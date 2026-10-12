# -*- coding: utf-8 -*-
"""Regression tests for v2.1: obfuscated/stealth spam, phantom broadcasts,
counter retries, per-chat rotations, stop/delete scope and send fallbacks."""
import asyncio
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import bot
from bot import BroadcasterService, Database, should_auto_read, calculate_spam_score
from telethon import errors
from telethon.tl.types import MessageEntityMentionName, MessageMediaWebPage, MessageMediaPhoto

SPAM2 = [
 "Привет! Хочешь заработать? Пиши мне",
 "Ищу админов в канал, оплата от 500р в день",
 "Работа для подростков от 14 лет, 1500₽ в день, пиши +",
 "Нужны люди для простой работы, оплата каждый день",
 "Требуются курьеры, высокая оплата, пишите в лс",
 "🎁 Бесплатная раздача Telegram Premium! Переходи @freepremiumbot",
 "Получи бесплатно 100 звёзд: t.me/freestarsbot?start=123",
 "Скупаю юзы дорого",
 "Продам юз @abcd недорого",
 "Куплю каналы любой тематики, пишите",
 "Пиар в 50 чатах всего за 100₽, пиши",
 "Подпишись на мой канал пж t.me/mychannel1",
 "заходи в наш чат t.me/+AbCdEfGhIj",
 "Зaрaбoтoк от 3000 в день",
 "З.в.е.з.д.ы дешево",
 "𝐙𝐚𝐫𝐚𝐛𝐨𝐭𝐨𝐤 online",
 "Hello! Earn $500 daily from home, DM me",
 "Free crypto airdrop, claim now https://scam.xyz",
 "Investment opportunity, 30% weekly profit, contact @investpro",
 "Взаимный пиар? Пиши в лс",
 "Привет, глянь мой канал @kanal_superr",
 "Есть подработка, 2 часа в день, от 2000р",
 "Нужен человек на легкую работу, пиши в личку",
 "Обмен звезд на рубли, быстро",
 "Продаю премиум на год 1500р",
 "Telegram Premium дешево, пиши",
 "дарю подарки, пиши в лс кто хочет",
 "Отдам NFT бесплатно",
 "Буст канала, бусты для каналов дешево",
 "Делаю ботов на заказ, пиши",
 "Ищу партнера для бизнеса, вложения от 10к, доход 50%",
 "Здравствуйте, вы выиграли приз! Заберите по ссылке t.me/prizebot",
 "Вступай в нашу команду, работа удаленно",
 "Слив курсов, все курсы за 100₽",
 "Продам рекламу в чатах, охват 100к, прайс в лс",
 "💸 Легкие деньги 💸 пиши @money",
 "Помогу с накруткой, недорого",
 "скупаю тг аккаунты от 2020 года",
 "Продам виртуальные номера",
 "Кто хочет халявные звезды? Пишите",
]
HAM2 = [
 "@me привет, сколько стоит реклама у тебя?",
 "почем пост на сутки?",
 "привет, можно у тебя рекламу купить?",
 "спасибо, оплатил",
 "ок, жду реквизиты",
 "ты где пропал?",
 "кинь стату канала",
 "а закреп есть?",
 "давай по бартеру",
 "можешь разместить мой пост завтра в 12?",
 "сколько просят за ВП?",
 "ахах, ну ты даешь",
 "я тоже продаю рекламу, у нас похожие каналы",
 "у тебя сколько охват?",
 "хорошо, договорились",
 "реклама вышла, проверь",
 "оплатил звездами, проверь",
 "Да, интересно, напиши мне",
]
HAM3 = [
 "привет, у тебя есть свободное место на завтра под пост?",
 "скинь прайс пожалуйста",
 "сколько стоит закреп на 24 часа?",
 "го ВП? у меня 5к",
 "можешь скинуть ссылку на канал?",
 "оплатил, жду пост",
 "братан, ты мне должен 200р за прошлый пост",
 "не, спасибо, неинтересно",
 "привет, какая тематика у канала?",
 "почему пост удалил?",
 "Привет! Интересует реклама в твоем канале, напиши мне пожалуйста",
 "сделаешь скидку если возьму 3 поста?",
 "Купил бы рекламу на выходные, есть окна?",
 "а ты админ этого чата?",
 "ок, принял, скину креатив вечером",
 "это не я, это мой друг писал",
 "хорошо, тогда в 18:00 ставь",
 "оплата звездами подойдет?",
 "можно оплатить тоном?",
 "в лс скинул",
 "я тебе в лс написал",
 "ответь в лс плиз",
 "а чат живой вообще?",
 "сколько подписчиков на канале?",
 "дай ссылку на свой канал, гляну",
 "у меня есть канал на 3к, интересно ВП?",
]


