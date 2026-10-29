# -*- coding: utf-8 -*-
"""Регрессии по дефектам, которые нашёл владелец (перенос из QA-предложений).

Исходный файл лежал вне репозитория (`qa/newtests/test_owner_bugs.py`) и был
написан как «красные» тесты: они фиксировали симптомы и должны были упасть на
старом коде. Сейчас код исправлен, поэтому здесь те же сценарии, но с
ожиданиями нового поведения. Что изменилось по сравнению с предложением:

  * папка, которая пропала, паркует свои чаты после 10 промахов (было 3):
    один-два неудачных чтения папки — это сетевой сбой, а не удаление;
  * «кнопки из сообщения» приходят в шаблон в форме `{text, type, value}`
    (её даёт `cole.buttons.extract_buttons`), форма `{text, url}` в шаблоны
    не попадает и намеренно отбрасывается — тест это фиксирует;
  * гибридный счётчик проверяется через `counter_ready_at`/`send_pending`,
    поэтому один и тот же тест проверяет и свежесть окна, и отсутствие дубля.

Проверяется поведение, а не внутренности: берутся публичные функции `bot`,
фейковый клиент Telethon и временная база.
"""
import asyncio
import time

from telethon.tl.types import (
    MessageEntityBlockquote,
    MessageEntityBold,
    MessageEntityCustomEmoji,
    MessageEntityFormattedDate,
    MessageEntityPre,
    MessageEntitySpoiler,
    MessageEntityTextUrl,
    MessageEntityUnderline,
    MessageMediaPhoto,
)
from unittest.mock import AsyncMock, patch

import bot
from tests.support import MY_ID, RecordingClient, group_event, make_handlers

AD_CAPTION = "🔥 Прайс\n🇮🇳 Индия (+91) - 30\n🇹🇷 Турция (+90) - 50\nКупить: @shop"


# --------------------------------------------------------------------------- #
# (a) пинг без reply и пинг в подписи к медиа
# --------------------------------------------------------------------------- #
def test_a_non_reply_hidden_ping_is_stealth_and_cleared():
    """Упоминание без reply и без видимого @ — скрытый тег, его гасим."""
    msg = dict(mentioned=True, entities=[], media=None)
    from types import SimpleNamespace as NS

    kind = asyncio.run(bot.classify_ping(group_event(), NS(**msg), "Прайс на аккаунты",
                                         MY_ID, ["myuser"], ["Иван"]))
    assert kind == "stealth"
    assert bot.should_auto_read("Прайс на аккаунты", NS(**msg), is_ping=True,
                               ping_kind=kind) is True


def test_a_reply_to_a_third_party_is_not_our_ping():
    """Ответ другому человеку — не пинг: ни reply-зачёта, ни поблажки покупателю."""
    from types import SimpleNamespace as NS

    reply = NS(sender_id=111222, out=False)
    ev = group_event(is_reply=True, reply_to=reply, mentioned=True)
    msg = NS(mentioned=True, entities=[], media=None)
    kind = asyncio.run(bot.classify_ping(ev, msg, "🔥 прайс", MY_ID, ["myuser"], ["Иван"]))
    assert kind == "stealth"


def test_a_ping_typed_in_a_media_caption_counts_as_username():
    """raw_text медиа — это подпись; @handle в ней и есть пинг."""
    from types import SimpleNamespace as NS

    caption = "@myuser 🔥 Продам аккаунты, пиши в лс @shop"
    msg = NS(mentioned=True, entities=[], media=MessageMediaPhoto(), media_type=None)
    ev = group_event(text=caption, mentioned=True, media=MessageMediaPhoto())
    kind = asyncio.run(bot.classify_ping(ev, msg, caption, MY_ID, ["myuser"], ["Иван"]))
    assert kind == "username"
    assert bot.should_auto_read(caption, msg, is_ping=True, ping_kind=kind) is True


def test_a_ad_in_caption_without_typed_handle_is_cleared():
    """Подпись-каталог продавца — спам даже без @handle."""
    from types import SimpleNamespace as NS

    msg = NS(mentioned=True, entities=[], media=MessageMediaPhoto(), media_type=None)
    assert bot.should_auto_read(AD_CAPTION, msg, is_ping=True, ping_kind="stealth") is True


