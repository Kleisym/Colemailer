"""v2.2: ordinary ad notifications, hidden metadata, edits and unread safety."""
import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
import bot
from telethon.tl.types import (
    InputPeerChannel, InputPeerChat, MessageEntityTextUrl,
    MessageEntityMentionName,
)

# Visible text transcribed from the user's screenshot, without inventing entities.
SCREENSHOT_AD = """Актуальные прайсы
🇮🇳 Индия (+91) - 30 🌟
🇮🇩 Индонезия (+62) - 25 🌟
🇨🇴 Колумбия (+57) - 25 🌟
🇲🇲 Мьянма (+95) - 15 🌟
🇧🇩 Бангладеш (+880) - 75 🌟
🇧🇷 Бразилия (+51) - 25 🌟
🇨🇦 Канада (+1) - 15 🌟
🇲🇽 Мексика (+52) - 50 🌟
🇹🇷 Турция (+90) - 50 🌟
🇨🇱 Чили (+56) - 50 🌟
🇿🇦 ЮАР (+27) - 50 🌟
Также в продаже:
🇷🇺 Россия (+7) 2017 год - 800 🌟
🇹🇷 Турция (+90) 2016 год - 1000 🌟
ОТЗЫВЫ: https://t.me/loveas_otziv
Купить / Обратная связь:
@loveas_biznes
Переслано через NINJA"""


@pytest.mark.parametrize('kind', [None, 'stealth', 'name', 'username', 'reply'])
def test_screenshot_caught_with_or_without_ping(kind):
    assert bot.should_auto_read(SCREENSHOT_AD, is_ping=kind is not None, ping_kind=kind)


@pytest.mark.parametrize('text', [
    'Прайс\nИндия (+91) - 30\nТурция (+90) - 50\nКупить: @seller_shop',
    'В продаже\nРоссия 2017 - 800 ⭐\nТурция 2016 - 1000 ⭐\nОтзывы: t.me/shopreviews',
    'Продам аккаунты по 100₽, пишите @seller_shop',
    'Продаю звезды дешево, пиши в лс @starseller',
    'Зaрaбoтoк от 3000 в день, пиши @workonline',
    'Free crypto airdrop, claim now https://scam.example',
    SCREENSHOT_AD.replace('🌟', '⭐').replace(' - ', ' — '),
    SCREENSHOT_AD.replace('🌟', 'звёзд'),
    SCREENSHOT_AD.replace('🌟', '').replace(' - ', ' – '),
])
def test_strong_unsolicited_ads(text):
    assert bot.should_auto_read(text, is_ping=False), bot.calculate_spam_score(text)


@pytest.mark.parametrize('text', [
    'Привет, сколько стоит реклама?',
    'скинь прайс пожалуйста',
    'Куплю у тебя рекламу на завтра, есть место?',
    'оплатил 1000 звездами, проверь',
    'Вот контакты моего друга @friendname',
    'Посмотри документацию https://docs.python.org',
    '🇮🇳 Индия\n🇹🇷 Турция\n🇧🇷 Бразилия\n🇨🇦 Канада',
    'Наш маршрут\nИндия (+91)\nТурция (+90)\nКанада (+1)\nВернемся в пятницу',
    'Россия - 800\nТурция - 1000\nЭто расстояния по маршруту',
    'В магазине выросли цены, опять все дорого',
    'Есть аккаунты? Сколько стоит?',
    'Продал старый телефон за 1000₽, куплю новый',
    'Прайс на перевозку нужен, у кого есть?',
])
def test_ordinary_group_text_preserved(text):
    assert not bot.should_auto_read(text, is_ping=False), bot.calculate_spam_score(text)


def test_hidden_link_target_is_scored():
    text = 'Продаю аккаунты\nКупить\nОтзывы'
    msg = NS(entities=[MessageEntityTextUrl(offset=17, length=6, url='https://t.me/shopreviews')])
    assert bot.should_auto_read(text, msg, is_ping=False)


def test_inline_shop_buttons_are_scored():
    msg = NS(entities=[], reply_markup=NS(rows=[NS(buttons=[
        NS(text='Купить аккаунты дешево', url='https://t.me/shopreviews')
    ])]))
    assert bot.should_auto_read('', msg, is_ping=False)


def test_help_link_button_not_ad():
    msg = NS(entities=[], reply_markup=NS(rows=[NS(buttons=[
        NS(text='Документация', url='https://docs.python.org')
    ])]))
    assert not bot.should_auto_read('Привет! Инструкция по настройке', msg, is_ping=False)


def test_hidden_tag_cannot_hide_behind_reply():
    msg = NS(mentioned=True, entities=[MessageEntityMentionName(offset=0, length=1, user_id=123)])
    ev = NS(is_reply=True, get_reply_message=AsyncMock(return_value=NS(sender_id=123)))
    assert asyncio.run(bot.classify_ping(ev, msg, '🌟 прайс', 123, ['myusername'], ['Иван'])) == 'stealth'