class TestDetectionV3(unittest.TestCase):
    def test_new_spam_is_caught(self):
        for t in SPAM2:
            self.assertTrue(should_auto_read(t, is_ping=True), f"{t!r} {calculate_spam_score(t)}")

    def test_live_conversation_is_kept(self):
        for t in HAM2 + HAM3:
            self.assertFalse(should_auto_read(t, is_ping=True), f"{t!r} {calculate_spam_score(t)}")

    def test_normalization_folds_homoglyphs_and_spacing(self):
        norm, flags = bot.normalize_text("Зaрaбoтoк")
        self.assertIn("заработок", norm)
        norm, _ = bot.normalize_text("з.в.е.з.д.ы дешево")
        self.assertIn("звезды", norm)
        norm, flags = bot.normalize_text("𝐙𝐚𝐫𝐚𝐛𝐨𝐭𝐨𝐤")
        self.assertTrue(flags)

    def test_stealth_ping_is_always_spam(self):
        self.assertTrue(should_auto_read("привет", is_ping=True, ping_kind="stealth"))
        self.assertFalse(should_auto_read("привет, как дела?", is_ping=True, ping_kind="reply"))

    def test_media_ping_with_ad_caption_is_spam(self):
        self.assertTrue(should_auto_read("Скупаю звёзды, пиши", is_ping=True, ping_kind="username"))


class _Msg(SimpleNamespace):
    pass


class _Event:
    def __init__(self, reply=None, is_reply=False):
        self.is_reply = is_reply
        self._reply = reply

    async def get_reply_message(self):
        return self._reply


class TestPingClassification(unittest.TestCase):
    ME = 777

    def classify(self, text, msg, event=None):
        return asyncio.run(bot.classify_ping(event or _Event(), msg, text, self.ME, ["myname"], ["Вася"]))

    def test_not_a_ping(self):
        self.assertIsNone(self.classify("всем привет", _Msg(mentioned=False, entities=None)))

    def test_typed_username(self):
        self.assertEqual(self.classify("@myname глянь", _Msg(mentioned=True, entities=None)), "username")

    def test_reply_to_me(self):
        ev = _Event(reply=_Msg(sender_id=self.ME, out=True), is_reply=True)
        self.assertEqual(self.classify("ок", _Msg(mentioned=True, entities=None), ev), "reply")

    def test_mentioned_without_username_or_reply_is_stealth(self):
        self.assertEqual(self.classify("звезды дешево", _Msg(mentioned=True, entities=None)), "stealth")

    def test_hidden_entity_is_stealth(self):
        text = "Скидки ⁠"
        ent = MessageEntityMentionName(offset=len(text) - 1, length=1, user_id=self.ME)
        self.assertEqual(self.classify(text, _Msg(mentioned=True, entities=[ent])), "stealth")

    def test_name_entity_is_name(self):
        text = "Вася, привет"
        ent = MessageEntityMentionName(offset=0, length=4, user_id=self.ME)
        self.assertEqual(self.classify(text, _Msg(mentioned=True, entities=[ent])), "name")


class _DBCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._old_db = bot.db
        self.db = Database(db_path=Path(self.tmp.name) / "t.db")
        bot.db = self.db

    def tearDown(self):
        bot.db = self._old_db
        self.tmp.cleanup()


class _SendClient:
    def __init__(self):
        self.sent = []
        self.kwargs = []

    async def get_input_entity(self, peer):
        return peer

    async def send_message(self, peer, message=None, formatting_entities=None, **kw):
        self.sent.append((peer, message))
        self.kwargs.append(kw)


class TestCounterRetry(_DBCase):
    def test_failed_counter_send_does_not_fire_on_next_message(self):
        self.db.add_or_update_broadcast(chat_id=3, template_name="p", mode="counter", counter_threshold=10, account_id=7)
        task = self.db.list_all_tasks(account_id=7)[0]
        self.db.schedule_retry(task, 300)
        row = self.db.list_all_tasks(account_id=7)[0]
        self.assertLess(row["current_count"], 10)
        self.assertGreater(row["retry_at"], time.time())
        self.assertEqual(self.db.get_due_retries(account_id=7), [])
        self.assertEqual(len(self.db.get_due_retries(account_id=7, now=time.time() + 301)), 1)

    def test_retry_claim_is_exclusive(self):
        self.db.add_or_update_broadcast(chat_id=3, template_name="p", mode="counter", counter_threshold=10, account_id=7)
        task = self.db.list_all_tasks(account_id=7)[0]
        self.db.schedule_retry(task, 1)
        later = time.time() + 5
        self.assertTrue(self.db.claim_retry(task["id"], later))
        self.assertFalse(self.db.claim_retry(task["id"], later))


