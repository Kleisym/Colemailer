# -*- coding: utf-8 -*-
"""Общие фикстуры для тестов Colemailer.

Главное здесь — изоляция базы и кэшей: каждый тест получает собственную
временную sqlite-базу, поэтому набор можно запускать повторно и параллельно
без гонки за один и тот же файл в CWD.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import bot  # noqa: E402


@pytest.fixture()
def tmp_db(monkeypatch):
    """Свежая база + пустые кэши мьютов на каждый тест."""
    tmpdir = Path(tempfile.mkdtemp(prefix="cole_tests_"))
    database = bot.Database(tmpdir / "bot.db")
    monkeypatch.setattr(bot, "db", database, raising=False)
    for name, value in (
        ("_MUTE_CACHE", {}),
        ("_MUTE_CHAT_CACHE", {}),
        ("_MUTE_ACTION_CACHE", {}),
        ("_MUTE_ACTION_CHAT_CACHE", {}),
        ("_MUTE_USER_CHAT_CACHE", {}),
        ("_MUTE_WARN_COOLDOWN", {}),
        ("_GENUINE_PINGS", {}),
        ("_PRESERVED_PINGS", set()),
        ("OWN_ACCOUNT_IDS", set()),
        ("_BOT_SYSTEM_MSG_IDS", set()),
    ):
        monkeypatch.setattr(bot, name, value, raising=False)
    # Дедуп-ринг глобальный: без сброса второй тест с тем же (chat_id, msg_id)
    # молча получил бы "дубликат" и не дошёл до проверяемой ветки.
    bot._GLOBAL_DEDUP_RING._deque.clear()
    bot._GLOBAL_DEDUP_RING._set.clear()
    try:
        yield database
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
