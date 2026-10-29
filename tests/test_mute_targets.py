# -*- coding: utf-8 -*-
"""Мьют человека, а не одного сообщения.

Проверяем то, из-за чего всё начиналось: `.мутить` ответом на сообщение должен
глушить автора целиком (текст, медиа, правки, следующие сообщения), а не только
то сообщение, на которое ответили. Отдельно — мьют «только в этом чате» и
размут, который не сносит глобальный мьют.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace as NS

from telethon.tl.types import InputPeerChannel, MessageMediaPhoto, User

import bot
from tests.support import CHAT_ID, MY_ID, RecordingClient, command_event, group_event, make_handlers

SENDER = 456789
OTHER_CHAT = -100777


class MuteClient(RecordingClient):
    """Клиент, который умеет резолвить @username в человека."""

    def __init__(self, user_id: int = SENDER, username: str = "spammer"):
        super().__init__()
        self.user_id = user_id
        self.username = username

    async def get_entity(self, peer):
        return User(
            id=self.user_id,
            access_hash=1,
            first_name="Spam",
            last_name="Bot",
            username=self.username,
        )


def reply_message(sender: int = SENDER, mid: int = 100, text: str = "реклама"):
    return NS(
        id=mid,
        sender_id=sender,
        raw_text=text,
        message=text,
        entities=[],
        media=None,
        input_chat=InputPeerChannel(9988, 1),
    )


def command_with_reply(raw: str, sender: int = SENDER, client=None):
    event = command_event(raw)
    event.is_reply = True
    event.get_reply_message = _async_return(reply_message(sender))
    return event


def _async_return(value):
    async def _inner(*_a, **_kw):
        return value
    return _inner


def run_command(raw: str, *, sender: int = SENDER, reply: bool = True):
    client = MuteClient()
    handlers = make_handlers(client)
    event = command_with_reply(raw, sender=sender) if reply else command_event(raw)
    asyncio.run(handlers["command_dispatcher"](event))
    return client, event


def incoming(sender=SENDER, chat=CHAT_ID, mid=200, media=None, text="следующее сообщение"):
    event = group_event(text=text, mid=mid, sender_id=sender, chat_id=chat, media=media)
    return event


def test_reply_mute_mutes_the_author_everywhere(tmp_db):
    run_command(".мутить")
    bot.mute_cache_rebuild(MY_ID)

    assert bot.mute_action_for(MY_ID, SENDER, CHAT_ID) == "silent"
    assert bot.mute_action_for(MY_ID, SENDER, OTHER_CHAT) == "silent", "мьют должен работать во всех чатах"
    assert bot.mute_action_for(MY_ID, 999999, CHAT_ID) is None


def test_mute_only_this_chat_does_not_touch_other_chats(tmp_db):
    run_command(".мутить тут")
    bot.mute_cache_rebuild(MY_ID)

    assert bot.mute_action_for(MY_ID, SENDER, CHAT_ID) == "silent"
    assert bot.mute_action_for(MY_ID, SENDER, OTHER_CHAT) is None
    assert bot.mute_scope_for(MY_ID, SENDER, CHAT_ID) == "user_chat"


def test_mute_by_username_and_id(tmp_db):
    run_command(".мутить @spammer удалить", reply=False)
    bot.mute_cache_rebuild(MY_ID)
    assert bot.mute_action_for(MY_ID, SENDER, CHAT_ID) == "delete"

    run_command(".мутить 456789 варн", reply=False)
    bot.mute_cache_rebuild(MY_ID)
    assert bot.mute_action_for(MY_ID, SENDER, CHAT_ID) == "warn"


def test_global_and_local_mute_can_coexist(tmp_db):
    run_command(".мутить @spammer", reply=False)
    run_command(".мутить @spammer тут бан", reply=False)
    bot.mute_cache_rebuild(MY_ID)

    # В этом чате действует более конкретный режим, в другом — глобальный.
    assert bot.mute_action_for(MY_ID, SENDER, CHAT_ID) == "ban"
    assert bot.mute_action_for(MY_ID, SENDER, OTHER_CHAT) == "silent"


def test_unmute_here_keeps_global_mute(tmp_db):
    run_command(".мутить @spammer", reply=False)
    run_command(".мутить @spammer тут", reply=False)
    bot.mute_cache_rebuild(MY_ID)

    run_command(".размутить @spammer тут", reply=False)
    bot.mute_cache_rebuild(MY_ID)
    assert bot.mute_action_for(MY_ID, SENDER, CHAT_ID) == "silent"
    assert bot.mute_action_for(MY_ID, SENDER, OTHER_CHAT) == "silent"

    run_command(".размутить @spammer", reply=False)
    bot.mute_cache_rebuild(MY_ID)
    assert bot.mute_action_for(MY_ID, SENDER, CHAT_ID) is None


def test_incoming_handler_silences_a_muted_author_in_another_chat(tmp_db):
    run_command(".мутить")
    bot.mute_cache_rebuild(MY_ID)
    client = MuteClient()
    handlers = make_handlers(client)

    asyncio.run(handlers["incoming_handler"](incoming(chat=OTHER_CHAT, mid=301)))
    names = [type(r).__name__ for r in client.requests]
    assert "ReadMessageContentsRequest" in names
    assert "ReadHistoryRequest" in names


def test_media_only_message_is_muted_too(tmp_db):
    run_command(".мутить удалить")
    bot.mute_cache_rebuild(MY_ID)
    client = MuteClient()
    handlers = make_handlers(client)

    event = incoming(mid=302, media=MessageMediaPhoto(photo=None), text="")
    asyncio.run(handlers["incoming_handler"](event))
    assert client.deleted, "медиа без текста тоже должно удаляться"


def test_edit_of_muted_message_does_not_bypass_the_mute(tmp_db):
    run_command(".мутить удалить")
    bot.mute_cache_rebuild(MY_ID)
    client = MuteClient()
    handlers = make_handlers(client)

    event = incoming(mid=303, text="безобидный текст, потом реклама")
    asyncio.run(handlers["edited_spam_handler"](event))
    assert client.deleted and client.deleted[0]["ids"] == [303]


def test_chat_scope_with_ban_falls_back_to_silent(tmp_db):
    run_command(".мутить чат бан", reply=False)
    bot.mute_cache_rebuild(MY_ID)
    assert bot.mute_action_for(MY_ID, SENDER, CHAT_ID) == "ban"
    assert bot.mute_scope_for(MY_ID, SENDER, CHAT_ID) == "chat"

    client = MuteClient()
    handlers = make_handlers(client)
    asyncio.run(handlers["incoming_handler"](incoming(mid=304)))
    assert client.permissions == [], "нельзя банить всех участников чата"


def test_mute_survives_cache_rebuild(tmp_db):
    run_command(".мутить")
    bot._MUTE_ACTION_CACHE.clear()
    bot._MUTE_CACHE.clear()
    bot.mute_cache_rebuild(MY_ID)
    assert bot.mute_action_for(MY_ID, SENDER, OTHER_CHAT) == "silent"


def test_mute_list_shows_scope(tmp_db):
    run_command(".мутить @spammer", reply=False)
    run_command(".мутить @spammer тут", reply=False)
    bot.mute_cache_rebuild(MY_ID)
    client = MuteClient()
    handlers = make_handlers(client)
    event = command_event(".заглушенные")
    asyncio.run(handlers["command_dispatcher"](event))
    text = "\n".join(event.replies)
    assert "везде" in text
    assert "чат" in text