class TestRotations(_DBCase):
    def setUp(self):
        super().setUp()
        for n in ("a", "b", "c", "other"):
            self.db.save_template(n, n, [], [])

    def test_chat_rotation_does_not_hijack_other_posts(self):
        self.db.set_chat_rotation(1, ["a", "b"], account_id=7)
        self.assertIsNone(self.db.get_next_rotation_template(chat_id=1, account_id=7, member_of_chat_rotation="other"))
        first = self.db.get_next_rotation_template(chat_id=1, account_id=7, member_of_chat_rotation="a")
        second = self.db.get_next_rotation_template(chat_id=1, account_id=7, member_of_chat_rotation="a")
        self.assertEqual({first, second}, {"a", "b"})

    def test_named_rotation_position_is_per_chat(self):
        self.db.set_named_rotation("r", ["a", "b", "c"], account_id=7)
        c1 = [self.db.get_next_rotation_template(chat_id=1, account_id=7, rotation_name="r") for _ in range(2)]
        c2 = [self.db.get_next_rotation_template(chat_id=2, account_id=7, rotation_name="r") for _ in range(2)]
        self.assertEqual(c1, c2)


class TestStopDeleteScope(_DBCase):
    def test_manual_stop_is_not_resurrected_by_folder_sync(self):
        self.db.add_or_update_broadcast(chat_id=5, template_name="p", mode="interval", interval_seconds=60,
                                        folder_name="F", account_id=7)
        self.db.stop_tasks(account_id=7, name="p", manual=True)
        self.db.ensure_broadcast_task(chat_id=5, template_name="p", mode="interval", interval_seconds=60,
                                      folder_name="F", account_id=7)
        self.assertEqual(self.db.get_active_interval_tasks(account_id=7), [])

    def test_stop_by_name_covers_every_chat(self):
        for chat in (1, 2, 3):
            self.db.add_or_update_broadcast(chat_id=chat, template_name="p", mode="interval", interval_seconds=60, account_id=7)
        self.db.add_or_update_broadcast(chat_id=1, template_name="q", mode="interval", interval_seconds=60, account_id=7)
        self.assertEqual(self.db.stop_tasks(account_id=7, name="p", manual=True), 3)
        active = self.db.get_active_interval_tasks(account_id=7)
        self.assertEqual([t["template_name"] for t in active], ["q"])

    def test_delete_in_one_chat_keeps_folder_tombstone(self):
        self.db.add_or_update_broadcast(chat_id=5, template_name="p", mode="interval", interval_seconds=60,
                                        folder_name="F", account_id=7)
        self.db.delete_tasks(account_id=7, name="p", chat_ids=[5], keep_folder_tombstones=True)
        self.db.ensure_broadcast_task(chat_id=5, template_name="p", mode="interval", interval_seconds=60,
                                      folder_name="F", account_id=7)
        self.assertEqual(self.db.get_active_interval_tasks(account_id=7), [])


class TestSending(unittest.TestCase):
    def test_link_preview_is_not_saved_as_media(self):
        self.assertFalse(bot._is_downloadable_media(_Msg(media=MessageMediaWebPage(webpage=None))))
        self.assertTrue(bot._is_downloadable_media(_Msg(media=MessageMediaPhoto())))

    def test_text_is_sent_without_markdown_parsing(self):
        client = _SendClient()
        asyncio.run(bot.send_single_item(client, 1, "__не курсив__ **и не жирный**", [], []))
        self.assertEqual(client.sent[0][1], "__не курсив__ **и не жирный**")
        self.assertIn("parse_mode", client.kwargs[0])
        self.assertIsNone(client.kwargs[0]["parse_mode"])


class TestInstanceLock(unittest.TestCase):
    def test_second_copy_is_refused(self):
        key = f"test_{os.getpid()}_{time.time_ns()}"
        self.assertTrue(bot.acquire_instance_lock(key))
        try:
            self.assertFalse(bot.acquire_instance_lock(key))
        finally:
            bot.release_instance_lock(key)
        self.assertTrue(bot.acquire_instance_lock(key))
        bot.release_instance_lock(key)


if __name__ == "__main__":
    unittest.main()
