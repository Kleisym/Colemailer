# -*- coding: utf-8 -*-
"""Кроссплатформенные вещи: конфиг, пути, блокировки, база.

Эти тесты гоняются на Windows, Linux и macOS в CI. Они проверяют то, что
обычно ломается при переносе: BOM/CRLF в config.txt, кириллица и пробелы в
путях, файловый лок одного аккаунта и запись ключей в нужную секцию.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

import bot
from tests.support import MY_ID


def write(path: Path, text: str, encoding: str = "utf-8") -> Path:
    path.write_text(text, encoding=encoding)
    return path


def test_config_accepts_bom_crlf_and_quotes(tmp_path):
    cfg = tmp_path / "config.txt"
    body = (
        "\ufefflog_errors_only = false\r\n"
        "api_id = 12345678\r\n"
        "api_hash = '0123456789abcdef0123456789abcdef'\r\n"
        'phone = "+79991234567"\r\n'
        "auto_sub_folder = \"Моя папка\"\r\n"
    )
    write(cfg, body, encoding="utf-8")
    loaded = bot.load_config(cfg)
    assert loaded["log_errors_only"] is False
    assert loaded["api_id"] == 12345678
    assert loaded["api_hash"] == "0123456789abcdef0123456789abcdef"
    assert loaded["phone"] == "+79991234567"
    assert loaded["auto_sub_folder"] == "Моя папка"


def test_config_sections_and_flat_file(tmp_path):
    cfg = tmp_path / "multi.txt"
    write(cfg, (
        "log_errors_only = true\n"
        "[account1]\n"
        "api_id = 11111111\n"
        "api_hash = aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
        "phone = +79990000001\n"
        "[account2]\n"
        "api_id = 22222222\n"
        "api_hash = bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb\n"
    ))
    loaded = bot.load_config(cfg)
    assert len(loaded["accounts"]) == 2
    assert loaded["accounts"][0]["name"] == "account1"
    assert loaded["accounts"][1]["api_id"] == 22222222
    # Глобальные ключи при наличии секций не читаются.
    assert loaded["api_id"] == 11111111


def test_write_credentials_flat_and_sections(tmp_path, monkeypatch):
    flat = tmp_path / "flat.txt"
    write(flat, "log_errors_only = true\napi_id =\napi_hash =\nphone =\n")
    monkeypatch.setattr(bot, "CONFIG_PATH", flat)
    bot._write_credentials(12345678, "a" * 32, "+79991234567")
    loaded = bot.load_config(flat)
    assert loaded["api_id"] == 12345678
    assert loaded["phone"] == "+79991234567"

    multi = tmp_path / "multi.txt"
    write(multi, "log_errors_only = true\n[account1]\napi_id = 1\napi_hash = x\n[account2]\napi_id = 2\napi_hash = y\n")
    monkeypatch.setattr(bot, "CONFIG_PATH", multi)
    bot._write_credentials(87654321, "b" * 32, "+79990000002")
    text = multi.read_text(encoding="utf-8")
    first = text.split("[account2]")[0]
    assert "api_id = 87654321" in first
    assert "api_id = 2" in text.split("[account2]")[1]


def test_instance_lock_is_exclusive_and_releases():
    key = f"pytest-{os.getpid()}-{id(object())}"
    try:
        assert bot.acquire_instance_lock(key) is True
        assert bot.acquire_instance_lock(key) is False
    finally:
        bot.release_instance_lock(key)
    assert bot.acquire_instance_lock(key) is True
    bot.release_instance_lock(key)


def test_instance_lock_path_is_safe(tmp_path):
    path = bot._instance_lock_path("acct:-100123/../x")
    assert path.parent.exists()
    assert "/" not in path.name and "\\" not in path.name
    assert path.name.startswith("colemailer_")


def test_database_survives_unicode_and_spaces(tmp_path):
    folder = tmp_path / "кириллица и пробелы"
    folder.mkdir()
    db = bot.Database(folder / "база бота.db")
    db.save_template("пост", "привет", [], [])
    assert db.get_template("пост")["text"] == "привет"
    db.add_muted_peer(peer_id=123, account_id=MY_ID, peer_key=123, username="юзер")
    rows = db.list_muted_peers(MY_ID)
    assert rows and rows[0]["username"] == "юзер"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX-права проверяются на Linux/macOS")
def test_posix_lock_does_not_depend_on_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    key = f"posix-{os.getpid()}"
    try:
        assert bot.acquire_instance_lock(key)
    finally:
        bot.release_instance_lock(key)


def test_default_config_file_is_created_in_temp(tmp_path):
    target = tmp_path / "config.txt"
    loaded = bot.load_config(target)
    # Файла нет и это не CONFIG_PATH по умолчанию: пустой конфиг без падения.
    assert loaded["accounts"] == []
    assert not target.exists()


def test_help_fits_telegram_message_limit():
    chunks = bot._split_for_telegram(bot.HELP_TEXT)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 3800
    # Ни одна строка не потерялась и не разорвалась.
    assert sum(len(c.splitlines()) for c in chunks) == len(bot.HELP_TEXT.splitlines())
