# -*- coding: utf-8 -*-
"""Живой пинг не теряется, когда бот гасит рекламу в том же чате.

Сценарий владельца: в чате висит непрочитанный настоящий вопрос, а следом
прилетает рекламный пинг. Читать историю «до рекламы» — значит пометить
прочитанным и настоящий вопрос, то есть потерять лид. Поэтому бот сначала
копирует живой пинг в «Избранное» (`forward_messages("me", ...)`) и только
потом читает чат; если копия не удалась — история остаётся нетронутой.
"""
import asyncio
import time

from types import SimpleNamespace as NS

import bot
from telethon.tl.functions.channels import ReadHistoryRequest as ChannelReadHistoryRequest
from telethon.tl.functions.messages import GetPeerDialogsRequest
from telethon.tl.types import InputPeerChannel

from tests.support import CHAT_ID, MY_ID, RecordingClient

CHAT_PEER = InputPeerChannel(9988, 1)


class DialogClient(RecordingClient):
    """Клиент с ответом на GetPeerDialogsRequest и необязательным отказом форварда."""

    def __init__(self, read_max=0, forward_fails=False):
        super().__init__()
        self.read_max = read_max
        self.forward_fails = forward_fails

    async def __call__(self, request):
        self.requests.append(request)
        if isinstance(request, GetPeerDialogsRequest):
            return NS(dialogs=[NS(read_inbox_max_id=self.read_max)])
        return None

    async def forward_messages(self, to_peer, messages, from_peer=None, **kw):
        if self.forward_fails:
            raise RuntimeError("Избранное недоступно")
        self.forwarded.append({"to": to_peer, "messages": messages, "from": from_peer})
        return [NS(id=1)]


def spam_message(mid=9000):
    return NS(id=mid, chat_id=CHAT_ID, sender_id=666, entities=[], media=None,
              raw_text="🔥 прайс", message="🔥 прайс", input_chat=CHAT_PEER)


def clear(client, mid=9000, protect=False):
    asyncio.run(bot.clear_spam_mention(client, CHAT_PEER, spam_message(mid),
                                      account_id=MY_ID, chat_id=CHAT_ID,
                                      protect_unread_history=protect))
    return client


def read_history_calls(client):
    return [r for r in client.requests if isinstance(r, ChannelReadHistoryRequest)]


def has_dialog_lookup(client):
    return any(isinstance(r, GetPeerDialogsRequest) for r in client.requests)


# --------------------------------------------------------------------------- #
# основной сценарий
# --------------------------------------------------------------------------- #
def test_unread_genuine_ping_is_copied_to_saved_messages_before_reading(tmp_db):
    bot.note_genuine_ping(MY_ID, CHAT_ID, 5000)
    client = DialogClient(read_max=0)

    clear(client, mid=9000)

    assert client.forwarded == [{"to": "me", "messages": 5000, "from": CHAT_PEER}]
    assert read_history_calls(client), "после сохранения пинга чат должен читаться"


def test_reading_is_cancelled_when_the_ping_could_not_be_saved(tmp_db):
    """Не смогли спасти лид — не читаем чат, иначе пинг исчезнет молча."""
    bot.note_genuine_ping(MY_ID, CHAT_ID, 5000)
    client = DialogClient(read_max=0, forward_fails=True)

    clear(client, mid=9000)

    assert read_history_calls(client) == []


def test_already_read_ping_needs_no_copy(tmp_db):
    bot.note_genuine_ping(MY_ID, CHAT_ID, 5000)
    client = DialogClient(read_max=6000)

    clear(client, mid=9000)

    assert client.forwarded == []
    assert read_history_calls(client)


def test_expired_ping_does_not_block_reading(tmp_db):
    bot._GENUINE_PINGS[(MY_ID, CHAT_ID)] = (5000, time.time() - bot.GENUINE_PING_TTL - 60)
    client = DialogClient(read_max=0)

    clear(client, mid=9000)

    assert client.forwarded == []
    assert read_history_calls(client)


def test_no_pending_ping_means_no_dialog_lookup(tmp_db):
    client = DialogClient(read_max=0)

    clear(client, mid=9000)

    assert has_dialog_lookup(client) is False
    assert client.forwarded == []
    assert read_history_calls(client)


def test_older_ping_is_not_copied_for_a_newer_spam_message(tmp_db):
    """Пинг после рекламы сам придёт своим апдейтом — копировать нечего."""
    bot.note_genuine_ping(MY_ID, CHAT_ID, 9500)
    client = DialogClient(read_max=0)

    clear(client, mid=9000)

    assert client.forwarded == []
    assert has_dialog_lookup(client) is False
    assert read_history_calls(client)


def test_the_same_ping_is_copied_only_once(tmp_db):
    bot.note_genuine_ping(MY_ID, CHAT_ID, 5000)
    client = DialogClient(read_max=0)
    clear(client, mid=9000)

    # Второй рекламный пинг, а живой пинг всё ещё «висит» в кэше.
    bot.note_genuine_ping(MY_ID, CHAT_ID, 5000)
    clear(client, mid=9100)

    assert len(client.forwarded) == 1, "в Избранное не должно прилетать две копии"
    assert len(read_history_calls(client)) == 2


def test_preserve_ping_reports_success_and_failure(tmp_db):
    ok = DialogClient(read_max=0)
    assert asyncio.run(bot._preserve_ping(ok, CHAT_PEER, CHAT_ID, 42, MY_ID)) is True
    assert ok.forwarded[0]["to"] == "me"

    broken = DialogClient(read_max=0, forward_fails=True)
    assert asyncio.run(bot._preserve_ping(broken, CHAT_PEER, CHAT_ID, 43, MY_ID)) is False
