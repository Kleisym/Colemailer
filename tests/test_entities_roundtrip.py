# -*- coding: utf-8 -*-
"""Сущности форматирования: serialize -> база -> deserialize.

Telegram добавляет новые типы сущностей (blockquote, кастомные эмодзи, даты),
и старая версия Telethon не знает их классы. Пост должен пережить круг
«сохранили в шаблон — отправили» без потери остального форматирования.
"""
from telethon.tl.types import (
    MessageEntityBold,
    MessageEntityBlockquote,
    MessageEntityCustomEmoji,
    MessageEntityFormattedDate,
    MessageEntityItalic,
    MessageEntityPre,
    MessageEntitySpoiler,
    MessageEntityTextUrl,
    MessageEntityUnderline,
)

import bot

TEXT = "Заголовок цитаты жирный курсив код ссылка 😀 дата"


def entity_types(entities):
    return [type(e).__name__ for e in entities]


# --------------------------------------------------------------------------- #
# полный круг
# --------------------------------------------------------------------------- #
def test_blockquote_and_custom_emoji_survive_the_round_trip():
    entities = [
        MessageEntityBlockquote(offset=0, length=16),
        MessageEntityCustomEmoji(offset=45, length=2, document_id=5368324170671202286),
    ]

    restored = bot.deserialize_entities(bot.serialize_entities(entities))

    assert entity_types(restored) == ["MessageEntityBlockquote", "MessageEntityCustomEmoji"]
    assert [(e.offset, e.length) for e in restored] == [(0, 16), (45, 2)]
    assert restored[1].document_id == 5368324170671202286


def test_bold_and_text_url_survive_the_round_trip():
    entities = [
        MessageEntityBold(offset=0, length=8),
        MessageEntityTextUrl(offset=9, length=6, url="https://t.me/cole"),
    ]

    restored = bot.deserialize_entities(bot.serialize_entities(entities))

    assert entity_types(restored) == ["MessageEntityBold", "MessageEntityTextUrl"]
    assert restored[1].url == "https://t.me/cole"


def test_mixed_entity_set_keeps_order_and_payload():
    entities = [
        MessageEntityBold(offset=0, length=4),
        MessageEntitySpoiler(offset=5, length=3),
        MessageEntityUnderline(offset=9, length=2),
        MessageEntityPre(offset=12, length=6, language="python"),
        MessageEntityTextUrl(offset=19, length=8, url="https://t.me/x"),
        MessageEntityCustomEmoji(offset=28, length=2, document_id=55555),
    ]

    restored = bot.deserialize_entities(bot.serialize_entities(entities))

    assert entity_types(restored) == entity_types(entities)
    pre = [e for e in restored if isinstance(e, MessageEntityPre)][0]
    assert pre.language == "python"
    emoji = [e for e in restored if isinstance(e, MessageEntityCustomEmoji)][0]
    assert emoji.document_id == 55555


def test_entities_survive_the_template_table(tmp_db):
    entities = [
        MessageEntityBlockquote(offset=0, length=16),
        MessageEntityCustomEmoji(offset=45, length=2, document_id=55555),
    ]
    tmp_db.save_template("ent", TEXT, bot.serialize_entities(entities), [])

    tpl = tmp_db.get_template("ent")
    restored = bot.deserialize_entities(tpl["entities_hex"])

    assert entity_types(restored) == entity_types(entities)
    assert tpl["text"] == TEXT


def test_deserialize_skips_a_broken_entity_and_keeps_the_rest():
    """Одна испорченная запись не должна ломать всё форматирование поста."""
    good = bot.serialize_entities([MessageEntityBold(offset=0, length=4)])
    restored = bot.deserialize_entities(["zzzz", *good])

    assert entity_types(restored) == ["MessageEntityBold"]


def test_deserialize_of_empty_input_is_empty():
    assert bot.deserialize_entities([]) == []
    assert bot.deserialize_entities(None) == []
    assert bot.serialize_entities([]) == []


# --------------------------------------------------------------------------- #
# пересчёт смещений (префикс команды + обрезка по границам текста)
# --------------------------------------------------------------------------- #
def rebased(entities, prefix_len, text_len):
    return bot.deserialize_entities(bot._rebase_entities(entities, prefix_len, text_len))


def test_partially_out_of_range_entity_is_clamped_and_others_survive():
    text_len = 15
    entities = [
        MessageEntityBold(offset=0, length=5),
        MessageEntityTextUrl(offset=6, length=10, url="https://t.me/x"),
    ]

    restored = rebased(entities, 0, text_len)

    assert entity_types(restored) == ["MessageEntityBold", "MessageEntityTextUrl"]
    assert (restored[0].offset, restored[0].length) == (0, 5)
    assert (restored[1].offset, restored[1].length) == (6, 9), "хвост за текстом обрезается"
    assert restored[1].url == "https://t.me/x"


def test_entity_fully_outside_the_text_is_dropped():
    restored = rebased([MessageEntityItalic(offset=20, length=3)], 0, 15)
    assert restored == []


def test_entity_before_the_prefix_is_dropped():
    restored = rebased([MessageEntityBold(offset=0, length=5)], prefix_len=5, text_len=15)
    assert restored == []


def test_entity_partially_covering_the_prefix_keeps_its_visible_tail():
    restored = rebased([MessageEntityBold(offset=3, length=6)], prefix_len=5, text_len=15)
    assert len(restored) == 1
    assert (restored[0].offset, restored[0].length) == (0, 4)


def test_rebase_keeps_blockquote_across_the_prefix_cut():
    restored = rebased([MessageEntityBlockquote(offset=2, length=10)], prefix_len=0, text_len=8)
    assert entity_types(restored) == ["MessageEntityBlockquote"]
    assert (restored[0].offset, restored[0].length) == (2, 6)
