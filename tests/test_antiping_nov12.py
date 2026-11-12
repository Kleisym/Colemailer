"""Visible screenshot captions and the post-classification mute/read path."""
import asyncio
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock, patch

import pytest
from telethon.tl import types
from telethon.tl.functions.account import GetNotifySettingsRequest, UpdateNotifySettingsRequest
from telethon.tl.functions.channels import ReadHistoryRequest, ReadMessageContentsRequest
from telethon.tl.functions.messages import GetPeerDialogsRequest, GetUnreadMentionsRequest

import bot
from tests.support import CHAT_ID, MY_ID, RecordingClient, command_event, group_event, make_handlers

CAPTIONS = {
    'catalogue': 'ПРАЙС деньги\n________________\nМАКС 8$ НЕРЕГ МОМЕНТ ОПЛАТА БОТ @seller_bot\n'
                 '________________\nВОРК ПО ФИЗ НОМЕРАМ по 28$ выгодная тема для вас и для меня\n'
                 'билайн\nсб-моб\nмегафон\nмтс\nт-мобайл\nПИСАТЬ @seller_shop\n'
                 'НАС УЖЕ 1300+\nМОЯ РЕПУТАЦИЯ В ТИМЕ +rep\nТИМА У НЕГО В БИО\n'
                 '@seller_shop\nРассылка через @sigmasend',
    'tariff': 'Продам ОП в чате @chat_shop\n1 🔔 - 2.2₽\n12 часов - 100₽\n24 часа - 220₽\n'
              'Так же рекламирую ботов\nКуплю чаты\nОт 500+ человек в группе и с хорошим активом\n'
              'Пишите — @seller_shop\nРассылка через @Gigapust',
    'recruitment': '💲 ИЩУ ЛЮДЕЙ НА ВОРК!\nПРОФИТ: в первые день\nГРАФИК: свободный\n'
                   'ОБУЧЕНИЕ: БЕСПЛАТНО\nТРАФИК: предоставляем\nРаботаешь под процент, '
                   'желательно иметь базу знаний крипто (отправить/принять)\nПО РАБОТЕ ⬇️\n@work_shop',
    'clicks': 'клики в канале @click_shop (залив)\n100 кликов - по курсу 5$ / 170 / 2$ / 140 '
              '(уточнять в лс)\nделаю от 200 до 1к ю\nПисать в лс @seller_shop\n'
              'Отправлено с помощью @jruvusw',
    'free_gift': 'Хочешь улучшить свой подарок? 🎁\nХочешь также получить NFT бесплатно?\n'
                 'Тогда присоединяйся к Easy Gift: с нами более 2 миллиона пользователей.\n'
                 'https://t.me/gift_app?startapp=r_123\nhttps://t.me/gift_app?startapp=r_123\n'
                 'https://t.me/gift_app?startapp=r_123',
    'chat_invite': 'Ищешь чат для общения, знакомств и выгодных покупок или продаж?\n'
                   'Никаких рассыльщиков — только живые люди. Присоединяйся к нам.\n'
                   'https://t.me/chatmetro112\nhttps://t.me/chatmetro112',
    'game_buyup': 'СКУПАЮ BRAWL STARS\nОТ 75К И ВЫШЕ\nСО СМЕНОЙ ПОЧТЫ\nБЕЗ ДОП ЗАЩИТЫ\n'
                  'STANDOFF GOLD\nКУПЛЮ ГОЛДУ ОТ 500 ГОЛДЫ\nПОКУПАЮ ДОРОГИЕ НФТ, ЗВЁЗДЫ\n'
                  'ПИСАТЬ ТОЛЬКО @seller_shop',
}


@pytest.mark.parametrize('name', list(CAPTIONS))
def test_visible_caption_is_ad_without_invented_mention(name):
    assert bot.should_auto_read(CAPTIONS[name], NS(entities=[]), is_ping=False), bot.calculate_spam_score(CAPTIONS[name])


@pytest.mark.parametrize('text', [
    'Ищешь чат для общения? Вот ссылка https://t.me/chatmetro112',
    'Присоединяйся к созвону в 18:00, ссылку отправлю позже',
    'Можешь проверить https://t.me/chatmetro112? У меня эта ссылка https://t.me/chatmetro112 не работает',
    'Хочу купить у тебя рекламу на завтра, есть место?',
])
def test_conversation_is_not_an_ad(text):
    assert not bot.should_auto_read(text, NS(entities=[]), is_ping=False)


