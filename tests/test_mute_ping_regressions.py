import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from telethon.tl.functions.channels import (
    ReadHistoryRequest as ChannelReadHistory,
    ReadMessageContentsRequest as ChannelReadContents,
)
from telethon.tl.types import InputPeerChannel, PeerChannel

import bot
from tests.support import CHAT_ID, MY_ID, RecordingClient, command_event, group_event, make_handlers

SENDER = 456789
CHANNEL_SENDER = -1000000456789
PEER = InputPeerChannel(9988, 123456)
SCREENSHOT = (
    'ПРАЙС деньги\n________________\nМАКС 8$ НЕРЕГ МОМЕНТ ОПЛАТА\n'
    '________________\nВОРК ПО ФИЗ НОМЕРАМ по 28$ выгодная тема для вас и для меня\n'
    'билайн\nсб-моб\nмегафон\nмтс\nт-мобайл\n________________\n'
    'ПИСАТЬ @seller_shop\nНАС УЖЕ 1300+\nМОЯ РЕПУТАЦИЯ В ТИМЕ +rep\n'
    'ТИМА У НЕГО В БИО\n@seller_shop\nОтправлено с помощью @sender_bot'
)
TARIFF = ('РЕПОСТЫ:\n10 минут — 1 Ⓥ\n30 минут — 1.5 Ⓥ\n'
          '1 час — 2.5 Ⓥ\n12 часов — 5 Ⓥ\n24 часа — 8 Ⓥ\nПисать @seller_shop')


def reply_command(raw='.мутить', sender=SENDER):
    message = group_event(text=SCREENSHOT, sender_id=sender, mentioned=True).message
    event = command_event(raw)
    event.is_private = False
    event.is_reply = True
    event.input_chat = PEER
    event.get_reply_message = AsyncMock(return_value=message)
    return event, message


@pytest.mark.parametrize('watermark', ['', '\nОтправлено с помощью @sender_bot'])
@pytest.mark.parametrize('mentioned', [False, True])
def test_screenshot_catalogue_is_detected_without_our_username(watermark, mentioned):
    text = SCREENSHOT.split('\nОтправлено с помощью')[0] + watermark
    assert bot.should_auto_read(text, NS(entities=[], mentioned=mentioned), is_ping=False)


def test_repost_tariff_with_contact_is_an_ad_without_watermark_or_ping():
    assert bot.should_auto_read(TARIFF, NS(entities=[]), is_ping=False)


@pytest.mark.parametrize('text', [
    'РЕПОСТЫ: есть прайс? @seller_shop',
    'Можешь купить рекламу? @seller_shop',
    'Расписание встречи:\n10 минут — 1 вопрос\n30 минут — 2 вопрос\n1 час — 3 вопрос\n@friendname',
])
def test_tariff_detection_preserves_questions_and_ordinary_schedules(text):
    assert not bot.should_auto_read(text, NS(entities=[]), is_ping=False)


def test_reply_mute_clears_the_message_that_already_pinged(tmp_db):
    client = RecordingClient()
    handlers = make_handlers(client)
    event, message = reply_command()
    asyncio.run(handlers['command_dispatcher'](event))
    assert bot.mute_action_for(MY_ID, SENDER, CHAT_ID) == 'silent'
    contents = [r for r in client.requests if isinstance(r, ChannelReadContents)]
    history = [r for r in client.requests if isinstance(r, ChannelReadHistory)]
    assert [r.id for r in contents] == [[message.id]]
    assert [r.max_id for r in history] == [message.id]


def test_cross_chat_quote_never_reads_the_command_chat_with_foreign_message_id(tmp_db):
    client = RecordingClient()
    handlers = make_handlers(client)
    event, message = reply_command()
    message.chat_id = -1000000888800
    asyncio.run(handlers['command_dispatcher'](event))
    assert bot.mute_action_for(MY_ID, SENDER) == 'silent'
    assert not any(isinstance(r, (ChannelReadContents, ChannelReadHistory)) for r in client.requests)


@pytest.mark.parametrize('handler', ['incoming_handler', 'edited_spam_handler'])
def test_muted_message_uses_event_peer_when_message_cannot_resolve_chat(tmp_db, handler):
    tmp_db.add_muted_peer(SENDER, account_id=MY_ID)
    client = RecordingClient()
    client.get_input_entity = AsyncMock(side_effect=RuntimeError('cache miss'))
    handlers = make_handlers(client)
    event = group_event(text=SCREENSHOT, mentioned=True)
    event.input_chat = PEER
    del event.message.input_chat
    asyncio.run(handlers[handler](event))
    contents = [r for r in client.requests if isinstance(r, ChannelReadContents)]
    assert len(contents) == 1
    assert contents[0].channel.access_hash == PEER.access_hash
    client.get_input_entity.assert_not_awaited()


