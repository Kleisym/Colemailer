import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from telethon.tl.types import MessageEntityMentionName

import bot
from tests.support import MY_ID, group_event, make_handlers

# Screenshot text, with contact handles replaced and no invented entities.
ADS = [
    "ПРАЙС деньги\nМАКС 8$ НЕРЕГ МОМЕНТ ОПЛАТА\n"
    "ВОРК ПО ФИЗ НОМЕРАМ по 28$\nбилайн\nсб-моб\nмегафон\nмтс\nт-мобайл\n"
    "ПИСАТЬ @seller_shop\nНАС УЖЕ 1300+\nМОЯ РЕПУТАЦИЯ В ТИМЕ +rep\n"
    "ТИМА У НЕГО В БИО\n@contact_shop",
    "ИЩУ ВЗЛОТЫ/ОП\n1 0 . 5 0\n@seller_shop\n"
    "так же продаю привод кому интересно в лс\nпрайс + отзывы @review_shop",
]


@pytest.mark.parametrize('text', ADS)
def test_screenshot_ads_need_no_mention(text):
    assert bot.should_auto_read(text, NS(entities=[]), is_ping=False)


@pytest.mark.parametrize('handler', ['incoming_handler', 'edited_spam_handler'])
@pytest.mark.parametrize('mentioned', [False, True])
@pytest.mark.parametrize('text', ADS)
def test_ad_clearing_does_not_wait_for_reply_rpc(tmp_db, handler, mentioned, text):
    calls = []
    handlers = make_handlers(broadcaster=NS(on_incoming_message=lambda _: calls.append('counter')))
    event = group_event(text=text, is_reply=True, mentioned=mentioned)
    event.get_reply_message = AsyncMock(side_effect=RuntimeError('slow reply lookup'))

    async def cleared(*args, **kwargs):
        calls.append('clear')

    with patch.object(bot, 'clear_spam_mention', side_effect=cleared) as clear:
        asyncio.run(handlers[handler](event))
    event.get_reply_message.assert_not_awaited()
    clear.assert_awaited_once()
    # Telegram's bare mentioned flag does not identify this account.
    assert clear.call_args.kwargs['protect_unread_history'] is True
    assert calls == (['clear', 'counter'] if handler == 'incoming_handler' else ['clear'])


def test_hidden_entity_skips_reply_lookup():
    event = group_event(text='🔥 привет', is_reply=True, mentioned=True,
                        entities=[MessageEntityMentionName(0, 2, MY_ID)])
    assert asyncio.run(bot.classify_ping(event, event.message, event.raw_text,
                                        MY_ID, ['ownername'], ['Иван'])) == 'stealth'
    event.get_reply_message.assert_not_awaited()


def test_visible_username_skips_reply_lookup():
    event = group_event(text='@ownername сколько стоит?', is_reply=True, mentioned=True)
    assert asyncio.run(bot.classify_ping(event, event.message, event.raw_text,
                                        MY_ID, ['ownername'], ['Иван'])) == 'username'
    event.get_reply_message.assert_not_awaited()


def test_mentioned_flag_without_target_evidence_is_not_our_ping():
    event = group_event(text='Прайс без адресата', mentioned=True)
    assert asyncio.run(bot.classify_ping(event, event.message, event.raw_text,
                                         MY_ID, ['ownername'], ['Иван'])) == 'unknown'
    assert not bot.should_auto_read(event.raw_text, event.message,
                                    is_ping=False, ping_kind='unknown')


def test_failed_reply_lookup_does_not_turn_buyer_into_stealth_spam():
    event = group_event(text='Сколько стоит реклама?', is_reply=True, mentioned=True)
    event.get_reply_message = AsyncMock(side_effect=RuntimeError('offline'))
    kind = asyncio.run(bot.classify_ping(event, event.message, event.raw_text,
                                        MY_ID, ['ownername'], ['Иван']))
    assert kind == 'unknown'
    assert not bot.should_auto_read(event.raw_text, event.message, is_ping=True, ping_kind=kind)


def test_reply_lookup_has_a_deadline(monkeypatch):
    monkeypatch.setattr(bot, 'PING_REPLY_TIMEOUT', 0.01, raising=False)
    event = group_event(text='Привет', is_reply=True, mentioned=True)

    async def blocked():
        await asyncio.sleep(20)

    event.get_reply_message = blocked

    async def run():
        return await asyncio.wait_for(bot.classify_ping(event, event.message, event.raw_text,
                                                        MY_ID, [], []), timeout=0.25)
    assert asyncio.run(run()) == 'unknown'


def test_disabled_antispam_and_autosub_skip_reply_work(tmp_db):
    calls = []
    handlers = make_handlers(config=dict(auto_read_spam_pings=False, auto_sub_enabled=False),
                             broadcaster=NS(on_incoming_message=lambda _: calls.append('counter')))
    event = group_event(text='Привет', is_reply=True)
    asyncio.run(handlers['incoming_handler'](event))
    event.get_reply_message.assert_not_awaited()
    assert calls == ['counter']


def test_uncertain_reply_never_reads_history_as_hidden_spam(tmp_db):
    handlers = make_handlers()
    event = group_event(text='Сколько стоит реклама?', is_reply=True, mentioned=True)
    event.get_reply_message = AsyncMock(side_effect=RuntimeError('offline'))
    with patch.object(bot, 'clear_spam_mention', new_callable=AsyncMock) as clear:
        asyncio.run(handlers['incoming_handler'](event))
    clear.assert_not_awaited()