class ClearClient:
    def __init__(self, previous=(), read_max=10, unread_count=2, fail=False, peer=None):
        self.previous = previous
        self.read_max = read_max
        self.unread_count = unread_count
        self.fail = fail
        self.calls = []
        self.peer = peer or InputPeerChannel(channel_id=900, access_hash=1)

    async def get_input_entity(self, peer):
        return self.peer

    async def __call__(self, req):
        self.calls.append(type(req).__name__)
        if type(req).__name__ == 'GetPeerDialogsRequest':
            if self.fail:
                raise RuntimeError('offline')
            return NS(dialogs=[NS(read_inbox_max_id=self.read_max, unread_count=self.unread_count)])

    async def get_messages(self, peer, **kwargs):
        assert kwargs == dict(min_id=self.read_max, max_id=50, limit=51)
        return self.previous


def clear(client):
    bot._GENUINE_PINGS.clear()
    asyncio.run(bot.clear_spam_mention(client, -100900, NS(id=50), account_id=123,
                                      chat_id=-100900, protect_unread_history=True))


@pytest.mark.parametrize('peer', [InputPeerChannel(900, 1), InputPeerChat(900)])
def test_single_unread_ad_can_clear_history(peer):
    client = ClearClient(peer=peer)
    clear(client)
    assert 'ReadHistoryRequest' in client.calls
    assert 'ReadMentionsRequest' not in client.calls
    assert 'ReadReactionsRequest' not in client.calls


@pytest.mark.parametrize('previous', [
    [NS(message='Привет, ответь пожалуйста', out=False, mentioned=False)],
    [NS(message='почем реклама?', out=False, mentioned=True)],
    [NS(message=SCREENSHOT_AD, out=False, mentioned=True)],
    [NS(message='', out=False, mentioned=False)],
    [NS(message=SCREENSHOT_AD, out=False), NS(message='оплатил', out=False)],
])
def test_unread_conversation_survives_even_after_restart(previous):
    client = ClearClient(previous=previous)
    clear(client)
    assert 'ReadHistoryRequest' not in client.calls


def test_only_unread_ads_can_clear_history():
    client = ClearClient(previous=[NS(message=SCREENSHOT_AD, out=False, mentioned=False)])
    clear(client)
    assert 'ReadHistoryRequest' in client.calls


@pytest.mark.parametrize('options', [dict(fail=True), dict(unread_count=100), dict(read_max=50),
                                    dict(previous=[NS(message=SCREENSHOT_AD)] * 51)])
def test_uncertain_backlog_and_old_edits_fail_closed(options):
    client = ClearClient(**options)
    clear(client)
    assert 'ReadHistoryRequest' not in client.calls


def make_handlers(config=None):
    handlers = {}
    class Client:
        def on(self, builder):
            def register(f):
                handlers[f.__name__] = f
                return f
            return register
    broadcaster = NS(on_incoming_message=lambda chat: None)
    bot.register_events(Client(), broadcaster, 987654321, config or dict(auto_sub_enabled=False))
    return handlers


def event(text=SCREENSHOT_AD, mid=888, private=False):
    return NS(chat_id=-1009988, id=mid, sender_id=456789, is_private=private,
              is_reply=False, raw_text=text, message=NS(id=mid, mentioned=False, entities=[]))


def test_handler_processes_no_ping_ads_and_edits():
    handlers = make_handlers()
    with patch.object(bot, 'clear_spam_mention', new_callable=AsyncMock) as clear_mock:
        asyncio.run(handlers['incoming_handler'](event()))
        assert clear_mock.await_count == 1
        assert clear_mock.call_args.kwargs['protect_unread_history'] is True
        asyncio.run(handlers['edited_spam_handler'](event()))
        assert clear_mock.await_count == 2


@pytest.mark.parametrize('name', ['incoming_handler', 'edited_spam_handler'])
@pytest.mark.parametrize('ev', [event('почем реклама?', mid=889), event(private=True, mid=890)])
def test_handler_does_not_touch_private_or_buyer_messages(name, ev):
    handlers = make_handlers()
    with patch.object(bot, 'clear_spam_mention', new_callable=AsyncMock) as clear_mock:
        asyncio.run(handlers[name](ev))
        clear_mock.assert_not_awaited()


def test_disabled_antispam_does_not_clear():
    handlers = make_handlers(dict(auto_sub_enabled=False, auto_read_spam_pings=False))
    with patch.object(bot, 'clear_spam_mention', new_callable=AsyncMock) as clear_mock:
        asyncio.run(handlers['incoming_handler'](event(mid=891)))
        asyncio.run(handlers['edited_spam_handler'](event(mid=891)))
        clear_mock.assert_not_awaited()


def test_current_telethon_button_schema():
    from telethon.tl import types
    if not hasattr(types, 'KeyboardInlineButton'):
        pytest.skip('Older Telethon uses a direct button.url instead')
    markup = types.ReplyInlineMarkup(rows=[types.KeyboardInlineButtonRow(buttons=[
        types.KeyboardInlineButton(text='Купить аккаунты', type=types.InlineButtonTypeUrl(url='https://t.me/shopreviews'))
    ])])
    assert bot.should_auto_read('Продаю аккаунты', NS(reply_markup=markup), is_ping=False)
