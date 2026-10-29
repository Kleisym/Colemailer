# -*- coding: utf-8 -*-
"""Превью ссылок и инлайн-кнопки в рассылке.

Владелец жаловался на два симптома: «превью выключил, а карточка ссылки всё
равно приезжает» и «кнопки не появились / схлопнулись в один ряд». Оба живут
на стыке шаблон -> отправка, поэтому тесты идут от шаблона до аргументов,
которые получает Telethon.
"""
import asyncio

import pytest
from telethon.tl.types import (
    InlineButtonTypeCallback,
    InlineButtonTypeUrl,
    ReplyInlineMarkup,
)

import bot
from cole.buttons import ButtonError, build_markup, parse_row, to_json
from tests.support import RecordingClient, command_event, make_handlers

LAYOUT_211 = [
    [{"text": "Купить", "type": "url", "value": "https://t.me/shop"},
     {"text": "Прайс", "type": "callback", "value": "price"}],
    [{"text": "Отзывы", "type": "url", "value": "https://t.me/rev"}],
    [{"text": "Помощь", "type": "callback", "value": "help"}],
]


def markup_rows(markup):
    return list(markup.rows)


# --------------------------------------------------------------------------- #
# `.превью выкл/вкл`
# --------------------------------------------------------------------------- #
def test_preview_command_turns_the_card_off(tmp_db):
    tmp_db.save_template("promo", "смотри https://example.com", [], [])
    handlers = make_handlers(RecordingClient())
    event = command_event(".превью выкл promo")

    asyncio.run(handlers["command_dispatcher"](event))

    assert tmp_db.get_template("promo")["disable_preview"] == 1
    assert "выключено" in "\n".join(event.replies).lower()


def test_preview_command_turns_the_card_back_on(tmp_db):
    tmp_db.save_template("promo", "смотри https://example.com", [], [], disable_preview=1)
    handlers = make_handlers(RecordingClient())
    event = command_event(".превью вкл promo")

    asyncio.run(handlers["command_dispatcher"](event))

    assert tmp_db.get_template("promo")["disable_preview"] == 0


def test_preview_command_keeps_buttons_and_text(tmp_db):
    """Смена флага не должна терять кнопки и текст поста (INSERT OR REPLACE)."""
    tmp_db.save_template("promo", "смотри https://example.com", ["0102"], [],
                         buttons_json=to_json(LAYOUT_211))
    handlers = make_handlers(RecordingClient())

    asyncio.run(handlers["command_dispatcher"](command_event(".превью выкл promo")))

    tpl = tmp_db.get_template("promo")
    assert tpl["disable_preview"] == 1
    assert tpl["buttons"] == LAYOUT_211
    assert tpl["text"] == "смотри https://example.com"
    assert tpl["entities_hex"] == ["0102"]


def test_preview_command_rejects_unknown_word(tmp_db):
    tmp_db.save_template("promo", "текст", [], [])
    handlers = make_handlers(RecordingClient())
    event = command_event(".превью назад promo")

    asyncio.run(handlers["command_dispatcher"](event))

    assert tmp_db.get_template("promo")["disable_preview"] == 0
    assert "вкл" in "\n".join(event.replies).lower()


# --------------------------------------------------------------------------- #
# link_preview доходит до Telethon
# --------------------------------------------------------------------------- #
def test_send_single_item_passes_link_preview_false_and_markup():
    client = RecordingClient()
    asyncio.run(bot.send_single_item(client, 1, "смотри https://example.com", [], [],
                                     buttons=LAYOUT_211, disable_preview=True))

    sent = client.sent_messages[0]
    assert sent["kwargs"]["link_preview"] is False
    assert isinstance(sent["kwargs"]["buttons"], ReplyInlineMarkup)


def test_send_single_item_keeps_preview_enabled_by_default():
    client = RecordingClient()
    asyncio.run(bot.send_single_item(client, 1, "смотри https://example.com", [], []))
    assert client.sent_messages[0]["kwargs"]["link_preview"] is True


def test_buttons_reach_send_file_for_a_media_post(tmp_path):
    media = tmp_path / "pic.jpg"
    media.write_bytes(b"\xff\xd8\xff\xd9")
    client = RecordingClient()

    asyncio.run(bot.send_single_item(client, 1, "подпись", [], [str(media)],
                                     buttons=LAYOUT_211))

    sent = client.sent_messages[0]
    assert sent.get("kind") == "file"
    assert sent["caption"] == "подпись"
    assert isinstance(sent["kwargs"]["buttons"], ReplyInlineMarkup)


