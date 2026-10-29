# -*- coding: utf-8 -*-
"""Мьюты: что именно бот делает с сообщением заглушённого человека.

Четыре режима (`silent`, `delete`, `warn`, `ban`) отличаются только реакцией
после того, как сообщение уже помечено прочитанным — иначе пуш и бейдж
упоминания остаются на телефоне. Отдельная история — мьют на весь чат: в
чате нельзя раздавать баны и варны, поэтому `ban`/`warn` там принудительно
превращаются в `silent`.
"""
import asyncio

from types import SimpleNamespace as NS

from telethon.tl.functions.channels import (
    ReadHistoryRequest as ChannelReadHistoryRequest,
    ReadMessageContentsRequest as ChannelReadContentsRequest,
)
from telethon.tl.types import InputPeerChannel, MessageMediaPhoto

import bot
from tests.support import CHAT_ID, MY_ID, RecordingClient, command_event, group_event, make_handlers

SENDER = 456789


def mute_message(mid=8001, sender=SENDER, text="смотри прайс"):
    return NS(
        id=mid,
        sender_id=sender,
        raw_text=text,
        message=text,
        entities=[],
        media=None,
        input_chat=InputPeerChannel(9988, 1),
    )


def run_action(action, *, client=None, mid=8001, sender=SENDER):
    client = client or RecordingClient()
    msg = mute_message(mid=mid, sender=sender)
    asyncio.run(bot.apply_mute_action(client, msg, MY_ID, CHAT_ID, action))
    return client


def read_requests(client):
    return [type(r) for r in client.requests
            if isinstance(r, (ChannelReadContentsRequest, ChannelReadHistoryRequest))]


# --------------------------------------------------------------------------- #
# silent
# --------------------------------------------------------------------------- #
def test_silent_marks_the_message_read_and_stops_there():
    client = run_action("silent")
    assert len(read_requests(client)) == 2, "ожидались readMessageContents + readHistory"
    assert client.deleted == []
    assert client.sent_messages == []
    assert client.permissions == []


def test_silent_clears_the_mention_and_the_unread_badge():
    client = run_action("silent")
    names = [type(r).__name__ for r in client.requests]
    assert "ReadMessageContentsRequest" in names
    assert "ReadHistoryRequest" in names


# --------------------------------------------------------------------------- #
# delete
# --------------------------------------------------------------------------- #
def test_delete_marks_read_then_deletes_the_message():
    client = run_action("delete", mid=8002)
    assert client.deleted, "сообщение не удалено"
    assert client.deleted[0]["ids"] == [8002]
    assert client.deleted[0]["chat_id"] == CHAT_ID
    assert len(read_requests(client)) == 2
    assert client.sent_messages == []


# --------------------------------------------------------------------------- #
# warn
# --------------------------------------------------------------------------- #
def test_warn_marks_read_and_replies_a_warning(tmp_db):
    client = run_action("warn", mid=8003)
    assert len(client.sent_messages) == 1
    sent = client.sent_messages[0]
    assert sent["kwargs"].get("reply_to") == 8003
    assert "игнор" in sent["message"].lower()
    assert client.deleted == []


def test_warn_is_rate_limited_per_person(tmp_db):
    client = RecordingClient()
    run_action("warn", client=client, mid=8004)
    run_action("warn", client=client, mid=8005)
    assert len(client.sent_messages) == 1, "варн не должен спамить в чат на каждое сообщение"


# --------------------------------------------------------------------------- #
# ban
# --------------------------------------------------------------------------- #
def test_ban_takes_away_the_right_to_write():
    client = run_action("ban", mid=8006)
    assert client.permissions, "edit_permissions не вызван"
    ban = client.permissions[0]
    assert ban["user_id"] == SENDER
    assert ban["kwargs"].get("view_messages") is False
    assert client.deleted == []
    assert len(read_requests(client)) == 2


# --------------------------------------------------------------------------- #
# обработчик входящих: мьют стоит до пинга и до счётчика
# --------------------------------------------------------------------------- #
def test_muted_sender_never_reaches_ping_or_counter(tmp_db):
    tmp_db.add_muted_peer(peer_id=SENDER, peer_key=SENDER, account_id=MY_ID, action="silent")
    bot.mute_cache_rebuild(MY_ID)

    counter_hits = []
    client = RecordingClient()
    handlers = make_handlers(client, broadcaster=NS(on_incoming_message=counter_hits.append))
    event = group_event(text="🔥 прайс\nКупить: @shop", mentioned=True, mid=8010)

    asyncio.run(handlers["incoming_handler"](event))

    assert counter_hits == [], "мьют не должен увеличивать счётчик рассылки"
    assert len(read_requests(client)) == 2