def test_a_media_caption_ping_reaches_clear_with_correct_flag(tmp_db):
    """Обработчик обязан отдать медиа-пинг в clear_spam_mention с protect=False."""
    client = RecordingClient()
    handlers = make_handlers(client)
    ev = group_event(text=AD_CAPTION, mentioned=True, media=MessageMediaPhoto(), mid=7010)
    with patch.object(bot, "clear_spam_mention", new_callable=AsyncMock) as clear_mock:
        asyncio.run(handlers["incoming_handler"](ev))
    assert clear_mock.await_count == 1
    assert clear_mock.call_args.kwargs["protect_unread_history"] is False


# --------------------------------------------------------------------------- #
# (b) мьют не пускает пинг дальше: ни clear, ни счётчик
# --------------------------------------------------------------------------- #
def test_b_muted_sender_never_reaches_clear(tmp_db):
    tmp_db.add_muted_peer(peer_id=456789, peer_key=456789, username="spammer", account_id=MY_ID)
    bot.mute_cache_rebuild(MY_ID)
    assert bot.is_peer_muted(MY_ID, 456789) is True

    sent = []
    client = RecordingClient()
    handlers = make_handlers(client)
    client_broadcaster_calls = len(sent)
    ev = group_event(text=AD_CAPTION, mentioned=True, mid=7020)
    with patch.object(bot, "clear_spam_mention", new_callable=AsyncMock) as clear_mock:
        asyncio.run(handlers["incoming_handler"](ev))
    assert clear_mock.await_count == 0
    assert client_broadcaster_calls == 0
    # Сообщение просто помечается прочитанным — и всё.
    assert client.sent_messages == []
    assert client.deleted == []
    assert client.permissions == []


def test_b_mute_blocks_the_edited_message_path_too(tmp_db):
    tmp_db.add_muted_peer(peer_id=456789, peer_key=456789, account_id=MY_ID)
    bot.mute_cache_rebuild(MY_ID)
    client = RecordingClient()
    handlers = make_handlers(client)
    with patch.object(bot, "clear_spam_mention", new_callable=AsyncMock) as clear_mock:
        asyncio.run(handlers["edited_spam_handler"](group_event(text=AD_CAPTION, mid=7021)))
    assert clear_mock.await_count == 0


def test_b_mute_survives_a_restart_cache_rebuild(tmp_db):
    """Мьюты лежат в базе: после холодного старта кэш собирается заново."""
    tmp_db.add_muted_peer(peer_id=777, peer_key=777, account_id=42)
    bot.mute_cache_rebuild(42)
    assert bot.is_peer_muted(42, 777) is True


# --------------------------------------------------------------------------- #
# (c) hybrid: 15 сообщений И пауза, без догоняющей отправки
# --------------------------------------------------------------------------- #
def test_c_legacy_leftover_count_does_not_fire_after_restart(tmp_db):
    """hybrid после рестарта: остаток счётчика не добивает порог одним сообщением.

    Счётчик, не добравший порог, живёт в базе (окно помечается только через
    counter_ready_at), поэтому «14 вчерашних + 1 новое» само по себе порог
    добивает. После рестарта процесса `reset_pending_sends` обнуляет остаток —
    именно это и проверяем: новый пост не уходит с одного сообщения.
    """
    from tests.support import hybrid_task_row

    hybrid_task_row(tmp_db, count=14, last_sent_ago=24 * 3600, ready_ago=None)
    tmp_db.reset_pending_sends(account_id=1)
    assert tmp_db.increment_and_check_counter(555, account_id=1) == []
    row = tmp_db.get_active_interval_tasks(account_id=1)[0]
    assert row["current_count"] <= 1


def test_c_stale_window_does_not_fire_on_the_next_message(tmp_db):
    """Окно, открытое 4 часа назад, мертво: счёт начинается с нуля."""
    from tests.support import hybrid_task_row

    hybrid_task_row(tmp_db, count=15, last_sent_ago=4 * 3600, ready_ago=4 * 3600)
    assert tmp_db.increment_and_check_counter(555, account_id=1) == []


def test_c_both_conditions_met_fires_exactly_once(tmp_db):
    from tests.support import hybrid_task_row

    task = hybrid_task_row(tmp_db, count=15, last_sent_ago=1000, ready_ago=60)
    ready = tmp_db.increment_and_check_counter(555, account_id=1)
    assert len(ready) == 1
    assert ready[0]["template_name"] == "h"
    assert tmp_db.claim_hybrid_task(task["id"], time.time(),
                                    stale_after=2700) is True
    # Второй claim того же поста не проходит: send_pending уже стоит.
    assert tmp_db.claim_hybrid_task(task["id"], time.time(), stale_after=2700) is False
    assert tmp_db.increment_and_check_counter(555, account_id=1) == []


