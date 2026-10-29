# -*- coding: utf-8 -*-
"""Пинги: как сообщение вообще «дотянулось» до нас.

`classify_ping` — единственное место, где решается судьба пинга: от ответа
зависит, можно ли гасить сообщение и читать историю. Тесты фиксируют все
способы, которыми владельца реально упоминают, и все ложные срабатывания:

  * reply на наше сообщение без @ и без entity — это пинг ("reply");
  * @handle в подписи к фото/видео — это пинг ("username");
  * reply другому человеку — не пинг;
  * сущность-упоминание с подписью-эмодзи — скрытый тег ("stealth");
  * reply на служебный заголовок форум-топика — не пинг.
"""
import asyncio

from types import SimpleNamespace as NS

from telethon.tl.types import (
    MessageEntityBold,
    MessageEntityMentionName,
    MessageEntityTextUrl,
    MessageMediaPhoto,
)

import bot
from tests.support import MY_ID, group_event

MY_USERNAMES = ["myuser"]
MY_NAMES = ["Иван"]


def classify(event, message, text):
    return asyncio.run(bot.classify_ping(event, message, text, MY_ID, MY_USERNAMES, MY_NAMES))


def message_stub(text="", mentioned=False, entities=None, media=None):
    return NS(id=7001, mentioned=mentioned, entities=entities or [], media=media,
              raw_text=text, message=text)


# --------------------------------------------------------------------------- #
# reply
# --------------------------------------------------------------------------- #
def test_reply_to_our_own_message_is_a_ping_without_mentions():
    """Ответ на наш пост — пинг сам по себе, даже без @ и entity.

    Раньше гейт возвращал None до проверки reply, и реклама ответом на наше
    сообщение не гасилась никогда.
    """
    reply = NS(sender_id=MY_ID, out=False)
    event = group_event(is_reply=True, reply_to=reply, mid=7101)
    msg = message_stub("Прайс на аккаунты")
    assert classify(event, msg, "Прайс на аккаунты") == "reply"


def test_reply_to_our_own_outgoing_message_is_a_ping():
    """Своё сообщение приходит и как out=True (другой наш аккаунт)."""
    reply = NS(sender_id=None, out=True)
    event = group_event(is_reply=True, reply_to=reply, mid=7102)
    msg = message_stub("🔥 прайс")
    assert classify(event, msg, "🔥 прайс") == "reply"


def test_reply_to_another_person_is_not_a_ping():
    """Обычный reply в чате — не повод трогать сообщение."""
    reply = NS(sender_id=111222, out=False)
    event = group_event(is_reply=True, reply_to=reply, mid=7103)
    msg = message_stub("да, согласен")
    assert classify(event, msg, "да, согласен") is None


def test_reply_to_a_forum_topic_header_is_not_a_ping():
    """В форуме ответ на заголовок топика адресован каналу, а не нам."""
    topic_header = NS(sender_id=None, out=False, id=12,
                      action=NS(className="MessageActionTopicCreate"))
    event = group_event(is_reply=True, reply_to=topic_header, mid=7104)
    msg = message_stub("Продам аккаунты, пиши в лс")
    assert classify(event, msg, "Продам аккаунты, пиши в лс") is None


def test_reply_to_our_post_inside_a_forum_topic_is_still_a_ping():
    """Reply на наше сообщение внутри топика — обычный пинг."""
    our_post = NS(sender_id=MY_ID, out=False, id=13)
    event = group_event(is_reply=True, reply_to=our_post, mid=7105)
    msg = message_stub("Смотрите прайс")
    assert classify(event, msg, "Смотрите прайс") == "reply"


# --------------------------------------------------------------------------- #
# упоминания в тексте и в подписи к медиа
# --------------------------------------------------------------------------- #
def test_handle_typed_in_a_media_caption_is_a_username_ping():
    """raw_text медиа — это подпись, @handle в ней считается пингом."""
    caption = "@myuser 🔥 Продам аккаунты, пиши в лс @shop"
    event = group_event(text=caption, mentioned=True, media=MessageMediaPhoto(), mid=7106)
    msg = message_stub(caption, mentioned=True, media=MessageMediaPhoto())
    assert classify(event, msg, caption) == "username"