@pytest.mark.parametrize('handler', ['incoming_handler', 'edited_spam_handler'])
def test_channel_sender_fallback_matches_marked_channel_id(tmp_db, handler):
    tmp_db.add_muted_peer(CHANNEL_SENDER, account_id=MY_ID)
    client = RecordingClient()
    handlers = make_handlers(client)
    event = group_event(text='обычное сообщение', sender_id=None)
    event.message.from_id = PeerChannel(SENDER)
    asyncio.run(handlers[handler](event))
    assert any(isinstance(r, ChannelReadContents) for r in client.requests)


def test_reply_channel_mute_keeps_user_and_channel_namespaces_distinct(tmp_db):
    client = RecordingClient()
    handlers = make_handlers(client)
    event, message = reply_command(sender=None)
    message.from_id = PeerChannel(SENDER)
    asyncio.run(handlers['command_dispatcher'](event))
    assert bot.mute_action_for(MY_ID, CHANNEL_SENDER, CHAT_ID) == 'silent'
    assert bot.mute_action_for(MY_ID, SENDER, CHAT_ID) is None


def test_failed_current_read_is_reported_not_claimed_as_silenced(tmp_db):
    client = RecordingClient()
    client.get_input_entity = AsyncMock(side_effect=RuntimeError('cache miss'))
    handlers = make_handlers(client)
    event, message = reply_command()
    del message.input_chat
    del event.input_chat
    with patch.object(bot, 'log_error') as errors:
        asyncio.run(handlers['command_dispatcher'](event))
    assert bot.mute_action_for(MY_ID, SENDER) == 'silent'
    assert errors.called
    assert 'не удалось' in '\n'.join(event.replies).lower()


def test_slow_contents_rpc_does_not_delay_history_read(monkeypatch):
    monkeypatch.setattr(bot, 'READ_RPC_TIMEOUT', 0.03, raising=False)
    history_sent = asyncio.Event()
    concurrent_history = []

    class Client(RecordingClient):
        async def __call__(self, request):
            self.requests.append(request)
            if isinstance(request, ChannelReadContents):
                await history_sent.wait()
                concurrent_history.append(True)
                await asyncio.Future()
            if isinstance(request, ChannelReadHistory):
                history_sent.set()
            return True

    event = group_event()
    with patch.object(bot, 'log_error') as errors:
        async def run():
            return await asyncio.wait_for(bot.mark_message_read(Client(), PEER, event.message, CHAT_ID), 2.0)
        result = asyncio.run(run())
    assert history_sent.is_set()
    assert concurrent_history == [True]
    assert result is False
    assert errors.called


def test_read_rpc_false_is_a_failure_not_success():
    class Client(RecordingClient):
        async def __call__(self, request):
            self.requests.append(request)
            return False if isinstance(request, ChannelReadContents) else True

    with patch.object(bot, 'log_error') as errors:
        result = asyncio.run(bot.mark_message_read(Client(), PEER, group_event().message, CHAT_ID))
    assert result is False
    assert errors.called


def test_ad_clearing_does_not_await_contents_before_sending_history(monkeypatch):
    monkeypatch.setattr(bot, 'READ_RPC_TIMEOUT', 0.03, raising=False)
    history_sent = asyncio.Event()
    concurrent = []

    class Client(RecordingClient):
        async def __call__(self, request):
            self.requests.append(request)
            if isinstance(request, ChannelReadContents):
                await history_sent.wait()
                concurrent.append(True)
                await asyncio.Future()
            if isinstance(request, ChannelReadHistory):
                history_sent.set()
            return True

    with patch.object(bot, 'log_error') as errors:
        async def run():
            await asyncio.wait_for(bot.clear_spam_mention(Client(), PEER, group_event().message,
                                                          account_id=MY_ID, chat_id=CHAT_ID), 2.0)
        asyncio.run(run())
    assert concurrent == [True]
    assert errors.called


def test_ping_diagnostic_reports_decision_without_reading_history(tmp_db):
    tmp_db.add_muted_peer(SENDER, account_id=MY_ID)
    client = RecordingClient()
    handlers = make_handlers(client)
    event, _ = reply_command('.пингдиаг')
    asyncio.run(handlers['command_dispatcher'](event))
    output = '\n'.join(event.replies).lower()
    assert 'реклама: да' in output
    assert 'мьют: silent' in output
    assert not any(isinstance(r, (ChannelReadContents, ChannelReadHistory)) for r in client.requests)


def test_diagnostic_does_not_claim_antispam_runs_in_private_chats(tmp_db):
    client = RecordingClient()
    handlers = make_handlers(client)
    event, message = reply_command('.пингдиаг')
    event.is_private = True
    message.is_private = True
    asyncio.run(handlers['command_dispatcher'](event))
    assert 'Ожидаемое действие: пропуск' in '\n'.join(event.replies)