def test_system_reply_id_in_another_group_never_hides_mute_command(tmp_db):
    client = RecordingClient()
    handlers = make_handlers(client)
    first = command_event('.версия', chat_id=CHAT_ID)
    asyncio.run(handlers['command_dispatcher'](first))  # fake edit returns id 9003
    second = command_event('.мутить 8165378529', chat_id=-1007777, mid=9003)
    asyncio.run(handlers['command_dispatcher'](second))
    assert bot.mute_action_for(MY_ID, 8165378529, -1007777) == 'silent'
    assert second.replies


def test_ad_only_unread_mentions_do_not_block_safe_history_read(tmp_db):
    peer = types.InputPeerChannel(9988, 1)

    class Client(RecordingClient):
        async def __call__(self, request):
            self.requests.append(request)
            if isinstance(request, GetPeerDialogsRequest):
                return NS(dialogs=[NS(read_inbox_max_id=1, unread_count=3)])
            return True

        async def get_messages(self, *_args, **_kw):
            return [NS(id=5, message=CAPTIONS['catalogue'], entities=[], mentioned=True, out=False)]

    client = Client()
    result = asyncio.run(bot.clear_spam_mention(client, peer, NS(id=10),
                         account_id=MY_ID, chat_id=CHAT_ID, protect_unread_history=True))
    assert result is True
    assert any(isinstance(r, ReadHistoryRequest) for r in client.requests)


def test_receipt_burst_is_coalesced_per_chat_not_two_rpc_per_message():
    async def run():
        client = RecordingClient()
        peer = types.InputPeerChannel(9988, 1)
        results = await asyncio.gather(*(bot.mark_message_read(client, peer, NS(id=i), CHAT_ID)
                                         for i in range(1, 41)))
        assert all(results)
        contents = [r for r in client.requests if isinstance(r, ReadMessageContentsRequest)]
        history = [r for r in client.requests if isinstance(r, ReadHistoryRequest)]
        assert len(contents) == 1
        assert set(contents[0].id) == set(range(1, 41))
        assert [r.max_id for r in history] == [40]
    asyncio.run(run())


class NativeClient(RecordingClient):
    async def get_input_entity(self, peer):
        return types.InputPeerUser(peer, 123) if isinstance(peer, int) and peer > 0 else types.InputPeerChannel(9988, 123)

    async def __call__(self, request):
        self.requests.append(request)
        if isinstance(request, GetNotifySettingsRequest):
            return types.PeerNotifySettings(mute_until=0, show_previews=False,
                                           other_sound=types.NotificationSoundDefault())
        return True


def test_global_mute_applies_native_sender_notifications_and_unmute_restores(tmp_db):
    client = NativeClient()
    handlers = make_handlers(client)
    asyncio.run(handlers['command_dispatcher'](command_event('.мутить 8165378529')))
    settings = [r for r in client.requests if isinstance(r, UpdateNotifySettingsRequest)]
    assert len(settings) == 1
    assert settings[0].peer.peer.user_id == 8165378529
    assert settings[0].settings.mute_until == 2147483647
    asyncio.run(handlers['command_dispatcher'](command_event('.размутить 8165378529')))
    settings = [r for r in client.requests if isinstance(r, UpdateNotifySettingsRequest)]
    assert len(settings) == 2
    assert settings[-1].settings.mute_until == 0
    assert settings[-1].settings.show_previews is False


def test_local_sender_mute_does_not_change_other_chat_native_settings(tmp_db):
    client = NativeClient()
    handlers = make_handlers(client)
    asyncio.run(handlers['command_dispatcher'](command_event('.мутить 8165378529 тут')))
    assert bot.mute_action_for(MY_ID, 8165378529, CHAT_ID) == 'silent'
    assert not any(isinstance(r, UpdateNotifySettingsRequest) for r in client.requests)


def test_quiet_chat_disables_native_sound_without_reading_history(tmp_db):
    client = NativeClient()
    handlers = make_handlers(client)
    ev = command_event('.тишина')
    ev.is_private = False
    asyncio.run(handlers['command_dispatcher'](ev))
    updates = [r for r in client.requests if isinstance(r, UpdateNotifySettingsRequest)]
    assert len(updates) == 1
    assert isinstance(updates[0].settings.sound, types.NotificationSoundNone)
    assert updates[0].settings.mute_until == 2147483647
    assert not any(isinstance(r, ReadHistoryRequest) for r in client.requests)
    assert ev.replies