# --------------------------------------------------------------------------- #
# (d) disable_preview должен доезжать до Telethon как link_preview=False
# --------------------------------------------------------------------------- #
class _SendClient:
    def __init__(self):
        self.calls = []

    async def get_input_entity(self, peer):
        return peer

    async def send_message(self, peer, message=None, formatting_entities=None, **kw):
        self.calls.append(("send_message", kw, message))
        return type("Msg", (), {"id": 1})()

    async def send_file(self, peer, file=None, caption=None, formatting_entities=None, **kw):
        self.calls.append(("send_file", kw, caption))
        return type("Msg", (), {"id": 2})()


def test_d_disable_preview_reaches_send_message():
    client = _SendClient()
    asyncio.run(bot.send_single_item(client, 1, "смотри https://example.com", [], [],
                                     disable_preview=True))
    assert client.calls, "ничего не отправлено"
    assert client.calls[0][1].get("link_preview") is False


def test_d_preview_stays_on_by_default():
    client = _SendClient()
    asyncio.run(bot.send_single_item(client, 1, "смотри https://example.com", [], []))
    assert client.calls[0][1].get("link_preview", True) is not False


def test_d_template_flag_is_forwarded_by_the_scheduler(tmp_db):
    client = _SendClient()
    tmp_db.save_template("p", "смотри https://example.com", [], [], disable_preview=1)
    service = bot.BroadcasterService(client, account_id=1)
    tmp_db.add_or_update_broadcast(chat_id=9, template_name="p", mode="interval",
                                   interval_seconds=60, account_id=1)
    task = tmp_db.get_active_interval_tasks(account_id=1)[0]
    asyncio.run(service._send_task(task["id"], 9, "p", task=task))
    assert client.calls[0][1].get("link_preview") is False


# --------------------------------------------------------------------------- #
# (e) чаты, добавленные в папку после старта рассылки
# --------------------------------------------------------------------------- #
class _FolderClient:
    def __init__(self, folders):
        self.folders = folders

    async def __call__(self, request):
        from telethon.tl.functions.messages import GetDialogFiltersRequest
        from telethon.tl.types import InputPeerUser, TextWithEntities

        if isinstance(request, GetDialogFiltersRequest):
            return type("Res", (), {"filters": [
                type("F", (), dict(
                    id=i + 1, title=TextWithEntities(text=title, entities=[]),
                    pinned_peers=[], exclude_peers=[], contacts=False, non_contacts=False,
                    bots=False, groups=False, broadcasts=False,
                    include_peers=[InputPeerUser(chat, 0) for chat in chats],
                ))
                for i, (title, chats) in enumerate(self.folders.items())
            ]})()
        return None


def test_e_new_chat_in_folder_is_enrolled_on_next_sync(tmp_db):
    tmp_db.save_template("promo", "hi", [], [])
    tmp_db.register_folder_broadcast(folder_name="Папка", template_name="promo",
                                     mode="interval", interval_seconds=30, account_id=5)
    client = _FolderClient({"Папка": [10, 20]})
    service = bot.BroadcasterService(client, account_id=5)
    assert asyncio.run(service.sync_folder_broadcasts()) == 2

    client.folders["Папка"].append(30)
    assert asyncio.run(service.sync_folder_broadcasts()) == 1
    active = {t["chat_id"] for t in tmp_db.get_active_interval_tasks(account_id=5)}
    assert active == {10, 20, 30}


def test_e_missing_folder_parks_its_chats_after_ten_misses(tmp_db):
    """Папка исчезла: 9 промахов — ждём, 10-й — снимаем чаты с рассылки."""
    tmp_db.save_template("promo", "hi", [], [])
    tmp_db.register_folder_broadcast(folder_name="Папка", template_name="promo",
                                     mode="interval", interval_seconds=30, account_id=5)
    client = _FolderClient({"Папка": [10]})
    service = bot.BroadcasterService(client, account_id=5)
    assert asyncio.run(service.sync_folder_broadcasts()) == 1

    client.folders.clear()  # папку переименовали / удалили
    for _ in range(9):
        asyncio.run(service.sync_folder_broadcasts())
    assert {t["chat_id"] for t in tmp_db.get_active_interval_tasks(account_id=5)} == {10}

    asyncio.run(service.sync_folder_broadcasts())
    assert {t["chat_id"] for t in tmp_db.get_active_interval_tasks(account_id=5)} == set()


