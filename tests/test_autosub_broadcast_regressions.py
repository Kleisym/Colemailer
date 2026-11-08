# -*- coding: utf-8 -*-
"""Регрессии авто-подписки, папок и дублей задач рассылки."""

import asyncio
import sqlite3
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import GetDialogFiltersRequest, UpdateDialogFilterRequest
from telethon.tl.functions.account import UpdateNotifySettingsRequest
from telethon.tl.types import InputPeerChannel, TextWithEntities

import bot
from tests.support import RecordingClient, group_event


class FolderClient(RecordingClient):
    def __init__(self, filters):
        super().__init__()
        self.filters = filters

    async def __call__(self, request):
        self.requests.append(request)
        if isinstance(request, GetDialogFiltersRequest):
            return NS(filters=self.filters)
        return None


def _folder(title="автосабнутое", peer_list=None, excluded=None):
    return NS(
        id=7,
        title=TextWithEntities(text=title, entities=[]),
        pinned_peers=[],
        include_peers=list(peer_list or []),
        exclude_peers=list(excluded or []),
        groups=False,
        broadcasts=False,
        contacts=False,
        non_contacts=False,
        bots=False,
        exclude_muted=False,
        exclude_archived=False,
    )


def _gate_event(text, *, mid=91001, button_url="https://t.me/required_channel"):
    ev = group_event(text=text, mid=mid, mentioned=False)
    ev.message.reply_markup = NS(rows=[NS(buttons=[
        NS(text="Подписаться 1", url=button_url),
        NS(text="Проверить", url=None),
    ])])
    ev.message.click = AsyncMock()
    return ev


def test_gatekeeper_without_personal_ping_joins_mutes_moves_and_checks(tmp_db):
    """Капча-бот не обязан адресовать аккаунт entity-упоминанием."""
    client = FolderClient([_folder()])
    handlers = bot.register_events(
        client,
        NS(on_incoming_message=lambda _chat: None),
        987654321,
        acc_cfg={"auto_sub_enabled": True, "auto_read_spam_pings": True,
                 "auto_sub_folder": "автосабнутое"},
    )
    event = _gate_event(
        "Kleisym, чтобы писать в чат, необходимо подписаться на канал: @required_channel"
    )

    asyncio.run(client.handlers["incoming_handler"](event))

    assert any(isinstance(req, JoinChannelRequest) for req in client.requests)
    assert any(isinstance(req, UpdateNotifySettingsRequest) for req in client.requests)
    assert any(isinstance(req, UpdateDialogFilterRequest) for req in client.requests)
    assert event.message.click.await_args_list == [((0, 0), {}), ((0, 1), {})]


def test_button_only_gatekeeper_is_processed_without_text_or_ping(tmp_db):
    """Новая разметка Telegram может оставить только кнопку подписки."""
    client = FolderClient([_folder()])
    bot.register_events(
        client,
        NS(on_incoming_message=lambda _chat: None),
        987654321,
        acc_cfg={"auto_sub_enabled": True, "auto_read_spam_pings": True,
                 "auto_sub_folder": "автосабнутое"},
    )
    event = _gate_event("", mid=91002)

    asyncio.run(client.handlers["incoming_handler"](event))

    assert any(isinstance(req, JoinChannelRequest) for req in client.requests)
    assert any(isinstance(req, UpdateDialogFilterRequest) for req in client.requests)


def test_callback_only_subscription_button_is_clicked_when_target_is_hidden(tmp_db):
    client = FolderClient([_folder()])
    bot.register_events(
        client,
        NS(on_incoming_message=lambda _chat: None),
        987654321,
        acc_cfg={"auto_sub_enabled": True, "auto_read_spam_pings": True,
                 "auto_sub_folder": "автосабнутое"},
    )
    event = _gate_event("", mid=91003, button_url="")

    asyncio.run(client.handlers["incoming_handler"](event))

    assert event.message.click.await_args_list[0] == ((0, 0), {})


def test_add_peer_to_existing_folder_uses_duck_typed_filter_and_removes_exclude(tmp_path):
    """DialogFilterChatlist/новые TL-типы не должны создавать дубликат папки."""
    existing = _folder(excluded=[InputPeerChannel(1234, 55)])
    client = FolderClient([existing])

    ok = asyncio.run(bot.add_peer_to_folder(
        client, "автосабнутое", InputPeerChannel(1234, 55)
    ))

    assert ok is True
    updates = [req for req in client.requests if isinstance(req, UpdateDialogFilterRequest)]
    assert len(updates) == 1
    assert updates[0].id == existing.id
    assert len(existing.include_peers) == 1
    assert existing.exclude_peers == []


def test_database_repairs_duplicate_broadcast_rows(tmp_path):
    """Старые базы без уникального индекса не могут отправить один пост дважды."""
    path = tmp_path / "legacy.db"
    db = bot.Database(path)
    db.save_template("promo", "text", [], [])

    with sqlite3.connect(path) as conn:
        conn.execute("DROP TABLE broadcast_tasks")
        conn.execute(
            """CREATE TABLE broadcast_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account_id INTEGER DEFAULT 0,
                chat_id INTEGER,
                template_name TEXT,
                mode TEXT,
                interval_seconds INTEGER DEFAULT 0,
                counter_threshold INTEGER DEFAULT 0,
                current_count INTEGER DEFAULT 0,
                last_sent_at REAL DEFAULT 0,
                is_active INTEGER DEFAULT 1,
                folder_name TEXT DEFAULT '',
                retry_at REAL DEFAULT 0,
                fail_count INTEGER DEFAULT 0,
                manual_stop INTEGER DEFAULT 0,
                counter_ready_at REAL DEFAULT 0,
                last_attempt_at REAL DEFAULT 0,
                send_pending INTEGER DEFAULT 0,
                last_count_at REAL DEFAULT 0
            )"""
        )
        conn.execute(
            "INSERT INTO broadcast_tasks(account_id,chat_id,template_name,mode,interval_seconds,is_active,last_sent_at) "
            "VALUES(1,99,'promo','hybrid',900,1,100)"
        )
        conn.execute(
            "INSERT INTO broadcast_tasks(account_id,chat_id,template_name,mode,interval_seconds,is_active,last_sent_at) "
            "VALUES(1,99,'promo','hybrid',900,1,200)"
        )

    repaired = bot.Database(path)
    rows = repaired.get_active_interval_tasks(account_id=1)
    assert len(rows) == 1
    assert rows[0]["last_sent_at"] == 200


def test_hybrid_parser_accepts_human_conjunction_before_minimum_delay():
    mode, interval, threshold, name, folder, error = bot.parse_broadcast_params(
        ".рассыл через 15 соо и 15 минут promo"
    )
    assert (mode, interval, threshold, name, folder, error) == (
        "hybrid", 900, 15, "promo", "", ""
    )