def test_quiet_restore_survives_restart_and_repeated_enable(tmp_db):
    client = NativeClient()
    assert asyncio.run(bot.set_managed_notification_mute(client, CHAT_ID, MY_ID, 'quiet_chat', True, quiet=True))
    assert asyncio.run(bot.set_managed_notification_mute(client, CHAT_ID, MY_ID, 'quiet_chat', True, quiet=True))
    fresh = NativeClient()
    assert asyncio.run(bot.set_managed_notification_mute(fresh, CHAT_ID, MY_ID, 'quiet_chat', False))
    settings = [r.settings for r in fresh.requests if isinstance(r, UpdateNotifySettingsRequest)]
    assert len(settings) == 1 and settings[0].mute_until == 0
    assert isinstance(settings[0].sound, types.NotificationSoundDefault)
    with tmp_db._conn() as conn:
        assert conn.execute('SELECT count(*) FROM managed_notifications').fetchone()[0] == 0


def test_native_restore_failure_keeps_snapshot_for_retry(tmp_db):
    client = NativeClient()
    assert asyncio.run(bot.set_managed_notification_mute(client, CHAT_ID, MY_ID, 'quiet_chat', True, quiet=True))
    broken = NativeClient()
    broken.__class__ = type('BrokenNative', (NativeClient,), {
        '__call__': AsyncMock(side_effect=RuntimeError('offline'))})
    assert not asyncio.run(bot.set_managed_notification_mute(broken, CHAT_ID, MY_ID, 'quiet_chat', False))
    with tmp_db._conn() as conn:
        assert conn.execute('SELECT count(*) FROM managed_notifications').fetchone()[0] == 1


def test_concurrent_native_mutes_preserve_both_reasons_and_original_snapshot(tmp_db):
    class SlowClient(NativeClient):
        async def __call__(self, request):
            if isinstance(request, GetNotifySettingsRequest):
                await asyncio.sleep(0.02)
            return await super().__call__(request)

    async def run():
        client = SlowClient()
        assert all(await asyncio.gather(
            bot.set_managed_notification_mute(client, CHAT_ID, MY_ID, 'quiet_chat', True),
            bot.set_managed_notification_mute(client, CHAT_ID, MY_ID, 'mute_chat', True)))
        assert len([r for r in client.requests if isinstance(r, GetNotifySettingsRequest)]) == 1
        with tmp_db._conn() as conn:
            row = conn.execute('SELECT reasons_json FROM managed_notifications').fetchone()
            assert set(json.loads(row[0])) == {'quiet_chat', 'mute_chat'}
        assert await bot.set_managed_notification_mute(client, CHAT_ID, MY_ID, 'quiet_chat', False)
        assert client.requests[-1].settings.mute_until == 2147483647
        assert await bot.set_managed_notification_mute(client, CHAT_ID, MY_ID, 'mute_chat', False)
        assert client.requests[-1].settings.mute_until == 0
    asyncio.run(run())


def test_unmute_reply_restores_native_settings(tmp_db):
    client = NativeClient()
    handlers = make_handlers(client)
    asyncio.run(handlers['command_dispatcher'](command_event('.мутить 8165378529')))
    ev = command_event('.размутить')
    ev.is_reply = True
    ev.get_reply_message = AsyncMock(return_value=NS(sender_id=8165378529, raw_text='ad'))
    asyncio.run(handlers['command_dispatcher'](ev))
    assert bot.mute_action_for(MY_ID, 8165378529, CHAT_ID) is None
    assert client.requests[-1].settings.mute_until == 0


def test_native_unmute_failure_is_reported_and_retry_retains_original(tmp_db):
    class BrokenRestore(NativeClient):
        async def __call__(self, request):
            if isinstance(request, UpdateNotifySettingsRequest) and request.settings.mute_until == 0:
                raise RuntimeError('offline')
            return await super().__call__(request)
    client = BrokenRestore()
    handlers = make_handlers(client)
    asyncio.run(handlers['command_dispatcher'](command_event('.мутить 8165378529')))
    ev = command_event('.размутить 8165378529')
    asyncio.run(handlers['command_dispatcher'](ev))
    assert '[MUTE-NATIVE]' in '\n'.join(ev.replies)
    with tmp_db._conn() as conn:
        assert conn.execute('SELECT count(*) FROM managed_notifications').fetchone()[0] == 1