def test_send_broadcast_post_forwards_preview_and_buttons_to_the_first_item():
    client = RecordingClient()
    bundle = [{"text": "первый"}, {"text": "второй"}]

    asyncio.run(bot.send_broadcast_post(client, 1, bundle=bundle,
                                        buttons=LAYOUT_211, disable_preview=True))

    assert len(client.sent_messages) == 2
    first, second = client.sent_messages
    assert isinstance(first["kwargs"]["buttons"], ReplyInlineMarkup)
    assert second["kwargs"]["buttons"] is None, "кнопки вешаются только на первый пост"
    assert first["kwargs"]["link_preview"] is False
    assert second["kwargs"]["link_preview"] is False


def test_scheduler_sends_template_with_disabled_preview_and_buttons(tmp_db):
    tmp_db.save_template("promo", "смотри https://example.com", [], [],
                         buttons_json=to_json(LAYOUT_211), disable_preview=1)
    tmp_db.add_or_update_broadcast(chat_id=9, template_name="promo", mode="interval",
                                   interval_seconds=60, account_id=1)
    task = tmp_db.get_active_interval_tasks(account_id=1)[0]
    client = RecordingClient()
    service = bot.BroadcasterService(client, account_id=1)

    asyncio.run(service._send_task(task["id"], 9, "promo", task=task))

    sent = client.sent_messages[0]
    assert sent["kwargs"]["link_preview"] is False
    assert isinstance(sent["kwargs"]["buttons"], ReplyInlineMarkup)


# --------------------------------------------------------------------------- #
# раскладка и типы кнопок
# --------------------------------------------------------------------------- #
def test_build_markup_keeps_the_2_1_1_layout():
    markup = build_markup(LAYOUT_211)
    rows = markup_rows(markup)
    assert [len(r.buttons) for r in rows] == [2, 1, 1]
    assert [[b.text for b in r.buttons] for r in rows] == [
        ["Купить", "Прайс"], ["Отзывы"], ["Помощь"],
    ]


def test_build_markup_keeps_url_and_callback_types():
    rows = markup_rows(build_markup(LAYOUT_211))
    url_button = rows[0].buttons[0]
    callback_button = rows[0].buttons[1]

    assert isinstance(url_button.type, InlineButtonTypeUrl)
    assert url_button.type.url == "https://t.me/shop"
    assert isinstance(callback_button.type, InlineButtonTypeCallback)
    assert callback_button.type.data == b"price"


def test_build_markup_returns_none_for_empty_rows():
    assert build_markup([]) is None
    assert build_markup(None) is None


def test_parse_row_accepts_eight_buttons_in_a_row():
    line = " || ".join(f"[B{i}](https://t.me/b{i})" for i in range(8))
    row = parse_row(line)
    assert len(row) == 8


def test_parse_row_rejects_nine_buttons_in_a_row():
    line = " || ".join(f"[B{i}](https://t.me/b{i})" for i in range(9))
    with pytest.raises(ButtonError):
        parse_row(line)


def test_parse_row_rejects_a_callback_longer_than_64_bytes():
    with pytest.raises(ButtonError):
        parse_row(f"[Кнопка](cb:{'a' * 65})")


def test_parse_row_accepts_a_callback_of_exactly_64_bytes():
    row = parse_row(f"[Кнопка](cb:{'a' * 64})")
    assert row[0]["type"] == "callback"
    assert len(row[0]["value"].encode("utf-8")) == 64


def test_parse_row_measures_callback_length_in_bytes_not_characters():
    """33 кириллических символа — это 66 байт, хотя символов меньше 64."""
    with pytest.raises(ButtonError):
        parse_row("[Кнопка](cb:" + "я" * 33 + ")")


def test_markup_truncates_a_row_wider_than_the_limit_to_eight():
    """Слишком широкий ряд не ломает отправку — лишние кнопки отбрасываются."""
    wide = [[{"text": f"B{i}", "type": "url", "value": f"https://t.me/b{i}"} for i in range(9)]]
    rows = markup_rows(build_markup(wide))
    assert len(rows[0].buttons) == 8