def test_muted_media_message_is_also_silenced(tmp_db):
    tmp_db.add_muted_peer(peer_id=SENDER, peer_key=SENDER, account_id=MY_ID, action="silent")
    bot.mute_cache_rebuild(MY_ID)

    counter_hits = []
    client = RecordingClient()
    handlers = make_handlers(client, broadcaster=NS(on_incoming_message=counter_hits.append))
    event = group_event(text="", mentioned=True, media=MessageMediaPhoto(), mid=8011)

    asyncio.run(handlers["incoming_handler"](event))

    assert counter_hits == []
    assert client.sent_messages == []
    assert len(read_requests(client)) == 2


def test_chat_scope_ban_is_downgraded_to_silent(tmp_db):
    """В чате нельзя банить всех подряд: ban из мьюта чата = тишина."""
    client = RecordingClient()
    handlers = make_handlers(client)
    asyncio.run(handlers["command_dispatcher"](command_event(".мутить чат бан")))

    assert bot.mute_action_for(MY_ID, SENDER, CHAT_ID) == "ban"
    assert bot.mute_scope_for(MY_ID, SENDER, CHAT_ID) == "chat"

    asyncio.run(handlers["incoming_handler"](group_event(text="привет", mid=8012)))

    assert client.permissions == [], "бан в чате не должен вызывать edit_permissions"
    assert client.deleted == []
    assert len(read_requests(client)) == 2


def test_chat_scope_warn_is_also_downgraded_to_silent(tmp_db):
    client = RecordingClient()
    handlers = make_handlers(client)
    asyncio.run(handlers["command_dispatcher"](command_event(".мутить чат варн")))

    asyncio.run(handlers["incoming_handler"](group_event(text="привет", mid=8013)))

    assert client.sent_messages == [], "варн в чате превращается в тишину"
    assert len(read_requests(client)) == 2


# --------------------------------------------------------------------------- #
# команды мьюта и размьюта
# --------------------------------------------------------------------------- #
def test_mute_command_stores_the_action(tmp_db):
    client = RecordingClient()
    handlers = make_handlers(client)
    asyncio.run(handlers["command_dispatcher"](command_event(f".мутить {SENDER} удалить")))

    rows = tmp_db.list_muted_peers(account_id=MY_ID)
    assert len(rows) == 1
    assert rows[0]["peer_key"] == SENDER
    assert rows[0]["action"] == "delete"
    assert bot.mute_action_for(MY_ID, SENDER) == "delete"


def test_unmute_chat_restores_the_chat(tmp_db):
    client = RecordingClient()
    handlers = make_handlers(client)
    asyncio.run(handlers["command_dispatcher"](command_event(".мутить чат")))
    assert bot.is_peer_muted(MY_ID, None, CHAT_ID) is True

    asyncio.run(handlers["command_dispatcher"](command_event(".размутить чат")))

    assert bot.is_peer_muted(MY_ID, None, CHAT_ID) is False
    assert tmp_db.remove_muted_peer(CHAT_ID, account_id=MY_ID, scope="chat") == 0


def test_unmute_by_username_removes_the_user_mute(tmp_db):
    tmp_db.add_muted_peer(peer_id=SENDER, peer_key=SENDER, username="spammer",
                          account_id=MY_ID, action="warn")
    bot.mute_cache_rebuild(MY_ID)

    client = RecordingClient(entities={"spammer": SENDER})
    handlers = make_handlers(client)
    asyncio.run(handlers["command_dispatcher"](command_event(".размутить @spammer")))

    assert bot.mute_action_for(MY_ID, SENDER) is None
    assert tmp_db.list_muted_peers(account_id=MY_ID) == []


def test_mute_list_shows_actions(tmp_db):
    tmp_db.add_muted_peer(peer_id=1, peer_key=1, username="first", account_id=MY_ID, action="delete")
    tmp_db.add_muted_peer(peer_id=CHAT_ID, peer_key=CHAT_ID, account_id=MY_ID, scope="chat", action="silent")

    client = RecordingClient()
    handlers = make_handlers(client)
    event = command_event(".заглушенные")
    asyncio.run(handlers["command_dispatcher"](event))

    text = "\n".join(event.replies)
    assert "удаление" in text
    assert "чат" in text