def test_receipt_batches_never_mix_channels():
    async def run():
        client = RecordingClient()
        assert all(await asyncio.gather(*(
            bot.mark_message_read(client, types.InputPeerChannel(channel, 1), NS(id=i), -1000000-channel)
            for channel in (98, 99) for i in range(1, 4))))
        history = [r for r in client.requests if isinstance(r, ReadHistoryRequest)]
        contents = [r for r in client.requests if isinstance(r, ReadMessageContentsRequest)]
        assert len(history) == len(contents) == 2
        assert {r.channel.channel_id for r in contents} == {98, 99}
        assert all(r.id == [1, 2, 3] for r in contents)
    asyncio.run(run())


def test_saved_mutes_are_applied_to_telegram_on_upgrade(tmp_db):
    tmp_db.add_muted_peer(8165378529, account_id=MY_ID)
    tmp_db.add_muted_peer(8123456789, account_id=MY_ID, chat_id=CHAT_ID)  # local: no global native change
    client = NativeClient()
    asyncio.run(bot.sync_saved_native_mutes(client, MY_ID))
    updates = [r for r in client.requests if isinstance(r, UpdateNotifySettingsRequest)]
    assert len(updates) == 1 and updates[0].peer.peer.user_id == 8165378529


def test_cleanup_acks_only_ad_and_muted_mentions_no_genuine_buyer(tmp_db):
    tmp_db.add_muted_peer(8165378529, account_id=MY_ID)
    msgs = [NS(id=10, sender_id=1, message=CAPTIONS['catalogue'], entities=[], mentioned=True),
            NS(id=11, sender_id=8165378529, message='стикер', entities=[], mentioned=True),
            NS(id=12, sender_id=2, message='сколько стоит реклама?', entities=[], mentioned=True)]

    class Client(NativeClient):
        async def __call__(self, request):
            if isinstance(request, GetUnreadMentionsRequest):
                self.requests.append(request)
                return NS(messages=msgs)
            return await super().__call__(request)

    client = Client()
    handlers = make_handlers(client)
    ev = command_event('.очиститьпинги')
    ev.is_private = False
    asyncio.run(handlers['command_dispatcher'](ev))
    requests = [r for r in client.requests if isinstance(r, ReadMessageContentsRequest)]
    assert len(requests) == 1 and requests[0].id == [10, 11]
    assert not any(isinstance(r, ReadHistoryRequest) for r in client.requests)


def test_android_bridge_puts_bot_read_errors_into_visible_log(monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'android/app/src/main/python/bot_bridge.py'
    spec = importlib.util.spec_from_file_location('bridge_read_errors', path)
    bridge = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bridge)
    monkeypatch.setattr(bot, 'log_error', bot.log_error)
    monkeypatch.setattr(bot, 'log_info', bot.log_info)
    bridge.install_callback(NS(onLog=lambda _line: None))
    bot.log_error('[READ] readMessageContents: FloodWaitError wait=10s')
    assert '[READ]' in bridge.get_logs_since(0)


def test_android_filter_catches_same_visible_captions(tmp_path):
    javac, java = shutil.which('javac'), shutil.which('java')
    if not javac or not java:
        pytest.skip('JDK required')
    source = Path(__file__).resolve().parents[1] / 'android/app/src/main/java/com/colemailer/app/AdNotificationFilter.java'
    rows = ',\n'.join('{' + json.dumps(name) + ',' + json.dumps(text, ensure_ascii=True) + '}'
                       for name, text in CAPTIONS.items())
    harness = tmp_path / 'CaptionTest.java'
    harness.write_text('''package com.colemailer.app;
public class CaptionTest {
 public static void main(String[] args) {
  String[][] cases = {''' + rows + '''};
  java.util.List<String> missed = new java.util.ArrayList<>();
  for (String[] c : cases) if (!AdNotificationFilter.isAd(c[1])) missed.add(c[0]);
  if (!missed.isEmpty()) throw new AssertionError("missed=" + missed);
  if (AdNotificationFilter.isAd("Ищешь чат для общения? https://t.me/chatmetro112")) throw new AssertionError("normal invite");
  System.out.println("caption checks=" + cases.length);
 }
}''', encoding='utf-8')
    classes = tmp_path / 'classes'
    classes.mkdir()
    subprocess.run([javac, '-encoding', 'UTF-8', '-d', str(classes), str(source), str(harness)],
                   check=True, capture_output=True, text=True)
    result = subprocess.run([java, '-cp', str(classes), 'com.colemailer.app.CaptionTest'],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