def test_handle_in_a_caption_without_mention_flag_is_still_a_ping():
    """Флаг `mentioned` может не прийти (например, после правки) — текст решает."""
    caption = "@myuser почём звёзды?"
    event = group_event(text=caption, mentioned=False, media=MessageMediaPhoto(), mid=7107)
    msg = message_stub(caption, mentioned=False, media=MessageMediaPhoto())
    assert classify(event, msg, caption) == "username"


def test_media_with_a_commercial_caption_is_cleared():
    caption = "@myuser 🔥 Продам аккаунты, пиши в лс @shop"
    msg = message_stub(caption, mentioned=True, media=MessageMediaPhoto())
    assert bot.should_auto_read(caption, msg, is_ping=True, ping_kind="username") is True


def test_bare_name_without_an_entity_is_not_a_ping():
    """Имя, набранное текстом, Telegram не считает упоминанием.

    «name» появляется только когда есть entity-упоминание на нас с подписью,
    похожей на наше имя (см. тест ниже). Просто текст «Иван, привет» — не пинг.
    """
    text = "Иван, привет! Продам звёзды дешевле"
    event = group_event(text=text, mid=7108)
    msg = message_stub(text)
    assert classify(event, msg, text) is None


# --------------------------------------------------------------------------- #
# entity-упоминания: видимое имя против скрытого тега
# --------------------------------------------------------------------------- #
def test_hidden_mention_entity_is_stealth():
    """Сущность ведёт на нас, а видно эмодзи — это скрытый тег."""
    text = "🔥🔥 продам аккаунты"
    entities = [MessageEntityMentionName(offset=0, length=2, user_id=MY_ID)]
    event = group_event(text=text, mid=7109)
    msg = message_stub(text, mentioned=True, entities=entities)
    assert classify(event, msg, text) == "stealth"


def test_mention_entity_with_our_name_is_a_name_ping():
    text = "Иван, глянь прайс"
    entities = [MessageEntityMentionName(offset=0, length=4, user_id=MY_ID)]
    event = group_event(text=text, mid=7110)
    msg = message_stub(text, entities=entities)
    assert classify(event, msg, text) == "name"


def test_entity_pointing_at_someone_else_is_not_a_ping():
    text = "Иван, привет"
    entities = [MessageEntityMentionName(offset=0, length=4, user_id=555111)]
    event = group_event(text=text, mid=7111)
    msg = message_stub(text, entities=entities)
    assert classify(event, msg, text) is None


def test_text_url_entity_with_tg_user_link_is_a_hidden_tag():
    """`[ссылка](tg://user?id=НАШ)` — тоже скрытое упоминание."""
    text = "смотри сюда"
    entities = [MessageEntityTextUrl(offset=0, length=5, url=f"tg://user?id={MY_ID}")]
    event = group_event(text=text, mid=7112)
    msg = message_stub(text, mentioned=True, entities=entities)
    assert classify(event, msg, text) == "stealth"


def test_plain_bold_entity_is_ignored():
    text = "жирный текст"
    entities = [MessageEntityBold(offset=0, length=6)]
    event = group_event(text=text, mid=7113)
    msg = message_stub(text, entities=entities)
    assert classify(event, msg, text) is None


# --------------------------------------------------------------------------- #
# гейт авто-чтения: порог для пингов
# --------------------------------------------------------------------------- #
def test_genuine_buyer_question_with_a_ping_is_kept():
    """Настоящий вопрос покупателя не гасим, даже если это пинг."""
    text = "@myuser а сколько стоит реклама в канале?"
    msg = message_stub(text, mentioned=True)
    assert bot.should_auto_read(text, msg, is_ping=True, ping_kind="username") is False


def test_commercial_ping_is_cleared():
    text = "@myuser продаю аккаунты, пишите в лс @shop"
    msg = message_stub(text)
    assert bot.should_auto_read(text, msg, is_ping=True, ping_kind="username") is True


def test_ad_without_ping_is_left_alone_when_it_is_a_normal_reply():
    """Без пинга обычная переписка не вычищается, даже если есть реклама рядом."""
    text = "спасибо, всё получил"
    msg = message_stub(text)
    assert bot.should_auto_read(text, msg, is_ping=False, ping_kind=None) is False


def test_hidden_ping_with_price_list_is_cleared():
    text = "🔥 Прайс\n🇮🇳 Индия (+91) - 30\n🇹🇷 Турция (+90) - 50\nКупить: @shop"
    msg = message_stub(text, mentioned=True, media=MessageMediaPhoto())
    assert bot.should_auto_read(text, msg, is_ping=True, ping_kind="stealth") is True