# --------------------------------------------------------------------------- #
# (f) инлайн-кнопки: раскладка и типы
# --------------------------------------------------------------------------- #
LAYOUT = [
    [{"text": "Купить", "type": "url", "value": "https://t.me/shop"},
     {"text": "Отзывы", "type": "url", "value": "https://t.me/rev"}],
    [{"text": "Написать", "type": "url", "value": "https://t.me/manager"}],
]
LAYOUT_BOT_SHAPE = [[{"text": "Купить", "url": "https://t.me/shop"}],
                    [{"text": "Отзывы", "url": "https://t.me/rev"}]]


def test_f_markup_keeps_rows_and_order():
    markup = bot.build_buttons_markup(LAYOUT)
    assert markup is not None, "cole.buttons не собрал разметку"
    rows = list(getattr(markup, "rows", []))
    assert len(rows) == 2
    assert len(rows[0].buttons) == 2
    assert len(rows[1].buttons) == 1
    assert [b.text for b in rows[0].buttons] == ["Купить", "Отзывы"]


def test_f_captured_message_buttons_use_the_template_shape():
    """Кнопки, снятые с сообщения, приходят из extract_buttons уже в форме
    `{text, type, value}` и рендерятся. Плоская форма `{text, url}` тоже
    принимается: так выглядят кнопки, снятые с чужого сообщения."""
    text, rows = bot.extract_buttons_block("Пост про канал\n[Купить](https://t.me/shop)")
    assert rows and "https://t.me/shop" not in text
    assert rows[0][0]["value"] == "https://t.me/shop"
    assert bot.build_buttons_markup(rows) is not None
    # Плоская форма приводится к шаблонной и не ломает отправку.
    assert bot.build_buttons_markup(LAYOUT_BOT_SHAPE) is not None


def test_f_buttons_reach_send_message():
    client = _SendClient()
    asyncio.run(bot.send_single_item(client, 1, "пост", [], [], buttons=LAYOUT))
    kw = client.calls[0][1]
    assert "buttons" in kw and kw["buttons"] is not None


def test_f_buttons_survive_template_round_trip(tmp_db):
    from cole.buttons import to_json

    tmp_db.save_template("btn", "пост", [], [], buttons_json=to_json(LAYOUT))
    tpl = tmp_db.get_template("btn")
    assert tpl["buttons"] == LAYOUT


def test_f_buttons_are_parsed_out_of_a_collected_post():
    """Хвост `[Купить](https://t.me/shop)` становится кнопкой, а не текстом."""
    text, rows = bot.extract_buttons_block("Пост про канал\n[Купить](https://t.me/shop)")
    assert rows, "блок кнопок не выделен"
    assert "https://t.me/shop" not in text


# --------------------------------------------------------------------------- #
# (g) новые типы сущностей переживают round-trip через базу
# --------------------------------------------------------------------------- #
NEW_ENTITIES = [
    MessageEntityBold(offset=0, length=4),
    MessageEntitySpoiler(offset=5, length=3),
    MessageEntityUnderline(offset=9, length=2),
    MessageEntityPre(offset=12, length=6, language="python"),
    MessageEntityTextUrl(offset=19, length=8, url="https://t.me/x"),
    MessageEntityCustomEmoji(offset=28, length=2, document_id=55555),
]


def test_g_entities_survive_serialise_deserialise():
    restored = bot.deserialize_entities(bot.serialize_entities(NEW_ENTITIES))
    assert [type(e).__name__ for e in restored] == [type(e).__name__ for e in NEW_ENTITIES]
    for original, got in zip(NEW_ENTITIES, restored):
        assert (got.offset, got.length) == (original.offset, original.length)


def test_g_entities_survive_the_template_table(tmp_db):
    hex_list = bot.serialize_entities(NEW_ENTITIES)
    tmp_db.save_template("ent", "bold spoil under pre link emoji", hex_list, [])
    tpl = tmp_db.get_template("ent")
    restored = bot.deserialize_entities(tpl["entities_hex"])
    assert len(restored) == len(NEW_ENTITIES)
    pre = [e for e in restored if type(e).__name__ == "MessageEntityPre"][0]
    assert getattr(pre, "language", "") == "python"
    url = [e for e in restored if type(e).__name__ == "MessageEntityTextUrl"][0]
    assert url.url == "https://t.me/x"
    emoji = [e for e in restored if type(e).__name__ == "MessageEntityCustomEmoji"][0]
    assert emoji.document_id == 55555


def test_g_blockquote_and_date_entities_are_not_dropped():
    entities = [MessageEntityBlockquote(offset=0, length=5),
                MessageEntityFormattedDate(offset=6, length=4, date=1700000000)]
    restored = bot.deserialize_entities(bot.serialize_entities(entities))
    assert len(restored) == 2
