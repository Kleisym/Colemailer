#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Самопроверка Colemailer на любой ОС: Windows, Linux, macOS, Termux.

Запуск:
    python scripts/selfcheck.py
    python scripts/selfcheck.py --verbose

Ничего не отправляет в Telegram, не требует api_id и не трогает рабочие
config.txt/сессию: всё делается во временном каталоге. Код возврата 0 —
всё в порядке, 1 — есть проблема (подробности в выводе).
"""
from __future__ import annotations

import argparse
import os
import platform
import sys
import tempfile
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CHECKS = []


def check(name):
    def decorator(func):
        CHECKS.append((name, func))
        return func
    return decorator


def _temp_db():
    import bot
    tmp = Path(tempfile.mkdtemp(prefix="colemailer_selfcheck_"))
    return bot.Database(tmp / "bot.db"), tmp


@check("версия и импорт")
def check_import():
    import bot
    from cole.version import VERSION
    assert VERSION, "пустая версия"
    assert bot.APP_VERSION == VERSION
    return f"{bot.APP_NAME} {VERSION}"


@check("config.txt: чтение, BOM, CRLF")
def check_config():
    import bot
    tmp = Path(tempfile.mkdtemp(prefix="colemailer_cfg_"))
    cfg = tmp / "config.txt"
    cfg.write_text(
        "\ufefflog_errors_only = false\r\napi_id = 12345678\r\n"
        "api_hash = 0123456789abcdef0123456789abcdef\r\n"
        'phone = "+79991234567"\r\nsession_name = selfcheck\r\n',
        encoding="utf-8",
    )
    loaded = bot.load_config(cfg)
    assert loaded["api_id"] == 12345678
    assert loaded["log_errors_only"] is False
    assert loaded["session_name"] == "selfcheck"
    return "ok"


@check("SQLite: шаблоны, мьюты, задачи")
def check_db():
    db, tmp = _temp_db()
    db.save_template("пост", "привет", [], [], buttons_json="[[{\"text\":\"A\",\"type\":\"url\",\"value\":\"https://t.me/a\"}]]")
    assert db.get_template("пост")["buttons"]
    db.add_or_update_broadcast(chat_id=1, template_name="пост", mode="hybrid",
                               interval_seconds=900, counter_threshold=15, account_id=1)
    db.add_muted_peer(peer_id=42, account_id=1, peer_key=42, username="юзер")
    assert db.list_muted_peers(1)
    return "ok"


@check("мьюты: человек везде и только в одном чате")
def check_mutes():
    import bot
    db, _tmp = _temp_db()
    old = bot.db
    bot.db = db
    try:
        db.add_muted_peer(peer_id=42, account_id=1, peer_key=42, scope="user", action="silent")
        db.add_muted_peer(peer_id=43, account_id=1, peer_key=43, scope="user", action="delete", chat_id=-100)
        bot.mute_cache_rebuild(1)
        assert bot.mute_action_for(1, 42, -100) == "silent"
        assert bot.mute_action_for(1, 42, -200) == "silent"
        assert bot.mute_action_for(1, 43, -100) == "delete"
        assert bot.mute_action_for(1, 43, -200) is None
        assert bot.mute_scope_for(1, 43, -100) == "user_chat"
    finally:
        bot.db = old
    return "ok"


@check("гибрид: порог и интервал, без досрочной отправки")
def check_hybrid():
    import bot
    db, _tmp = _temp_db()
    db.save_template("h", "text", [], [])
    db.add_or_update_broadcast(chat_id=5, template_name="h", mode="hybrid",
                               interval_seconds=900, counter_threshold=3, account_id=1)
    task = db.get_chat_broadcasts(5, 1)[0]
    with db._conn() as conn:
        conn.execute("UPDATE broadcast_tasks SET last_sent_at=? WHERE id=?", (time.time(), task["id"]))
    for _ in range(3):
        assert db.increment_and_check_counter(5, account_id=1) == []
    task = db.get_chat_broadcasts(5, 1)[0]
    assert task["current_count"] == 3
    assert db.claim_hybrid_task(task["id"], time.time(), stale_after=2700) is False, "отправка раньше интервала"
    with db._conn() as conn:
        conn.execute("UPDATE broadcast_tasks SET last_sent_at=? WHERE id=?", (time.time() - 1000, task["id"]))
    assert db.claim_hybrid_task(task["id"], time.time(), stale_after=2700) is True
    return "ok"


@check("кнопки: раскладка и Telethon")
def check_buttons():
    import bot
    from cole.buttons import build_markup, describe, extract_buttons
    text, rows = extract_buttons("пост\n[Купить](https://t.me/a) || [Прайс](cb:x)\n[Написать](https://t.me/b)")
    assert text == "пост" and len(rows) == 2
    markup = build_markup(rows)
    assert markup is not None and len(markup.rows) == 2
    assert len(markup.rows[0].buttons) == 2
    assert "Купить" in describe(rows)
    return "ok"


@check("api_autoreg: разбор страницы my.telegram.org")
def check_api_parser():
    from cole.api_autoreg import parse_apps_page
    html = (
        '<label>App api_id:</label><span class="x">1234567</span>'
        '<label>App api_hash:</label><span>0123456789abcdef0123456789abcdef</span>'
    )
    app = parse_apps_page(html)
    assert app and app["api_id"] == 1234567
    assert parse_apps_page("<html>login</html>") is None
    return "ok"


@check("файловый лок одного аккаунта")
def check_lock():
    import bot
    key = f"selfcheck-{os.getpid()}"
    try:
        assert bot.acquire_instance_lock(key) is True
        assert bot.acquire_instance_lock(key) is False
    finally:
        bot.release_instance_lock(key)
    return "ok"


@check("рабочий config.txt (если есть)")
def check_work_config():
    import bot
    if not bot.CONFIG_PATH.exists():
        return "нет config.txt (это нормально до настройки)"
    loaded = bot.load_config()
    accounts = loaded.get("accounts") or []
    if not accounts:
        return "config.txt пустой"
    ready = [a for a in accounts if a.get("api_id") and a.get("api_hash")]
    return f"аккаунтов: {len(accounts)}, с ключами: {len(ready)}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Самопроверка Colemailer")
    parser.add_argument("--verbose", action="store_true", help="печатать traceback при ошибке")
    args = parser.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    print(f"Colemailer selfcheck")
    print(f"  ОС:      {platform.platform()}")
    print(f"  Python:  {sys.version.split()[0]} ({sys.implementation.name})")
    print(f"  Каталог: {ROOT}")
    print(f"  Файлы:   bot.py={'да' if (ROOT / 'bot.py').exists() else 'НЕТ'}, "
          f"cole={'да' if (ROOT / 'cole').is_dir() else 'НЕТ'}")
    print("-" * 60)

    failed = 0
    for name, func in CHECKS:
        started = time.perf_counter()
        try:
            detail = func()
            spent = (time.perf_counter() - started) * 1000
            print(f"[OK]   {name}: {detail} ({spent:.0f} мс)")
        except Exception as exc:
            failed += 1
            print(f"[FAIL] {name}: {type(exc).__name__}: {exc}")
            if args.verbose:
                traceback.print_exc()

    print("-" * 60)
    if failed:
        print(f"Провалено проверок: {failed}. Пришли этот вывод разработчику.")
        return 1
    print("Всё в порядке: бот, база, мьюты, гибрид, кнопки и api-парсер работают.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
