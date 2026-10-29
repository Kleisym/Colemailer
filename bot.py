import asyncio
from contextlib import contextmanager
import collections
import copy
import getpass
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import sys
import time
import unicodedata
from typing import Any, Deque, Dict, List, Optional, Set, Tuple

from telethon import TelegramClient, errors, events, utils
from telethon.errors import SessionPasswordNeededError
from telethon.extensions import BinaryReader
from telethon.tl.functions.account import UpdateNotifySettingsRequest
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import (
    GetDialogFiltersRequest,
    ImportChatInviteRequest,
    ReadMentionsRequest,
    UpdateDialogFilterRequest,
)
from telethon.tl.types import (
    DialogFilter,
    DialogFilterChatlist,
    InputNotifyPeer,
    InputPeerNotifySettings,
    TextWithEntities,
)

try:
    from telethon._updates.messagebox import MessageBox  # noqa: F401  (проверка совместимости)
except Exception:
    MessageBox = None  # type: ignore

try:
    from cole.version import VERSION as APP_VERSION
except Exception:
    APP_VERSION = "3.0.0"

APP_NAME = "Colemailer"

BASE_DIR = Path(__file__).resolve().parent
STORAGE_DIR = BASE_DIR / "storage"
MEDIA_DIR = STORAGE_DIR / "media"
DB_PATH = STORAGE_DIR / "bot.db"
CONFIG_PATH = BASE_DIR / "config.txt"

try:
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
except Exception:
    pass

def init_app_storage(app_dir: str):
    global BASE_DIR, STORAGE_DIR, MEDIA_DIR, DB_PATH, CONFIG_PATH, db
    BASE_DIR = Path(app_dir).resolve()
    STORAGE_DIR = BASE_DIR / "storage"
    MEDIA_DIR = STORAGE_DIR / "media"
    DB_PATH = STORAGE_DIR / "bot.db"
    CONFIG_PATH = BASE_DIR / "config.txt"
    STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    db = Database(DB_PATH)
    return db

DEFAULT_CONFIG = """# ==============================================================================
# КАК ПОЛУЧИТЬ API_ID И API_HASH:
# 1. Зайди в браузере на https://my.telegram.org
# 2. Введи свой номер телефона с кодом страны (напр. +79991234567) и нажми Next.
# 3. В Telegram придет код от официального сервиса — вставь его на сайте и нажми Sign In.
# 4. Выбери пункт "API development tools".
# 5. В форме заполни два поля (любыми латинскими буквами):
#    - App title: например, Colemailer
#    - Short name: например, colemailer
#    Остальные поля оставь пустыми.
# 6. Нажми "Create application" (или Save changes).
# 7. Скопируй полученные данные:
#    - App api_id  -> вставь ниже в api_id (только цифры)
#    - App api_hash -> вставь ниже в api_hash (строка из 32 символов)
# ==============================================================================

# Показывать только ошибки (true — тихий режим, false — подробные логи)
log_errors_only = true

# ==============================================================================
# ОСНОВНОЙ АККАУНТ:
# ==============================================================================
api_id = 
api_hash = 
phone = 
session_name = session_userbot
auto_sub_folder = автосабнутое
auto_read_spam_pings = true
auto_sub_enabled = true

# ==============================================================================
# ДЛЯ ДОБАВЛЕНИЯ ВТОРОГО И ПОСЛЕДУЮЩИХ АККАУНТОВ (раскомментируйте блок ниже):
# ==============================================================================
# [account2]
# api_id = 12345678
# api_hash = 0123456789abcdef0123456789abcdef
# phone = +79997654321
# session_name = session_userbot2
# auto_sub_folder = автосабнутое
# auto_read_spam_pings = true
# auto_sub_enabled = true
"""

def load_config(config_file: Optional[Path] = None) -> Dict[str, Any]:
    target_path = config_file or CONFIG_PATH
    if not target_path.exists():
        if target_path == CONFIG_PATH:
            try:
                target_path.write_text(DEFAULT_CONFIG, encoding="utf-8")
            except Exception:
                pass
        else:
            return {"accounts": [], "log_errors_only": True}

    if not target_path.exists():
        return {"accounts": [], "log_errors_only": True}

    try:
        content = target_path.read_text(encoding="utf-8")
    except Exception:
        return {"accounts": [], "log_errors_only": True}
    lines = content.splitlines()

    has_sections = any(re.match(r"^\[.+\]$", l.strip()) for l in lines if l.strip() and not l.strip().startswith("#"))

    global_log_errors_only = True
    accounts: List[Dict[str, Any]] = []

    if has_sections:
        current_acc: Optional[Dict[str, Any]] = None
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            sec_match = re.match(r"^\[(.+)\]$", line)
            if sec_match:
                sec_name = sec_match.group(1).strip()
                current_acc = {
                    "name": sec_name,
                    "api_id": 0,
                    "api_hash": "",
                    "phone": "",
                    "session_name": f"session_{sec_name}",
                    "auto_sub_folder": "автосабнутое",
                    "auto_read_spam_pings": True,
                    "auto_sub_enabled": True,
                }
                accounts.append(current_acc)
                continue

            if "=" in line:
                k, v = line.split("=", 1)
                key = k.strip().lower()
                val = v.strip().strip('"').strip("'")
                if key == "log_errors_only":
                    global_log_errors_only = val.lower() in ("true", "1", "yes")
                elif current_acc is not None:
                    if key == "api_id":
                        current_acc["api_id"] = int(val) if val.isdigit() else 0
                    elif key == "api_hash":
                        current_acc["api_hash"] = val
                    elif key == "phone":
                        current_acc["phone"] = val
                    elif key == "session_name":
                        current_acc["session_name"] = val or f"session_{current_acc['name']}"
                    elif key == "auto_sub_folder":
                        current_acc["auto_sub_folder"] = val or "автосабнутое"
                    elif key == "auto_read_spam_pings":
                        current_acc["auto_read_spam_pings"] = val.lower() in ("true", "1", "yes")
                    elif key == "auto_sub_enabled":
                        current_acc["auto_sub_enabled"] = val.lower() in ("true", "1", "yes")
    else:
        single_acc = {
            "name": "default",
            "api_id": 0,
            "api_hash": "",
            "phone": "",
            "session_name": "session_userbot",
            "auto_sub_folder": "автосабнутое",
            "auto_read_spam_pings": True,
            "auto_sub_enabled": True,
        }
        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, v = line.split("=", 1)
                key = k.strip().lower()
                val = v.strip().strip('"').strip("'")
                if key == "log_errors_only":
                    global_log_errors_only = val.lower() in ("true", "1", "yes")
                elif key == "api_id":
                    single_acc["api_id"] = int(val) if val.isdigit() else 0
                elif key == "api_hash":
                    single_acc["api_hash"] = val
                elif key == "phone":
                    single_acc["phone"] = val
                elif key == "session_name":
                    single_acc["session_name"] = val or "session_userbot"
                elif key == "auto_sub_folder":
                    single_acc["auto_sub_folder"] = val or "автосабнутое"
                elif key == "auto_read_spam_pings":
                    single_acc["auto_read_spam_pings"] = val.lower() in ("true", "1", "yes")
                elif key == "auto_sub_enabled":
                    single_acc["auto_sub_enabled"] = val.lower() in ("true", "1", "yes")
        accounts.append(single_acc)

    first = accounts[0] if accounts else {}
    return {
        "accounts": accounts,
        "log_errors_only": global_log_errors_only,
        "api_id": first.get("api_id", 0),
        "api_hash": first.get("api_hash", ""),
        "phone": first.get("phone", ""),
        "session_name": first.get("session_name", "session_userbot"),
        "auto_sub_folder": first.get("auto_sub_folder", "автосабнутое"),
        "auto_read_spam_pings": first.get("auto_read_spam_pings", True),
        "auto_sub_enabled": first.get("auto_sub_enabled", True),
    }

try:
    CONFIG = load_config()
except Exception:
    CONFIG = {"accounts": [], "log_errors_only": True}

def log_info(msg: str):
    if not CONFIG.get("log_errors_only", True):
        print(msg)

def log_error(msg: str):
    print(msg)

# ---------------------------------------------------------------------------
# Кнопки постов. Разбор и сборка живут в cole/buttons.py, здесь только
# тонкие обёртки: так бот остаётся рабочим, даже если пакет не скопировали.
# ---------------------------------------------------------------------------
def _row_get(row: Any, key: str, default: Any = ""):
    try:
        return row[key]
    except Exception:
        return default


def buttons_from_json(raw: Optional[str]) -> List[Any]:
    try:
        from cole.buttons import from_json
    except Exception:
        return []
    return from_json(raw)


def buttons_to_json(rows: Optional[Any]) -> str:
    try:
        from cole.buttons import to_json
    except Exception:
        return ""
    return to_json(rows)


def build_buttons_markup(rows: Optional[Any]):
    try:
        from cole.buttons import build_markup
        return build_markup(rows)
    except Exception as e:
        log_error(f"[BTN] Кнопки не собраны ({type(e).__name__}: {e}) — пост уйдёт без них.")
        return None


def extract_buttons_block(payload: str) -> Tuple[str, List[Any]]:
    try:
        from cole.buttons import ButtonError, extract_buttons
    except Exception:
        return payload, []
    return extract_buttons(payload)


def describe_buttons(rows: Optional[Any]) -> str:
    try:
        from cole.buttons import describe
    except Exception:
        return "нет"
    return describe(rows)


_BOT_SYSTEM_MSG_IDS: Set[int] = set()

def is_internal_bot_message(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    # 1. Collector status notifications and interactive prompts
    if "добавлено в рассылку" in t and ("📥" in t or "Сообщение #" in t or "сообщение #" in t):
        return True
    if "Отправьте следующее сообщение или напишите" in t and (".закрыть" in t or "отменить" in t or ".отменить" in t):
        return True
    if "(для отмены .отменить)" in t or "(для отмены `.отменить`)" in t or "(для отмены отменить)" in t:
        return True
    if "Режим сбора" in t and ("активирован" in t or "начат" in t) and "📥" in t:
        return True
    if "Время ожидания сообщений (5 минут) истекло" in t:
        return True
    # 2. System command feedback
    if t.startswith("⚙️ Управление юзерботом"):
        return True
    if t.startswith("👁 Тестовый предпросмотр:"):
        return True
    if t.startswith("❌ Настройка рассылки") and "отменена" in t:
        return True
    if t.startswith("✅ Рассылка") and ("запущена" in t or "остановлена" in t):
        return True
    if t.startswith(("🔘 Пришли раскладку", "✅ Кнопки", "🧹 Кнопки", "⚠️ Кнопки", "⚠️ Не вижу ни одной кнопки")):
        return True
    if "Превью ссылок" in t and t.startswith(("🚫", "🖼")):
        return True
    if t.startswith("🔇 ") and ("Заглушен" in t or "Обновлён мьют" in t):
        return True
    return False

class Database:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA busy_timeout=30000;")
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            cursor = conn.cursor()
            try:
                cursor.execute("PRAGMA journal_mode=WAL;")
                cursor.execute("PRAGMA synchronous=NORMAL;")
                cursor.execute("PRAGMA temp_store=MEMORY;")
                cursor.execute("PRAGMA cache_size=-2000;")
            except Exception:
                pass
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS templates (
                    name TEXT PRIMARY KEY,
                    text TEXT,
                    entities_hex TEXT,
                    media_files TEXT,
                    bundle_json TEXT DEFAULT '',
                    created_at REAL
                )
            """)
            try:
                cursor.execute("PRAGMA table_info(templates)")
                cols = [r["name"] for r in cursor.fetchall()]
                if "bundle_json" not in cols:
                    cursor.execute("ALTER TABLE templates ADD COLUMN bundle_json TEXT DEFAULT ''")
                if "buttons_json" not in cols:
                    cursor.execute("ALTER TABLE templates ADD COLUMN buttons_json TEXT DEFAULT ''")
                if "disable_preview" not in cols:
                    cursor.execute("ALTER TABLE templates ADD COLUMN disable_preview INTEGER DEFAULT 0")
                if "source_chat_id" not in cols:
                    cursor.execute("ALTER TABLE templates ADD COLUMN source_chat_id INTEGER DEFAULT 0")
            except Exception:
                pass

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS broadcast_tasks (
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
                    UNIQUE(account_id, chat_id, template_name)
                )
            """)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_broadcast_tasks_chat ON broadcast_tasks (chat_id, is_active, mode);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_broadcast_tasks_active ON broadcast_tasks (is_active, mode, account_id);")

            # One row per running folder broadcast. Tasks are still materialised
            # per chat, but this registry is what lets the scheduler notice chats
            # added to a folder after the broadcast was created.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS folder_broadcasts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER DEFAULT 0,
                    folder_name TEXT,
                    template_name TEXT,
                    mode TEXT,
                    interval_seconds INTEGER DEFAULT 0,
                    counter_threshold INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1,
                    created_at REAL
                )
            """)
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_folder_broadcasts_unique ON folder_broadcasts (account_id, folder_name, template_name);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_folder_broadcasts_active ON folder_broadcasts (is_active, account_id);")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_rotations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER DEFAULT 0,
                    chat_id INTEGER,
                    name TEXT DEFAULT '',
                    template_names TEXT,
                    current_index INTEGER DEFAULT 0,
                    is_active INTEGER DEFAULT 1
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS muted_peers (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    account_id INTEGER DEFAULT 0,
                    peer_id INTEGER,
        peer_key INTEGER,
                    username TEXT,
                    display_name TEXT,
                    scope TEXT DEFAULT 'user',
                    action TEXT DEFAULT 'silent',
                    reason TEXT DEFAULT '',
                    created_at REAL
                )
            """)
            try:
                cursor.execute("PRAGMA table_info(muted_peers)")
                cols = [r["name"] for r in cursor.fetchall()]
                if "action" not in cols:
                    cursor.execute("ALTER TABLE muted_peers ADD COLUMN action TEXT DEFAULT 'silent'")
            except Exception:
                pass
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_muted_peers_lookup ON muted_peers (account_id, peer_key);")
            cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_muted_peers_unique ON muted_peers (account_id, peer_key);")

            try:
                cursor.execute("PRAGMA table_info(broadcast_tasks)")
                cols = [r["name"] for r in cursor.fetchall()]
                if "account_id" not in cols:
                    cursor.execute("ALTER TABLE broadcast_tasks ADD COLUMN account_id INTEGER DEFAULT 0")
                # retry_at: a failed counter-mode post is re-sent by the timer
                # after a back-off instead of "on the very next message"
                # (which ignored the configured message count).
                if "retry_at" not in cols:
                    cursor.execute("ALTER TABLE broadcast_tasks ADD COLUMN retry_at REAL DEFAULT 0")
                if "fail_count" not in cols:
                    cursor.execute("ALTER TABLE broadcast_tasks ADD COLUMN fail_count INTEGER DEFAULT 0")
                # manual_stop: stopped/removed by the user in ONE chat of a
                # folder broadcast. The folder sync must not resurrect it.
                if "manual_stop" not in cols:
                    cursor.execute("ALTER TABLE broadcast_tasks ADD COLUMN manual_stop INTEGER DEFAULT 0")
                # hybrid: момент, когда счётчик добрал порог. Отправка не должна
                # догонять задачу через часы после того, как чат замолчал.
                if "counter_ready_at" not in cols:
                    cursor.execute("ALTER TABLE broadcast_tasks ADD COLUMN counter_ready_at REAL DEFAULT 0")
                if "last_attempt_at" not in cols:
                    cursor.execute("ALTER TABLE broadcast_tasks ADD COLUMN last_attempt_at REAL DEFAULT 0")
                if "send_pending" not in cols:
                    cursor.execute("ALTER TABLE broadcast_tasks ADD COLUMN send_pending INTEGER DEFAULT 0")
                if "last_count_at" not in cols:
                    cursor.execute("ALTER TABLE broadcast_tasks ADD COLUMN last_count_at REAL DEFAULT 0")
            except Exception:
                pass

            # Per-chat position inside a named rotation. A single global index
            # meant that with 2 chats and 2 posts every chat always received
            # the same post and never rotated.
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS rotation_progress (
                    account_id INTEGER DEFAULT 0,
                    rotation_id INTEGER,
                    chat_id INTEGER,
                    current_index INTEGER DEFAULT 0,
                    PRIMARY KEY (account_id, rotation_id, chat_id)
                )
            """)

            try:
                cursor.execute("PRAGMA table_info(chat_rotations)")
                cols = [r["name"] for r in cursor.fetchall()]
                if "account_id" not in cols:
                    cursor.execute("ALTER TABLE chat_rotations ADD COLUMN account_id INTEGER DEFAULT 0")
                if "name" not in cols:
                    cursor.execute("ALTER TABLE chat_rotations ADD COLUMN name TEXT DEFAULT ''")
            except Exception:
                pass

            # Auto-migrate any existing records with < > in names
            try:
                cursor.execute("SELECT name, text, entities_hex, media_files, created_at FROM templates")
                for r in cursor.fetchall():
                    old_name = r["name"]
                    new_name = old_name.strip("<>").strip()
                    if new_name != old_name:
                        cursor.execute("""
                            INSERT OR REPLACE INTO templates (name, text, entities_hex, media_files, created_at)
                            VALUES (?, ?, ?, ?, ?)
                        """, (new_name, r["text"], r["entities_hex"], r["media_files"], r["created_at"]))
                        cursor.execute("DELETE FROM templates WHERE name = ?", (old_name,))

                cursor.execute("SELECT id, template_name FROM broadcast_tasks")
                for r in cursor.fetchall():
                    old_name = r["template_name"]
                    new_name = old_name.strip("<>").strip()
                    if new_name != old_name:
                        cursor.execute("UPDATE broadcast_tasks SET template_name = ? WHERE id = ?", (new_name, r["id"]))

                cursor.execute("SELECT id, chat_id, template_names FROM chat_rotations")
                for r in cursor.fetchall():
                    names = json.loads(r["template_names"]) if r["template_names"] else []
                    new_names = [n.strip("<>").strip() for n in names if n.strip("<>").strip()]
                    if new_names != names:
                        cursor.execute("UPDATE chat_rotations SET template_names = ? WHERE id = ?", (json.dumps(new_names), r["id"]))
            except Exception:
                pass

    def save_template(
        self,
        name: str,
        text: str,
        entities_hex: List[str],
        media_files: List[str],
        bundle_json: str = "",
        buttons_json: str = "",
        disable_preview: int = 0,
        source_chat_id: int = 0,
    ):
        clean_name = name.strip("<>").strip()
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO templates
                    (name, text, entities_hex, media_files, bundle_json,
                     buttons_json, disable_preview, source_chat_id, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (clean_name, text, json.dumps(entities_hex), json.dumps(media_files),
                  bundle_json, buttons_json or "", int(disable_preview or 0),
                  int(source_chat_id or 0), time.time()))

    def get_template(self, name: str) -> Optional[Dict[str, Any]]:
        clean_name = name.strip("<>").strip()
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM templates WHERE name = ? OR name = ? OR name = ?", (clean_name, name, f"<{clean_name}>"))
            row = cursor.fetchone()
            if not row:
                return None
            bundle_raw = ""
            if "bundle_json" in row.keys() and row["bundle_json"]:
                bundle_raw = row["bundle_json"]
            bundle = json.loads(bundle_raw) if bundle_raw else []
            if bundle:
                clean_bundle = [it for it in bundle if not is_internal_bot_message(it.get("text", ""))]
                if len(clean_bundle) != len(bundle):
                    bundle = clean_bundle
                    try:
                        cursor.execute("UPDATE templates SET bundle_json = ? WHERE name = ?", (json.dumps(bundle), row["name"]))
                    except Exception:
                        pass
            return {
                "name": row["name"],
                "text": row["text"],
                "entities_hex": json.loads(row["entities_hex"]) if row["entities_hex"] else [],
                "media_files": json.loads(row["media_files"]) if row["media_files"] else [],
                "bundle": bundle,
                "buttons": buttons_from_json(_row_get(row, "buttons_json", "")),
                "disable_preview": int(_row_get(row, "disable_preview", 0) or 0),
                "source_chat_id": int(_row_get(row, "source_chat_id", 0) or 0),
                "created_at": row["created_at"]
            }

    def delete_template(self, name: str):
        clean_name = name.strip("<>").strip()
        target_dir = MEDIA_DIR / clean_name
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM templates WHERE name = ? OR name = ?", (clean_name, f"<{clean_name}>"))
            cursor.execute("DELETE FROM broadcast_tasks WHERE template_name = ? OR template_name = ?", (clean_name, f"<{clean_name}>"))
            cursor.execute(
                "DELETE FROM folder_broadcasts WHERE template_name = ? OR template_name = ?",
                (clean_name, f"<{clean_name}>")
            )
            cursor.execute("SELECT id, template_names FROM chat_rotations")
            for r in cursor.fetchall():
                names = json.loads(r["template_names"]) if r["template_names"] else []
                new_names = [n for n in names if n != clean_name and n != f"<{clean_name}>"]
                if len(new_names) != len(names):
                    if new_names:
                        cursor.execute("UPDATE chat_rotations SET template_names = ?, current_index = 0 WHERE id = ?", (json.dumps(new_names), r["id"]))
                    else:
                        cursor.execute("DELETE FROM chat_rotations WHERE id = ?", (r["id"],))

    def list_templates(self) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM templates ORDER BY created_at DESC")
            rows = cursor.fetchall()
            results = []
            for r in rows:
                bundle_raw = r["bundle_json"] if ("bundle_json" in r.keys() and r["bundle_json"]) else ""
                bundle = json.loads(bundle_raw) if bundle_raw else []
                if bundle:
                    clean_bundle = [it for it in bundle if not is_internal_bot_message(it.get("text", ""))]
                    if len(clean_bundle) != len(bundle):
                        bundle = clean_bundle
                        try:
                            cursor.execute("UPDATE templates SET bundle_json = ? WHERE name = ?", (json.dumps(bundle), r["name"]))
                        except Exception:
                            pass
                results.append({
                    "name": r["name"],
                    "text": r["text"],
                    "entities_hex": json.loads(r["entities_hex"]) if r["entities_hex"] else [],
                    "media_files": json.loads(r["media_files"]) if r["media_files"] else [],
                    "bundle": bundle,
                    "buttons": buttons_from_json(_row_get(r, "buttons_json", "")),
                    "disable_preview": int(_row_get(r, "disable_preview", 0) or 0),
                    "created_at": r["created_at"]
                })
            return results

    def add_or_update_broadcast(
        self,
        chat_id: int,
        template_name: str,
        mode: str,
        interval_seconds: int = 0,
        counter_threshold: int = 0,
        folder_name: str = "",
        account_id: int = 0
    ):
        clean_name = template_name.strip("<>").strip()
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id FROM broadcast_tasks 
                WHERE chat_id = ? AND template_name = ? AND account_id = ?
            """, (chat_id, clean_name, account_id))
            row = cursor.fetchone()
            if row:
                cursor.execute("""
                    UPDATE broadcast_tasks SET
                        account_id = ?,
                        mode = ?,
                        interval_seconds = ?,
                        counter_threshold = ?,
                        is_active = 1,
                        folder_name = ?,
                        current_count = 0,
                        last_sent_at = 0.0,
                        retry_at = 0,
                        fail_count = 0,
                        manual_stop = 0
                    WHERE id = ?
                """, (account_id, mode, interval_seconds, counter_threshold, folder_name, row["id"]))
            else:
                cursor.execute("""
                    INSERT INTO broadcast_tasks (account_id, chat_id, template_name, mode, interval_seconds, counter_threshold, is_active, folder_name, last_sent_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?, 0.0)
                """, (account_id, chat_id, clean_name, mode, interval_seconds, counter_threshold, folder_name))

    def register_folder_broadcast(
        self,
        folder_name: str,
        template_name: str,
        mode: str,
        interval_seconds: int = 0,
        counter_threshold: int = 0,
        account_id: int = 0
    ):
        """Persist a folder-level broadcast so the scheduler can keep it in sync."""
        clean_folder = (folder_name or "").strip()
        clean_name = template_name.strip("<>").strip()
        if not clean_folder:
            return
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO folder_broadcasts
                    (account_id, folder_name, template_name, mode, interval_seconds, counter_threshold, is_active, created_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?)
                ON CONFLICT(account_id, folder_name, template_name) DO UPDATE SET
                    mode = excluded.mode,
                    interval_seconds = excluded.interval_seconds,
                    counter_threshold = excluded.counter_threshold,
                    is_active = 1
            """, (account_id, clean_folder, clean_name, mode, interval_seconds, counter_threshold, time.time()))

    def get_active_folder_broadcasts(self, account_id: int = 0) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            if account_id:
                rows = conn.execute(
                    "SELECT * FROM folder_broadcasts WHERE is_active = 1 AND (account_id = ? OR account_id = 0)",
                    (account_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM folder_broadcasts WHERE is_active = 1").fetchall()
            return [dict(r) for r in rows]

    def set_folder_broadcast_status(
        self,
        folder_name: Optional[str] = None,
        name: Optional[str] = None,
        is_active: int = 1,
        account_id: int = 0
    ) -> int:
        with self._conn() as conn:
            cursor = conn.cursor()
            conditions = []
            params: List[Any] = [is_active]
            if account_id:
                conditions.append("(account_id = ? OR account_id = 0)")
                params.append(account_id)
            if folder_name:
                conditions.append("folder_name = ?")
                params.append(folder_name)
            if name and name.lower() not in ("все", "all"):
                clean_name = name.strip("<>").strip()
                conditions.append("(template_name = ? OR template_name = ?)")
                params.extend([clean_name, f"<{clean_name}>"])
            where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
            cursor.execute(f"UPDATE folder_broadcasts SET is_active = ?{where_clause}", params)
            return cursor.rowcount

    def delete_folder_broadcasts(
        self,
        folder_name: Optional[str] = None,
        name: Optional[str] = None,
        account_id: int = 0
    ) -> int:
        with self._conn() as conn:
            cursor = conn.cursor()
            conditions = []
            params: List[Any] = []
            if account_id:
                conditions.append("(account_id = ? OR account_id = 0)")
                params.append(account_id)
            if folder_name:
                conditions.append("folder_name = ?")
                params.append(folder_name)
            if name and name.lower() not in ("все", "all"):
                clean_name = name.strip("<>").strip()
                conditions.append("(template_name = ? OR template_name = ?)")
                params.extend([clean_name, f"<{clean_name}>"])
            where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
            cursor.execute(f"DELETE FROM folder_broadcasts{where_clause}", params)
            return cursor.rowcount

    def get_chats_in_broadcast(self, chat_id: int, template_name: str, account_id: int = 0) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            clean_name = template_name.strip("<>").strip()
            row = conn.execute(
                "SELECT * FROM broadcast_tasks WHERE chat_id = ? AND template_name = ? AND (account_id = ? OR account_id = 0)",
                (chat_id, clean_name, account_id)
            ).fetchone()
            return dict(row) if row else None

    def ensure_broadcast_task(
        self,
        chat_id: int,
        template_name: str,
        mode: str,
        interval_seconds: int = 0,
        counter_threshold: int = 0,
        folder_name: str = "",
        account_id: int = 0
    ) -> bool:
        """
        Idempotent enrolment used by the folder reconciler.

        Returns True when a new task row was created. Crucially it never touches
        last_sent_at on an existing row: add_or_update_broadcast() zeroes that
        column, so re-registering every chat on every sync pass would reset every
        interval timer and fire the whole broadcast on each tick.
        """
        clean_name = template_name.strip("<>").strip()
        with self._conn() as conn:
            cursor = conn.cursor()
            row = cursor.execute(
                "SELECT id, is_active, mode, interval_seconds, counter_threshold, account_id, manual_stop "
                "FROM broadcast_tasks WHERE chat_id = ? AND template_name = ? AND account_id = ?",
                (chat_id, clean_name, account_id)
            ).fetchone()
            if row is not None and row["manual_stop"]:
                # The user stopped / removed this chat explicitly.
                return False
            if row is None:
                cursor.execute(
                    """
                    INSERT INTO broadcast_tasks
                        (account_id, chat_id, template_name, mode, interval_seconds,
                         counter_threshold, is_active, folder_name, last_sent_at)
                    VALUES (?, ?, ?, ?, ?, ?, 1, ?, 0.0)
                    """,
                    (account_id, chat_id, clean_name, mode, interval_seconds,
                     counter_threshold, folder_name)
                )
                return True

            # Re-activate when it was stopped or parked, and adopt config drift,
            # but leave the send timer alone.
            needs_update = (
                not row["is_active"]
                or row["mode"] != mode
                or (row["interval_seconds"] or 0) != (interval_seconds or 0)
                or (row["counter_threshold"] or 0) != (counter_threshold or 0)
            )
            if needs_update:
                cursor.execute(
                    """
                    UPDATE broadcast_tasks
                    SET account_id = ?, mode = ?, interval_seconds = ?,
                        counter_threshold = ?, is_active = 1, folder_name = ?
                    WHERE id = ?
                    """,
                    (account_id, mode, interval_seconds, counter_threshold,
                     folder_name, row["id"])
                )
            return False

    def get_enrolled_chat_ids(self, template_name: str, folder_name: str, account_id: int = 0) -> Set[int]:
        """Chats currently carrying an active task for this folder broadcast."""
        with self._conn() as conn:
            clean_name = template_name.strip("<>").strip()
            if account_id:
                rows = conn.execute(
                    "SELECT chat_id FROM broadcast_tasks "
                    "WHERE template_name = ? AND folder_name = ? AND is_active = 1 "
                    "AND (account_id = ? OR account_id = 0)",
                    (clean_name, folder_name, account_id)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT chat_id FROM broadcast_tasks "
                    "WHERE template_name = ? AND folder_name = ? AND is_active = 1",
                    (clean_name, folder_name)
                ).fetchall()
            return {r["chat_id"] for r in rows}

    def deactivate_broadcast_task(self, chat_id: int, template_name: str, account_id: int = 0) -> int:
        with self._conn() as conn:
            cursor = conn.cursor()
            clean_name = template_name.strip("<>").strip()
            cursor.execute(
                "UPDATE broadcast_tasks SET is_active = 0 "
                "WHERE chat_id = ? AND template_name = ? AND (account_id = ? OR account_id = 0)",
                (chat_id, clean_name, account_id)
            )
            return cursor.rowcount
    def remove_template_from_folder_broadcasts(self, template_name: str):
        clean_name = template_name.strip("<>").strip()
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM folder_broadcasts WHERE template_name = ? OR template_name = ?",
                (clean_name, f"<{clean_name}>")
            )

    def get_active_interval_tasks(self, account_id: int = 0) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            cursor = conn.cursor()
            if account_id:
                cursor.execute("""
                    SELECT * FROM broadcast_tasks 
                    WHERE is_active = 1 AND mode IN ('interval', 'hybrid') AND interval_seconds > 0
                    AND (account_id = ? OR account_id = 0)
                """, (account_id,))
            else:
                cursor.execute("""
                    SELECT * FROM broadcast_tasks 
                    WHERE is_active = 1 AND mode IN ('interval', 'hybrid') AND interval_seconds > 0
                """)
            return [dict(r) for r in cursor.fetchall()]

    def increment_and_check_counter(self, chat_id: int, account_id: int = 0) -> List[Dict[str, Any]]:
        """Посчитать живое сообщение чата и, если условия сошлись, отдать задачу.

        hybrid: порог сообщений и пауза проверяются вместе. Момент, когда
        счётчик добрал порог, запоминается в counter_ready_at — по нему потом
        видно, что окно протухло и догоняющей отправки быть не должно.
        """
        ready_tasks = []
        now = time.time()
        with self._conn() as conn:
            cursor = conn.cursor()
            if account_id:
                cursor.execute("""
                    SELECT * FROM broadcast_tasks 
                    WHERE chat_id = ? AND is_active = 1 AND mode IN ('counter', 'hybrid')
                    AND (account_id = ? OR account_id = 0)
                """, (chat_id, account_id))
            else:
                cursor.execute("""
                    SELECT * FROM broadcast_tasks 
                    WHERE chat_id = ? AND is_active = 1 AND mode IN ('counter', 'hybrid')
                """, (chat_id,))
            tasks = cursor.fetchall()
            for row in tasks:
                t = dict(row)
                mode = t.get("mode", "counter")
                threshold = max(int(t["counter_threshold"] or 0), 1)
                interval = int(t.get("interval_seconds") or 0)
                ready_at = float(t.get("counter_ready_at") or 0.0)

                # Протухшее окно: сообщения были давно, значит это не «15 сообщений
                # перед постом», а случайный хвост. Счёт начинается заново.
                stale_after = max(interval * 3, 1800) if mode == "hybrid" else 0
                if stale_after and ready_at and (now - ready_at) > stale_after:
                    ready_at = 0.0
                    t["current_count"] = 0
                last_count_at = float(t.get("last_count_at") or 0.0)
                if stale_after and not ready_at and int(t.get("current_count") or 0) > 0 \
                        and last_count_at and (now - last_count_at) > stale_after:
                    # Счётчик не добрал порог и замер: старые сообщения не в счёт.
                    t["current_count"] = 0

                new_count = int(t.get("current_count") or 0) + 1
                time_ready = mode != "hybrid" or (now - float(t.get("last_sent_at") or 0.0)) >= interval
                if mode == "hybrid" and new_count >= threshold and ready_at <= 0:
                    ready_at = now
                log_info(f"[COUNT] Чат {chat_id}: сообщение #{new_count}/{threshold} для рассылки '{t['template_name']}' ({mode})")

                # Счётчик не обнуляем здесь: состояние сбрасывается только
                # после реальной отправки (mark_task_sent). Иначе падение
                # процесса между claim и send теряет пост навсегда.
                if (new_count >= threshold and time_ready
                        and not (t.get("retry_at") or 0) > 0
                        and not int(t.get("send_pending") or 0)):
                    ready_tasks.append(t)
                cursor.execute("""
                    UPDATE broadcast_tasks
                    SET current_count = ?, counter_ready_at = ?, last_count_at = ?
                    WHERE id = ?
                """, (new_count, ready_at, now, t["id"]))
        return ready_tasks

    # ---- atomic claims: only one caller can win a due task -----------------
    def claim_counter_task(self, task_id: int, now: float) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE broadcast_tasks SET send_pending = 1, last_attempt_at = ? "
                "WHERE id = ? AND is_active = 1 AND COALESCE(send_pending, 0) = 0 "
                "AND current_count >= counter_threshold",
                (now, task_id),
            )
            return cur.rowcount == 1

    def claim_interval_task(self, task_id: int, now: float) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE broadcast_tasks SET last_sent_at = ?, last_attempt_at = ?, send_pending = 1 "
                "WHERE id = ? AND is_active = 1 AND COALESCE(send_pending, 0) = 0 "
                "AND (? - COALESCE(last_sent_at, 0)) >= interval_seconds",
                (now, now, task_id, now),
            )
            return cur.rowcount == 1

    def claim_hybrid_task(self, task_id: int, now: float, stale_after: float = 0.0) -> bool:
        """Забрать hybrid-задачу, если прошла пауза и порог ещё не протух."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM broadcast_tasks WHERE id = ? AND is_active = 1", (task_id,)
            ).fetchone()
            if not row:
                return False
            t = dict(row)
            ready_at = float(t.get("counter_ready_at") or 0.0)
            if stale_after and ready_at and (now - ready_at) > stale_after:
                conn.execute(
                    "UPDATE broadcast_tasks SET current_count = 0, counter_ready_at = 0, send_pending = 0 "
                    "WHERE id = ?", (task_id,),
                )
                log_info(f"[HYBRID] Чат {t['chat_id']}: окно счётчика протухло, ждём новые сообщения.")
                return False
            if int(t.get("send_pending") or 0):
                return False
            if int(t.get("current_count") or 0) < max(int(t.get("counter_threshold") or 0), 1):
                return False
            if (now - float(t.get("last_sent_at") or 0.0)) < int(t.get("interval_seconds") or 0):
                return False
            conn.execute(
                "UPDATE broadcast_tasks SET last_sent_at = ?, last_attempt_at = ?, send_pending = 1 WHERE id = ?",
                (now, now, task_id),
            )
            return True

    def schedule_retry(self, task: Dict[str, Any], delay: float, failed: bool = True):
        """
        Make a claimed-but-unsent task due again after `delay` seconds.

        interval/hybrid: сдвигаем last_sent_at так, чтобы таймер сработал через
        delay. hybrid получает свежее окно счётчика: это уже принятое решение
        отправить, ждать новых сообщений не нужно.
        counter: ставим retry_at; счётчик не подделываем.
        """
        mode = task.get("mode") or "interval"
        interval = task.get("interval_seconds") or 0
        threshold = max(int(task.get("counter_threshold") or 0), 1)
        delay = max(float(delay), 1.0)
        now = time.time()
        with self._conn() as conn:
            if mode in ("interval", "hybrid"):
                conn.execute(
                    "UPDATE broadcast_tasks SET last_sent_at = ?, send_pending = 0 WHERE id = ?",
                    (now - interval + delay, task["id"]),
                )
            if mode == "hybrid":
                conn.execute(
                    "UPDATE broadcast_tasks SET current_count = MAX(current_count, ?), counter_ready_at = ? WHERE id = ?",
                    (threshold, now + delay, task["id"]),
                )
            if mode == "counter":
                conn.execute(
                    "UPDATE broadcast_tasks SET retry_at = ?, send_pending = 0 WHERE id = ?",
                    (now + delay, task["id"]),
                )
            if failed:
                conn.execute(
                    "UPDATE broadcast_tasks SET fail_count = COALESCE(fail_count, 0) + 1 WHERE id = ?",
                    (task["id"],),
                )

    def get_fail_count(self, task_id: int) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT fail_count FROM broadcast_tasks WHERE id = ?", (task_id,)).fetchone()
            return int(row["fail_count"] or 0) if row else 0

    def mark_task_sent(self, task_id: int):
        with self._conn() as conn:
            conn.execute(
                "UPDATE broadcast_tasks SET fail_count = 0, retry_at = 0, send_pending = 0, "
                "current_count = 0, counter_ready_at = 0, last_count_at = 0, last_sent_at = ? WHERE id = ?",
                (time.time(), task_id),
            )

    def clear_pending(self, task_id: int):
        with self._conn() as conn:
            conn.execute("UPDATE broadcast_tasks SET send_pending = 0 WHERE id = ?", (task_id,))

    def reset_pending_sends(self, account_id: int = 0):
        """Подготовить задачи после старта процесса.

        - снять send_pending, зависший после падения;
        - сбросить накопленные счётчики: после рестарта порог считается заново,
          иначе «хвост» из прошлой сессии добивает 15 сообщений одним новым;
        - защита от скачка часов назад и от залпа по всем чатам после долгого
          простоя: слишком просроченная задача получает новый интервал.
        """
        scope = " AND (account_id = ? OR account_id = 0)" if account_id else ""
        params: List[Any] = [account_id] if account_id else []
        now = time.time()
        with self._conn() as conn:
            conn.execute(f"UPDATE broadcast_tasks SET send_pending = 0 WHERE send_pending = 1{scope}", params)
            conn.execute(
                f"UPDATE broadcast_tasks SET current_count = 0, counter_ready_at = 0, last_count_at = 0, retry_at = 0 "
                f"WHERE mode IN ('counter', 'hybrid'){scope}", params
            )
            conn.execute(
                f"UPDATE broadcast_tasks SET last_sent_at = ? WHERE last_sent_at > ?{scope}",
                [now, now + 300] + params,
            )
            conn.execute(
                f"UPDATE broadcast_tasks SET last_sent_at = ? "
                f"WHERE is_active = 1 AND interval_seconds > 0 AND last_sent_at > 0 "
                f"AND (? - last_sent_at) > MAX(interval_seconds * 3, 3600){scope}",
                [now - 1, now] + params,
            )

    def rearm_task(self, task_id: int):
        """Начать интервал заново (после ручного запуска или простоя)."""
        with self._conn() as conn:
            row = conn.execute("SELECT interval_seconds FROM broadcast_tasks WHERE id = ?", (task_id,)).fetchone()
            interval = int(row["interval_seconds"] or 0) if row else 0
            conn.execute(
                "UPDATE broadcast_tasks SET last_sent_at = ?, current_count = 0, counter_ready_at = 0, "
                "retry_at = 0, send_pending = 0 WHERE id = ?",
                (time.time() - interval, task_id),
            )

    def get_due_retries(self, account_id: int = 0, now: Optional[float] = None) -> List[Dict[str, Any]]:
        now = time.time() if now is None else now
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM broadcast_tasks WHERE is_active = 1 AND mode = 'counter' "
                "AND retry_at > 0 AND retry_at <= ? AND (account_id = ? OR ? = 0)",
                (now, account_id, account_id),
            ).fetchall()
            return [dict(r) for r in rows]

    def next_retry_at(self, account_id: int = 0) -> Optional[float]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT MIN(retry_at) AS t FROM broadcast_tasks WHERE is_active = 1 AND mode = 'counter' "
                "AND retry_at > 0 AND (account_id = ? OR ? = 0)",
                (account_id, account_id),
            ).fetchone()
            return float(row["t"]) if row and row["t"] else None

    def claim_retry(self, task_id: int, now: float) -> bool:
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE broadcast_tasks SET retry_at = 0, current_count = 0, last_sent_at = ? "
                "WHERE id = ? AND is_active = 1 AND retry_at > 0 AND retry_at <= ?",
                (now, task_id, now),
            )
            return cur.rowcount == 1

    def deactivate_task(self, task_id: int):
        with self._conn() as conn:
            conn.execute("UPDATE broadcast_tasks SET is_active = 0 WHERE id = ?", (task_id,))

    def adopt_legacy_rows(self, account_id: int):
        """
        Rows saved with account_id = 0 (old versions) were picked up by EVERY
        running account, so each of them sent the same post. The first account
        that starts now takes ownership of them.
        """
        if not account_id:
            return
        with self._conn() as conn:
            for table in ("broadcast_tasks", "folder_broadcasts", "chat_rotations", "muted_peers"):
                try:
                    conn.execute(f"UPDATE OR IGNORE {table} SET account_id = ? WHERE account_id = 0 OR account_id IS NULL", (account_id,))
                    conn.execute(f"DELETE FROM {table} WHERE account_id = 0 OR account_id IS NULL")
                except Exception:
                    pass

    def reset_hybrid_task(self, task_id: int):
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE broadcast_tasks SET current_count = 0, counter_ready_at = 0, last_count_at = 0, "
                "last_sent_at = ?, send_pending = 0 WHERE id = ?",
                (time.time(), task_id),
            )

    def update_task_last_sent(self, task_id: int):
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("UPDATE broadcast_tasks SET last_sent_at = ? WHERE id = ?", (time.time(), task_id))

    def restore_counter(self, task_id: int, count: int, last_sent_at: Optional[float] = None):
        with self._conn() as conn:
            cursor = conn.cursor()
            if last_sent_at is not None:
                cursor.execute("UPDATE broadcast_tasks SET current_count = ?, last_sent_at = ? WHERE id = ?", (count, last_sent_at, task_id))
            else:
                cursor.execute("UPDATE broadcast_tasks SET current_count = ? WHERE id = ?", (count, task_id))

    def count_tasks_for_template(self, template_name: str, account_id: int = 0) -> int:
        clean_name = template_name.strip("<>").strip()
        with self._conn() as conn:
            cursor = conn.cursor()
            if account_id:
                cursor.execute("""
                    SELECT COUNT(*) as cnt FROM broadcast_tasks 
                    WHERE (template_name = ? OR template_name = ?) 
                    AND (account_id = ? OR account_id = 0)
                """, (clean_name, f"<{clean_name}>", account_id))
            else:
                cursor.execute("""
                    SELECT COUNT(*) as cnt FROM broadcast_tasks 
                    WHERE (template_name = ? OR template_name = ?)
                """, (clean_name, f"<{clean_name}>"))
            row = cursor.fetchone()
            return row["cnt"] if row else 0

    # ---- user-facing stop / resume / delete with an explicit scope ---------
    @staticmethod
    def _scope_sql(account_id: int, name: Optional[str], chat_ids: Optional[List[int]], folder_name: Optional[str]):
        conds: List[str] = []
        params: List[Any] = []
        if account_id:
            conds.append("(account_id = ? OR account_id = 0)")
            params.append(account_id)
        if name and name.lower() not in ("все", "all"):
            clean = name.strip("<>").strip()
            conds.append("(template_name = ? OR template_name = ?)")
            params.extend([clean, f"<{clean}>"])
        sub: List[str] = []
        if folder_name:
            sub.append("folder_name = ?")
            params.append(folder_name)
        if chat_ids:
            sub.append(f"chat_id IN ({','.join('?' for _ in chat_ids)})")
            params.extend(chat_ids)
        if sub:
            conds.append(f"({' OR '.join(sub)})")
        return (" WHERE " + " AND ".join(conds)) if conds else "", params

    def stop_tasks(self, account_id: int = 0, name: Optional[str] = None, chat_ids: Optional[List[int]] = None,
                   folder_name: Optional[str] = None, manual: bool = False) -> int:
        where, params = self._scope_sql(account_id, name, chat_ids, folder_name)
        with self._conn() as conn:
            cur = conn.execute(f"UPDATE broadcast_tasks SET is_active = 0, manual_stop = ?{where}", [1 if manual else 0] + params)
            return cur.rowcount

    def resume_tasks(self, account_id: int = 0, name: Optional[str] = None, chat_ids: Optional[List[int]] = None,
                     folder_name: Optional[str] = None) -> int:
        """
        Direct (non-folder) tasks are re-enabled immediately. Folder tasks only
        lose their manual stop: the folder sync re-enables the ones whose chat
        is still in the folder, so chats that left it stay off.
        """
        where, params = self._scope_sql(account_id, name, chat_ids, folder_name)
        with self._conn() as conn:
            cur = conn.execute(
                "UPDATE broadcast_tasks SET manual_stop = 0, retry_at = 0, fail_count = 0, "
                "is_active = CASE WHEN folder_name IS NULL OR folder_name = '' THEN 1 ELSE is_active END" + where,
                params,
            )
            return cur.rowcount

    def delete_tasks(self, account_id: int = 0, name: Optional[str] = None, chat_ids: Optional[List[int]] = None,
                     folder_name: Optional[str] = None, keep_folder_tombstones: bool = False) -> int:
        """
        Delete tasks. With keep_folder_tombstones (deleting in ONE chat of a
        folder broadcast) folder rows are kept as manual-stop tombstones so the
        folder sync does not re-create them a minute later.
        """
        where, params = self._scope_sql(account_id, name, chat_ids, folder_name)
        with self._conn() as conn:
            if keep_folder_tombstones:
                n1 = conn.execute(
                    "UPDATE broadcast_tasks SET is_active = 0, manual_stop = 1" + where +
                    (" AND " if where else " WHERE ") + "folder_name IS NOT NULL AND folder_name != ''",
                    params,
                ).rowcount
                n2 = conn.execute(
                    "DELETE FROM broadcast_tasks" + where +
                    (" AND " if where else " WHERE ") + "(folder_name IS NULL OR folder_name = '')",
                    params,
                ).rowcount
                return n1 + n2
            return conn.execute("DELETE FROM broadcast_tasks" + where, params).rowcount

    def list_all_tasks(self, account_id: int = 0) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            if account_id:
                rows = conn.execute(
                    "SELECT * FROM broadcast_tasks WHERE (account_id = ? OR account_id = 0) ORDER BY template_name, chat_id",
                    (account_id,),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM broadcast_tasks ORDER BY template_name, chat_id").fetchall()
            return [dict(r) for r in rows]

    def list_folder_broadcasts(self, account_id: int = 0) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            if account_id:
                rows = conn.execute("SELECT * FROM folder_broadcasts WHERE account_id = ? OR account_id = 0", (account_id,)).fetchall()
            else:
                rows = conn.execute("SELECT * FROM folder_broadcasts").fetchall()
            return [dict(r) for r in rows]

    def count_live_tasks_for_template(self, template_name: str) -> int:
        """Tasks (any account) that still use a template, tombstones excluded."""
        clean = template_name.strip("<>").strip()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM broadcast_tasks WHERE (template_name = ? OR template_name = ?) AND COALESCE(manual_stop, 0) = 0",
                (clean, f"<{clean}>"),
            ).fetchone()
            return int(row["c"]) if row else 0

    def set_broadcast_status(
        self,
        name: Optional[str] = None,
        chat_id: Optional[int] = None,
        chat_ids: Optional[List[int]] = None,
        folder_name: Optional[str] = None,
        is_active: int = 1,
        account_id: int = 0
    ) -> int:
        with self._conn() as conn:
            cursor = conn.cursor()
            query = "UPDATE broadcast_tasks SET is_active = ?"
            params: List[Any] = [is_active]

            conditions = []
            if account_id:
                conditions.append("(account_id = ? OR account_id = 0)")
                params.append(account_id)

            if name and name.lower() not in ("все", "all"):
                clean_name = name.strip("<>").strip()
                conditions.append("(template_name = ? OR template_name = ?)")
                params.extend([clean_name, f"<{clean_name}>"])

            if folder_name or chat_ids:
                sub = []
                if folder_name:
                    sub.append("folder_name = ?")
                    params.append(folder_name)
                if chat_ids:
                    placeholders = ",".join("?" for _ in chat_ids)
                    sub.append(f"chat_id IN ({placeholders})")
                    params.extend(chat_ids)
                conditions.append(f"({' OR '.join(sub)})")
            elif chat_id is not None:
                conditions.append("chat_id = ?")
                params.append(chat_id)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            cursor.execute(query, params)
            return cursor.rowcount

    def delete_broadcasts(
        self,
        name: Optional[str] = None,
        chat_id: Optional[int] = None,
        chat_ids: Optional[List[int]] = None,
        folder_name: Optional[str] = None,
        account_id: int = 0
    ) -> int:
        with self._conn() as conn:
            cursor = conn.cursor()
            query = "DELETE FROM broadcast_tasks"
            params: List[Any] = []

            conditions = []
            if account_id:
                conditions.append("(account_id = ? OR account_id = 0)")
                params.append(account_id)

            if name and name.lower() not in ("все", "all"):
                clean_name = name.strip("<>").strip()
                conditions.append("(template_name = ? OR template_name = ?)")
                params.extend([clean_name, f"<{clean_name}>"])

            if folder_name or chat_ids:
                sub = []
                if folder_name:
                    sub.append("folder_name = ?")
                    params.append(folder_name)
                if chat_ids:
                    placeholders = ",".join("?" for _ in chat_ids)
                    sub.append(f"chat_id IN ({placeholders})")
                    params.extend(chat_ids)
                conditions.append(f"({' OR '.join(sub)})")
            elif chat_id is not None:
                conditions.append("chat_id = ?")
                params.append(chat_id)

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            cursor.execute(query, params)
            return cursor.rowcount

    def get_chat_broadcasts(self, chat_id: int, account_id: int = 0) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            cursor = conn.cursor()
            if account_id:
                cursor.execute("SELECT * FROM broadcast_tasks WHERE chat_id = ? AND (account_id = ? OR account_id = 0) ORDER BY id DESC", (chat_id, account_id))
            else:
                cursor.execute("SELECT * FROM broadcast_tasks WHERE chat_id = ? ORDER BY id DESC", (chat_id,))
            return [dict(r) for r in cursor.fetchall()]

    def set_chat_rotation(self, chat_id: int, template_names: List[str], account_id: int = 0):
        clean_names = [n.strip("<>").strip() for n in template_names if n.strip("<>").strip()]
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM chat_rotations WHERE chat_id = ? AND (name = '' OR name IS NULL) AND (account_id = ? OR account_id = 0)", (chat_id, account_id))
            row = cursor.fetchone()
            if row:
                cursor.execute("""
                    UPDATE chat_rotations SET template_names = ?, current_index = 0, is_active = 1, account_id = ?
                    WHERE id = ?
                """, (json.dumps(clean_names), account_id, row["id"]))
            else:
                cursor.execute("""
                    INSERT INTO chat_rotations (account_id, chat_id, name, template_names, current_index, is_active)
                    VALUES (?, ?, '', ?, 0, 1)
                """, (account_id, chat_id, json.dumps(clean_names)))

    def set_named_rotation(self, name: str, template_names: List[str], chat_id: Optional[int] = None, account_id: int = 0):
        clean_name = name.strip("<>").strip()
        clean_names = [n.strip("<>").strip() for n in template_names if n.strip("<>").strip()]
        with self._conn() as conn:
            cursor = conn.cursor()
            if account_id:
                cursor.execute("SELECT id FROM chat_rotations WHERE (name = ? OR name = ?) AND (account_id = ? OR account_id = 0)", (clean_name, f"<{clean_name}>", account_id))
            else:
                cursor.execute("SELECT id FROM chat_rotations WHERE name = ? OR name = ?", (clean_name, f"<{clean_name}>"))
            row = cursor.fetchone()
            if row:
                cursor.execute("""
                    UPDATE chat_rotations SET name = ?, template_names = ?, current_index = 0, is_active = 1, account_id = ?, chat_id = ?
                    WHERE id = ?
                """, (clean_name, json.dumps(clean_names), account_id, chat_id, row["id"]))
            else:
                cursor.execute("""
                    INSERT INTO chat_rotations (account_id, chat_id, name, template_names, current_index, is_active)
                    VALUES (?, ?, ?, ?, 0, 1)
                """, (account_id, chat_id, clean_name, json.dumps(clean_names)))

    def delete_named_rotation(self, name: str, account_id: int = 0) -> bool:
        clean_name = name.strip("<>").strip()
        with self._conn() as conn:
            cursor = conn.cursor()
            if account_id:
                cursor.execute("DELETE FROM chat_rotations WHERE (name = ? OR name = ?) AND (account_id = ? OR account_id = 0)", (clean_name, f"<{clean_name}>", account_id))
                deleted = cursor.rowcount > 0
                cursor.execute("DELETE FROM broadcast_tasks WHERE (template_name = ? OR template_name = ?) AND (account_id = ? OR account_id = 0)", (clean_name, f"<{clean_name}>", account_id))
            else:
                cursor.execute("DELETE FROM chat_rotations WHERE name = ? OR name = ?", (clean_name, f"<{clean_name}>"))
                deleted = cursor.rowcount > 0
                cursor.execute("DELETE FROM broadcast_tasks WHERE template_name = ? OR template_name = ?", (clean_name, f"<{clean_name}>"))
            return deleted

    def get_named_rotation(self, name: str, account_id: int = 0) -> Optional[Dict[str, Any]]:
        clean_name = name.strip("<>").strip()
        with self._conn() as conn:
            cursor = conn.cursor()
            if account_id:
                cursor.execute("SELECT * FROM chat_rotations WHERE (name = ? OR name = ?) AND is_active = 1 AND (account_id = ? OR account_id = 0)", (clean_name, f"<{clean_name}>", account_id))
            else:
                cursor.execute("SELECT * FROM chat_rotations WHERE (name = ? OR name = ?) AND is_active = 1", (clean_name, f"<{clean_name}>"))
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "account_id": row["account_id"],
                "chat_id": row["chat_id"],
                "name": row["name"],
                "template_names": json.loads(row["template_names"]) if row["template_names"] else [],
                "current_index": row["current_index"],
                "is_active": row["is_active"]
            }

    def list_named_rotations(self, account_id: int = 0) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            cursor = conn.cursor()
            if account_id:
                cursor.execute("SELECT * FROM chat_rotations WHERE name != '' AND (account_id = ? OR account_id = 0) ORDER BY id ASC", (account_id,))
            else:
                cursor.execute("SELECT * FROM chat_rotations WHERE name != '' ORDER BY id ASC")
            res = []
            for r in cursor.fetchall():
                res.append({
                    "id": r["id"],
                    "account_id": r["account_id"],
                    "chat_id": r["chat_id"],
                    "name": r["name"],
                    "template_names": json.loads(r["template_names"]) if r["template_names"] else [],
                    "current_index": r["current_index"],
                    "is_active": r["is_active"]
                })
            return res

    def delete_all_named_rotations(self, account_id: int = 0):
        with self._conn() as conn:
            cursor = conn.cursor()
            if account_id:
                cursor.execute("DELETE FROM chat_rotations WHERE name != '' AND (account_id = ? OR account_id = 0)", (account_id,))
            else:
                cursor.execute("DELETE FROM chat_rotations WHERE name != ''")

    def delete_chat_rotation(self, chat_id: Optional[int] = None, chat_ids: Optional[List[int]] = None, account_id: int = 0):
        with self._conn() as conn:
            cursor = conn.cursor()
            conditions = []
            params = []
            if account_id:
                conditions.append("(account_id = ? OR account_id = 0)")
                params.append(account_id)
            if chat_ids:
                placeholders = ",".join("?" for _ in chat_ids)
                conditions.append(f"chat_id IN ({placeholders})")
                params.extend(chat_ids)
            elif chat_id is not None:
                conditions.append("chat_id = ?")
                params.append(chat_id)
            where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
            cursor.execute(f"DELETE FROM chat_rotations{where_clause}", params)

    def set_rotation_status(self, chat_id: Optional[int] = None, chat_ids: Optional[List[int]] = None, is_active: int = 1, account_id: int = 0):
        with self._conn() as conn:
            cursor = conn.cursor()
            conditions = []
            params: List[Any] = [is_active]
            if account_id:
                conditions.append("(account_id = ? OR account_id = 0)")
                params.append(account_id)
            if chat_ids:
                placeholders = ",".join("?" for _ in chat_ids)
                conditions.append(f"chat_id IN ({placeholders})")
                params.extend(chat_ids)
            elif chat_id is not None:
                conditions.append("chat_id = ?")
                params.append(chat_id)
            where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ""
            cursor.execute(f"UPDATE chat_rotations SET is_active = ?{where_clause}", params)

    def remove_template_from_rotations(self, template_name: str):
        clean_name = template_name.strip("<>").strip()
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id, template_names FROM chat_rotations")
            for r in cursor.fetchall():
                names = json.loads(r["template_names"]) if r["template_names"] else []
                new_names = [n for n in names if n != clean_name and n != f"<{clean_name}>"]
                if len(new_names) != len(names):
                    if new_names:
                        cursor.execute("UPDATE chat_rotations SET template_names = ?, current_index = 0 WHERE id = ?", (json.dumps(new_names), r["id"]))
                    else:
                        cursor.execute("DELETE FROM chat_rotations WHERE id = ?", (r["id"],))

    def get_chat_rotation(self, chat_id: int, account_id: int = 0) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            cursor = conn.cursor()
            if account_id:
                cursor.execute("SELECT * FROM chat_rotations WHERE chat_id = ? AND (name = '' OR name IS NULL) AND is_active = 1 AND (account_id = ? OR account_id = 0)", (chat_id, account_id))
            else:
                cursor.execute("SELECT * FROM chat_rotations WHERE chat_id = ? AND (name = '' OR name IS NULL) AND is_active = 1", (chat_id,))
            row = cursor.fetchone()
            if not row:
                return None
            return {
                "chat_id": row["chat_id"],
                "name": row["name"],
                "template_names": json.loads(row["template_names"]) if row["template_names"] else [],
                "current_index": row["current_index"],
                "is_active": row["is_active"]
            }

    def get_next_rotation_template(
        self,
        chat_id: Optional[int] = None,
        account_id: int = 0,
        rotation_name: Optional[str] = None,
        member_of_chat_rotation: Optional[str] = None,
    ) -> Optional[str]:
        """
        Next post of a rotation, advancing the position.

        rotation_name: a named rotation; its position is tracked PER CHAT.
        Otherwise the chat's own (unnamed) rotation is used, but only when
        `member_of_chat_rotation` is None or is one of the rotated posts. That
        stops an old chat rotation from hijacking every unrelated broadcast in
        the chat (which looked like a "phantom" post being sent).
        """
        with self._conn() as conn:
            cursor = conn.cursor()
            row = None
            named = False
            if rotation_name:
                clean_rot = rotation_name.strip("<>").strip()
                if account_id:
                    cursor.execute("SELECT * FROM chat_rotations WHERE (name = ? OR name = ?) AND is_active = 1 AND (account_id = ? OR account_id = 0)", (clean_rot, f"<{clean_rot}>", account_id))
                else:
                    cursor.execute("SELECT * FROM chat_rotations WHERE (name = ? OR name = ?) AND is_active = 1", (clean_rot, f"<{clean_rot}>"))
                row = cursor.fetchone()
                named = row is not None

            if not row and chat_id is not None:
                if account_id:
                    cursor.execute("SELECT * FROM chat_rotations WHERE chat_id = ? AND (name = '' OR name IS NULL) AND is_active = 1 AND (account_id = ? OR account_id = 0)", (chat_id, account_id))
                else:
                    cursor.execute("SELECT * FROM chat_rotations WHERE chat_id = ? AND (name = '' OR name IS NULL) AND is_active = 1", (chat_id,))
                row = cursor.fetchone()
                if row is not None and member_of_chat_rotation is not None:
                    names_chk = [n.strip("<>").strip() for n in (json.loads(row["template_names"]) if row["template_names"] else [])]
                    if member_of_chat_rotation.strip("<>").strip() not in names_chk:
                        return None

            if not row:
                return None

            names = json.loads(row["template_names"]) if row["template_names"] else []
            if not names:
                return None

            valid_names = []
            for n in names:
                clean = n.strip("<>").strip()
                cursor.execute("SELECT 1 FROM templates WHERE name = ? OR name = ?", (clean, f"<{clean}>"))
                if cursor.fetchone():
                    valid_names.append(clean)

            if not valid_names:
                return None

            if len(valid_names) != len(names):
                cursor.execute("UPDATE chat_rotations SET template_names = ? WHERE id = ?", (json.dumps(valid_names), row["id"]))

            if named and chat_id is not None:
                prog = cursor.execute(
                    "SELECT current_index FROM rotation_progress WHERE account_id = ? AND rotation_id = ? AND chat_id = ?",
                    (account_id, row["id"], chat_id),
                ).fetchone()
                cur_idx = int(prog["current_index"]) if prog else 0
                idx = cur_idx % len(valid_names)
                cursor.execute(
                    "INSERT INTO rotation_progress (account_id, rotation_id, chat_id, current_index) VALUES (?, ?, ?, ?) "
                    "ON CONFLICT(account_id, rotation_id, chat_id) DO UPDATE SET current_index = excluded.current_index",
                    (account_id, row["id"], chat_id, (idx + 1) % len(valid_names)),
                )
                return valid_names[idx]

            idx = row["current_index"] % len(valid_names)
            template_name = valid_names[idx]
            next_idx = (idx + 1) % len(valid_names)
            cursor.execute("UPDATE chat_rotations SET current_index = ? WHERE id = ?", (next_idx, row["id"]))
            return template_name

    def add_muted_peer(
        self,
        peer_id: int,
        account_id: int = 0,
        peer_key: Optional[int] = None,
        username: str = "",
        display_name: str = "",
        scope: str = "user",
        reason: str = "",
        action: str = "silent",
    ) -> bool:
        """Add a peer to the mute list. Returns True when newly added."""
        if peer_key is None:
            peer_key = peer_id
        clean_username = (username or "").lstrip("@").strip().lower()
        clean_name = (display_name or "").strip()
        clean_action = (action or "silent").strip().lower()
        if clean_action not in MUTE_ACTIONS:
            clean_action = "silent"
        with self._conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR IGNORE INTO muted_peers
                    (account_id, peer_id, peer_key, username, display_name, scope, action, reason, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (account_id, peer_id, peer_key, clean_username, clean_name, scope, clean_action, reason, time.time())
            )
            if cursor.rowcount == 0:
                cursor.execute(
                    "UPDATE muted_peers SET username = COALESCE(NULLIF(?, ''), username), "
                    "display_name = COALESCE(NULLIF(?, ''), display_name), scope = ?, action = ? "
                    "WHERE account_id = ? AND peer_key = ?",
                    (clean_username, clean_name, scope, clean_action, account_id, peer_key)
                )
                return False
            return True

    def remove_muted_peer(self, peer_id: int, account_id: int = 0, scope: str = "user") -> int:
        with self._conn() as conn:
            cursor = conn.cursor()
            if scope == "chat":
                cursor.execute(
                    "DELETE FROM muted_peers WHERE peer_key = ? AND scope = 'chat' AND (account_id = ? OR account_id = 0)",
                    (peer_id, account_id)
                )
            else:
                cursor.execute(
                    "DELETE FROM muted_peers WHERE peer_key = ? AND scope != 'chat' AND (account_id = ? OR account_id = 0)",
                    (peer_id, account_id)
                )
            return cursor.rowcount

    def list_muted_peers(self, account_id: int = 0) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            if account_id:
                rows = conn.execute(
                    "SELECT * FROM muted_peers WHERE account_id = ? OR account_id = 0 ORDER BY created_at DESC",
                    (account_id,)
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM muted_peers ORDER BY created_at DESC").fetchall()
            return [dict(r) for r in rows]

    def find_muted_peer_by_username(self, username: str, account_id: int = 0) -> Optional[Dict[str, Any]]:
        clean = (username or "").lstrip("@").strip().lower()
        if not clean:
            return None
        with self._conn() as conn:
            if account_id:
                row = conn.execute(
                    "SELECT * FROM muted_peers WHERE username = ? AND (account_id = ? OR account_id = 0) LIMIT 1",
                    (clean, account_id)
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT * FROM muted_peers WHERE username = ? LIMIT 1", (clean,)
                ).fetchone()
        return dict(row) if row else None

try:
    db = Database()
except Exception:
    db = None
ACTIVE_COLLECTORS: Dict[Any, Dict[str, Any]] = {}

# Per-process index of muted peers so the hot incoming-message path never
# touches sqlite. Rebuilt from the database on demand and after every change.
# Что делать с сообщением заглушённого человека:
#   silent — пометить прочитанным, чтобы снять пинг и уведомление;
#   delete — прочитать и удалить сообщение;
#   warn   — ответить предупреждением (не чаще раза в 10 минут на человека);
#   ban    — снять право писать в чате (нужны права администратора).
MUTE_ACTIONS = ("silent", "delete", "warn", "ban")
MUTE_ACTION_ALIASES = {
    "тихо": "silent", "silence": "silent", "silent": "silent", "read": "silent",
    "удалить": "delete", "удаляй": "delete", "delete": "delete", "del": "delete",
    "варн": "warn", "предупредить": "warn", "warn": "warn",
    "бан": "ban", "ban": "ban", "кик": "ban", "kick": "ban",
}

_MUTE_CACHE: Dict[int, Set[int]] = {}
_MUTE_CHAT_CACHE: Dict[int, Set[int]] = {}
_MUTE_ACTION_CACHE: Dict[int, Dict[int, str]] = {}
_MUTE_ACTION_CHAT_CACHE: Dict[int, Dict[int, str]] = {}

def _strip_peer_id(value: int) -> int:
    """Telegram user ids arrive as 1000000000000+id; store and match the plain id."""
    try:
        v = int(value)
    except Exception:
        return value
    if v > 1000000000000:
        return v - 1000000000000
    return v

def mute_cache_rebuild(account_id: int = 0):
    """Repopulate the in-memory mute index for an account."""
    if db is None:
        return
    try:
        with db._conn() as conn:
            if account_id:
                rows = conn.execute(
                    "SELECT peer_key, scope, COALESCE(action, 'silent') AS action "
                    "FROM muted_peers WHERE account_id = ? OR account_id = 0",
                    (account_id,)
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT peer_key, scope, COALESCE(action, 'silent') AS action FROM muted_peers"
                ).fetchall()
    except Exception:
        return

    users = _MUTE_CACHE.setdefault(account_id, set())
    chats = _MUTE_CHAT_CACHE.setdefault(account_id, set())
    user_actions = _MUTE_ACTION_CACHE.setdefault(account_id, {})
    chat_actions = _MUTE_ACTION_CHAT_CACHE.setdefault(account_id, {})
    users.clear()
    chats.clear()
    user_actions.clear()
    chat_actions.clear()
    for r in rows:
        try:
            key = int(r["peer_key"])
        except Exception:
            continue
        action = (r["action"] or "silent").strip().lower()
        if action not in MUTE_ACTIONS:
            action = "silent"
        if (r["scope"] or "user") == "chat":
            chats.add(key)
            chat_actions[key] = action
        else:
            users.add(key)
            user_actions[key] = action

def is_peer_muted(account_id: int, peer_id: Any, chat_id: Optional[int] = None) -> bool:
    """True when the sender (or the chat itself) is muted for this account."""
    return mute_action_for(account_id, peer_id, chat_id) is not None

def mute_action_for(account_id: int, peer_id: Any, chat_id: Optional[int] = None) -> Optional[str]:
    """Действие мьюта для отправителя или чата. None — не заглушён."""
    if peer_id is None and chat_id is None:
        return None
    try:
        if peer_id is not None:
            key = _strip_peer_id(peer_id)
            action = _MUTE_ACTION_CACHE.get(account_id, {}).get(key)
            if action:
                return action
        if chat_id is not None:
            action = _MUTE_ACTION_CHAT_CACHE.get(account_id, {}).get(int(chat_id))
            if action:
                return action
    except Exception:
        return None
    return None


def mute_scope_for(account_id: int, peer_id: Any, chat_id: Optional[int] = None) -> Optional[str]:
    """'user' или 'chat' — в каком объёме сработал мьют."""
    try:
        if peer_id is not None and _strip_peer_id(peer_id) in _MUTE_CACHE.get(account_id, set()):
            return "user"
        if chat_id is not None and int(chat_id) in _MUTE_CHAT_CACHE.get(account_id, set()):
            return "chat"
    except Exception:
        pass
    return None

# =============================================================================
# SPAM / ADVERTISING DETECTION
#
# Three layers, evaluated in this order:
#   1. Hard structural evidence (score 100): inline-bot posts, invisible
#      characters, hidden or mass mentions, autoposter watermarks.
#   2. Weighted lexicon + layout scoring. Spam topics (stars, TON, NFT,
#      accounts, "earnings", casino...), sale verbs, contact routing, links and
#      catalogue layout each add points.
#   3. Conversational dampeners. They are capped and never cancel strong
#      commercial evidence, and the "buyer question" veto only applies to
#      messages that carry no sale lexicon, routing or links.
#
# Classification threshold: score >= SPAM_THRESHOLD.
# =============================================================================

SPAM_THRESHOLD = 50

# Usernames (lower-case, without @) of every account running in this process.
# A message that pings us through one of these is a *visible* ping; any other
# @handle in an advertisement is a foreign contact routing signal.
OWN_USERNAMES: Set[str] = set()

# Invisible characters used for ghost pings. ZWJ (\u200d) and variation
# selectors are deliberately NOT here: they are part of normal emoji.
_INVISIBLE_RE = re.compile(r"[\u200b\u200e\u200f\u2060-\u2064\u2066-\u206f\ufeff\u180e\u3164\u115f\u1160\u2800]")

SPAM_SIGNATURES = [
    # Autoposter / userbot watermarks
    r"(?:отправлено|рассылаю|рассылка|рассылается|опубликовано|запощено|размещено|постинг|автопост\w*)\s+(?:с\s+помощью|через|в|с)\s+@?[a-z0-9_]{3,32}\b",
    r"\b(?:sent|posted|broadcasted|powered)\s+(?:via|by|with|through)\s+@?[a-z0-9_]{3,32}\b",
    # Mailing software / services
    r"(?:скрипт|софт|программ\w*|бот)\s+(?:для\s+)?(?:рассыл|спам|автопост|инвайт)\w*\s*[:\-—]?\s*@?\w+",
    r"@[a-z0-9_]*(?:autopost|sender|spambot|postbot|mailer|repost|trafficbot|mailing)[a-z0-9_]*",
    r"заказать\s+(?:рассылку|спам|инвайтинг)",
]
SPAM_PATTERNS = [re.compile(p, re.IGNORECASE) for p in SPAM_SIGNATURES]

COUNTRY_FLAGS = ["🇺🇸", "🇮🇳", "🇮🇩", "🇨🇴", "🇲🇲", "🇧🇩", "🇧🇷", "🇨🇦", "🇲🇽", "🇹🇷", "🇨🇱", "🇿🇦", "🇷🇺",
                 "🇺🇦", "🇰🇿", "🇧🇾", "🇺🇿", "🇬🇧", "🇩🇪", "🇵🇭", "🇻🇳", "🇳🇬", "🇵🇰", "🇪🇬"]

# ---------------------------------------------------------------------------
# Text normalisation. Spammers dodge filters with look-alike Latin letters
# ("зaрaбoтoк"), fancy Unicode fonts ("𝐙𝐚𝐫𝐚𝐛𝐨𝐭𝐨𝐤") and separators between
# letters ("з.в.е.з.д.ы"). Everything is folded back before matching and the
# obfuscation itself is scored, because real people never type like that.
# ---------------------------------------------------------------------------
_HOMOGLYPHS_LAT_TO_CYR = str.maketrans({
    "a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "x": "х", "y": "у",
    "k": "к", "m": "м", "t": "т", "h": "н", "b": "в", "u": "и", "n": "п",
    "3": "з", "0": "о", "6": "б",
})
_FANCY_RANGES = ((0x1D400, 0x1D7FF), (0xFF01, 0xFF5E), (0x24B6, 0x24E9), (0x1F130, 0x1F189))
_CYR_RE = re.compile(r"[а-яё]", re.IGNORECASE)
_LAT_RE = re.compile(r"[a-z]", re.IGNORECASE)
_MASK_RE = re.compile(r"(?:https?://\S+|t\.me/\S+|telegram\.me/\S+|@[a-z0-9_]{3,32})", re.IGNORECASE)
_SPACED_RE = re.compile(r"(?<![\w])(?:[а-яёa-z][\.\-_*•|·~/\\]{1,2}){3,}[а-яёa-z](?![\w])", re.IGNORECASE)
_SPACED_WS_RE = re.compile(r"(?<![\w])(?:[а-яё] ){4,}[а-яё](?![\w])", re.IGNORECASE)
_WORD_RE = re.compile(r"[0-9a-zа-яё]+", re.IGNORECASE)


def normalize_text(text: str) -> Tuple[str, Set[str]]:
    """Lower-cased, de-obfuscated text plus the set of obfuscation tricks seen."""
    import unicodedata
    flags: Set[str] = set()
    if not text:
        return "", flags
    if any(lo <= ord(ch) <= hi for ch in text for lo, hi in _FANCY_RANGES):
        flags.add("fancy_font")
    t = unicodedata.normalize("NFKC", text).lower().replace("ё", "е")

    def _collapse(m: "re.Match") -> str:
        flags.add("spaced_letters")
        return re.sub(r"[\s\.\-_*•|·~/\\]", "", m.group(0))

    t = _SPACED_RE.sub(_collapse, t)
    t = _SPACED_WS_RE.sub(_collapse, t)

    # Fold look-alike Latin letters inside Cyrillic words (links and @handles
    # are left alone, they are legitimately Latin).
    out: List[str] = []
    pos = 0
    for m in _MASK_RE.finditer(t):
        out.append(_fold_words(t[pos:m.start()], flags))
        out.append(m.group(0))
        pos = m.end()
    out.append(_fold_words(t[pos:], flags))
    return "".join(out), flags


def _fold_words(chunk: str, flags: Set[str]) -> str:
    def _fold(m: "re.Match") -> str:
        w = m.group(0)
        cyr = len(_CYR_RE.findall(w))
        if cyr >= 2 and (_LAT_RE.search(w) or re.search(r"[а-я][036]+[а-я]", w)):
            flags.add("mixed_script")
            return w.translate(_HOMOGLYPHS_LAT_TO_CYR)
        return w
    return _WORD_RE.sub(_fold, chunk)


# (pattern, points, label). Topics that are almost only ever spam when a
# stranger pings you with them in a PR / ad-exchange chat.
_SPAM_LEXICON = [
    (r"\bзвезд\w*|\bstars?\b|\bzvezd\w*", 20, "stars"),
    (r"\bтон\w{0,2}\b|\bton\b|\busdt\b|\bbtc\b|\beth\b|крипт\w*|\bp2p\b|обменник\w*|биткоин\w*|\bbitcoin\w*|"
     r"\bcrypto\w*|\bairdrop\w*|\bтокен\w*|\btokens?\b", 20, "crypto"),
    (r"\bнфт\b|\bnft\w*|подар(?:ок|ки|ков|ками|ке|очки)\b|\bфлор\w*|\bgifts?\b", 20, "nft_gifts"),
    (r"\bголд\w*|\bgold\b|\bюс\b|\bробукс\w*|\bгемы\b|\bдонат\w*", 15, "game_currency"),
    (r"аккаунт\w*|\bакк(?:и|а|ов)?\b|\bсессии\b|\btdata\b|номер(?:а|ов)\s+(?:стран|рф|сша|для)|смен\w*\s+номер\w*|"
     r"виртуальн\w*\s+номер\w*|\bпремиум\w*|\bpremium\b|\bпремк\w*|\bбуст(?:ы|ов|а|ами)?\b|\bboosts?\b|"
     r"\bюз(?:ы|ов|ер\w*|ернейм\w*)?\b|\busernames?\b", 20, "tg_goods"),
    (r"заработ\w*|зарабат\w*|\bдоход\w*|пассивн\w*|без\s+вложени\w*|вложени\w*\s+от|подработк\w*|"
     r"удаленн\w*\s+работ\w*|работ\w*\s+(?:удаленно|на\s+дому|с\s+телефона|онлайн|для\s+(?:подростков|школьников|студентов|всех))|"
     r"\bвакансии\b|\bвакансия\b|\bтребу(?:ю|е)тся\b|\bнужны\s+(?:люди|работники|сотрудники|ребята|девушки)|"
     r"\bнужен\s+(?:человек|работник|сотрудник)|ищ(?:у|ем)\s+(?:людей|сотрудник\w*|работник\w*|партнер\w*|админ\w*|менеджер\w*)|"
     r"набор\s+в\s+команду|в\s+(?:нашу|свою)\s+команду|\bкурьер\w*|оплата\s+(?:каждый\s+день|ежедневн\w*|сразу|от\s+\d)|"
     r"высок\w*\s+оплат\w*|легк\w*\s+(?:деньг\w*|работ\w*|заработ\w*)|\bпрофит\w*|инвест\w*|\bearn\w*|\bprofit\w*|"
     r"\binvest\w*|\bincome\b|\bdaily\b|\bzarab[oa]t\w*|\bdohod\w*|\bсхем[ауы]\b|\bарбитраж\w*|\$\s*в\s+(?:день|неделю)|\bв\s+(?:день|сутки)\s+от\b", 35, "earnings"),
    (r"казино|\bcasino\b|\bkazino\b|\bказик\w*|гемблинг|\bazart\b|\b1win\b|\bstake\b|ставк[иа]\b|фриспин\w*|"
     r"\bбонус\w*\s+(?:за|при)\s+регистрац\w*|промокод\w*|\bслоты\b|\bbet\b|\bбеттинг\w*", 35, "gambling"),
    (r"\bинтим\w*|\b18\s*\+|\bэро\b|\bслив\w*|\bприват\w*\s+канал|\bonlyfans\b|\bнюдс\w*|\bnudes?\b", 35, "adult"),
    (r"\bклик(?:и|ов)\b|\bпросмотр(?:ы|ов)\b\s+(?:на|для)|\bнакрутк\w*|\bподписчик(?:и|ов)\b\s+(?:на|в|для)|\bреакци(?:и|й)\b\s+на", 20, "smm"),
    (r"\bвербовк\w*|\bдроп\w*\b|\bобнал\w*|\bкарты?\s+(?:физ|юр)", 30, "fraud"),
    (r"выиграл\w*|\bприз\w*|розыгрыш\w*|халяв\w*|\bраздач\w*|\bраздаю\b|бесплатн\w*|\bgiveaway\w*|\bfree\b|\bбонус\w*", 25, "prize"),
    (r"пиар\w*\s+в\s+\d+|\b\d+\s+чат(?:ах|ов|а)\b|прода(?:м|ю)\s+рекламу\s+в\s+(?:чат|канал|\d)|реклам\w*\s+в\s+(?:моих|наших|\d+)\s+(?:чат|канал)\w*|"
     r"взаимн\w*\s+пиар\w*|\bвп\b|\bвзаимк\w*|рассылк\w*\s+по\s+(?:чатам|лс|базе)|\bинвайт\w*", 25, "ad_services"),
    (r"делаю\s+(?:ботов|бота|сайт\w*|дизайн\w*|аватар\w*|аву|логотип\w*|монтаж\w*|рекламу)|на\s+заказ\b|\bуслуг\w*|"
     r"помогу\s+с\b|разработ\w*\s+(?:бот|сайт)\w*", 20, "services"),
    (r"\b(?:мой|мою|моего|мои|наш|нашу|нашего|наши)\s+(?:канал\w*|чат\w*|бот\w*|магазин\w*|проект\w*|групп\w*|сообществ\w*|паблик\w*)|"
     r"\bподпис(?:ывайся|ывайтесь|ись|итесь)\b|\bзаход(?:и|ите)\b|\bвступ(?:ай|айте)\b|\bзалета(?:й|йте)\b|"
     r"\bjoin\s+(?:my|our|us)\b|\bsubscribe\b", 25, "self_promo"),
]
_SPAM_LEXICON = [(re.compile(p, re.IGNORECASE), pts, label) for p, pts, label in _SPAM_LEXICON]
_STRONG_TOPICS = {"earnings", "gambling", "adult", "fraud"}
_PROMO_RE = re.compile(
    r"\b(?:бонус\w*|промокод\w*|акци[яи]|скидк\w*|бесплатн\w*|халяв\w*|розыгрыш\w*|раздач\w*|выигр\w*|вывод\w*|оптом|опт\b)",
    re.IGNORECASE,
)

_SALE_VERB_RE = re.compile(
    r"\b(?:продам|продаю|продается|продаем|продажа|скупаю|скупка|скупаем|куплю|покупаю|обменяю|обмен|"
    r"сдам|сдаю|предлагаю|предлагаем|оказываю|оказываем|отдам|отдаю|дарю|раздаю|раздача|делаю|помогу|ищу\s+менеджер\w*|"
    r"ищ(?:у|ем)\s+(?:партнер\w*|админ\w*|людей|сотрудник\w*|работник\w*)|требу(?:ю|е)тся|нужны\s+люди|нужен\s+человек|"
    r"переход(?:и|ите)|глян(?:ь|ьте)\s+(?:мой|мою|наш|нашу|канал)|загляни\w*|обращайтесь|"
    r"менеджер\w*\s+по\s+продажам|дешевле|дешево|выгодно|недорого|по\s+курсу|ниже\s+рынка|"
    r"купить\s+можно|можно\s+купить\s+за|в\s+наличии|цена\s+за|прайс\s*:|оплата\s+(?:в|через|картой|криптой)\s|"
    r"sell\w*|buy\w*|cheap\w*)\b",
    re.IGNORECASE,
)
_SELLER_ASK_RE = re.compile(
    r"\b(?:купишь|купите|покупайте|покупай|закажи|заказывай|нужн[ыао]\s+(?:звезд|акк|подписчик|просмотр|клик|реклам|бусты|премиум)|"
    r"хочешь\s+(?:заработать|зарабатывать|звезд|бесплатн|подарок|подарки|премиум)|хотите\s+(?:заработать|зарабатывать))",
    re.IGNORECASE,
)
_ROUTING_RE = re.compile(
    r"(?:пиш(?:и|ите)|писать|связь|обращаться|отпиш(?:и|ите)|стучи(?:те)?|жду|вопросы|заказ|менеджер\w*|contact|"
    r"по\s+поводу\s+\w+|для\s+заказа|купить)\s*(?:в\s+лс|в\s+личку|в\s+пм|сюда|тут|мне)?\s*[:\-—–]?\s*@\w+",
    re.IGNORECASE,
)
_EMOJI_ROUTING_RE = re.compile(r"(?:📩|👉|📲|💬|✍️|✍|✉️|☎️|📞|➡️|⬇️)\s*(?:в\s+лс|пишите|связь|обращаться)?\s*@\w+", re.IGNORECASE)
_DM_CTA_RE = re.compile(
    r"(?:\bв\s+лс\b|\bв\s+личк\w*|\bв\s+пм\b|\bлс\s+открыт\w*|\bлс\b|\bпиш(?:и|ите)\b|\bнапиш(?:и|ите)\b|\bотпиш(?:и|ите)\w*|"
    r"\bстуч(?:и|ите)\b|подробн\w*|ссылка\s+в\s+(?:профиле|био|описании)|\bв\s+профил\w*|\bв\s+био\b|\bпо\s+ссылке\b|"
    r"жми\b|переходи\w*|\bтык\b|\bdm\b|\bpm\b|\bwrite\s+me\b|\bcontact\b|\bclaim\b)",
    re.IGNORECASE,
)
_CATALOG_BULLET_RE = re.compile(r"^(?:[·•▪️▫️◾◽\-\—\*✅✔️☑️🔹🔸🔵🟢❗️❕]|\d+[\.\)\-\—]|[1-9]️⃣|[①-⑩])\s*")
_BANNER_RE = re.compile(r"^(?:🔥|⚡️|⚡|📢|📣|💎|💰|💸|💵|🚀|🚨|❗️|‼️|⚠️|⭐️|⭐|🌟|💥|🎯|👉|📩|📲|💬|🎁|🤑|📈|🆕|🔝)")
_PRICE_RE = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:₽|руб\w*|р\b|\$|usd\w*|€|грн|тг|⭐|🌟|звезд\w*|ton\b|тон\b)|\$\s*\d+",
    re.IGNORECASE,
)
_LINK_RE = re.compile(r"t\.me/(?:\+|joinchat/|[a-z0-9_]{5,})|telegram\.me/|https?://\S+", re.IGNORECASE)
_PRIVATE_LINK_RE = re.compile(r"t\.me/(?:\+|joinchat/)|t\.me/[a-z0-9_]*bot\b|\?start=", re.IGNORECASE)
_HANDLE_RE = re.compile(r"(?<![\w@])@([a-zA-Z0-9_]{4,32})")
_CONVO_RE = re.compile(
    r"\b(?:я|мне|меня|мы|нас|ты|тебе|тебя|твой|твоем|привет|ку|здравствуйте|спасибо|спс|лол|хах\w*|хд|"
    r"ладно|норм|почему|зачем|окей|ок|понял\w*|сорри|извини\w*|ага|угу|да|нет|тоже)\b",
    re.IGNORECASE,
)

BUYER_QUESTION_TRIGGERS = [
    r"\bпочем\b", r"\bцена\b", r"\bцену\b", r"\bактуально\b",
    r"\bсвободн\w*\b", r"\bстат[уа]\b", r"\bстатистик[ау]\b", r"\bохват\w*\b",
    r"\bчекни\s+лс\b", r"\bответь(?:те)?\s+в\s+лс\b", r"\bкуплю\s+рекламу\b", r"\bхочу\s+купить\b",
    r"\bпродашь\b", r"\bпродаешь\b", r"\bпродаете\b", r"\bсколько\s+стоит\b",
    r"\bможно\s+(?:купить|взять|разместить|заказать)\b", r"\bместо\s+есть\b", r"\bесть\s+место\b",
    r"\bзакреп\w*\b", r"\bслот\w*\b",
]
BUYER_PATTERNS = [re.compile(p, re.IGNORECASE) for p in BUYER_QUESTION_TRIGGERS]
_BUYER_PURCHASE_RE = re.compile(r"\b(?:куплю|купить|покупаю|возьму)\s+(?:у\s+тебя\s+|у\s+вас\s+)?(?:рекламу|пост\w*|закреп\w*|место|слот\w*|размещени\w*)", re.IGNORECASE)

GATEKEEPER_TRIGGERS = [
    r"чтобы\s+(?:писать|отправлять\s+сообщения)\s+в\s+(?:чат|группу)",
    r"необходимо\s+подписаться",
    r"нужно\s+подписаться",
    r"подпишитесь\s+на\s+(?:канал|наш)",
    r"обязательная\s+подписка",
    r"для\s+доступа\s+к\s+чату",
    r"пройдите\s+капчу",
    r"подтвердите,?\s*что\s+вы\s+не\s+(?:бот|робот)",
    r"you\s+must\s+(?:join|subscribe)",
]
GATEKEEPER_PATTERNS = [re.compile(p, re.IGNORECASE) for p in GATEKEEPER_TRIGGERS]

VERIFY_BUTTON_TEXTS = [
    "подписался", "я подписался", "проверить", "готово", "подтвердить",
    "вступил", "продолжить", "я не бот", "check", "done", "verify", "i subscribed", "i'm not a bot",
]


def _utf16_slice(text: str, offset: int, length: int) -> str:
    try:
        encoded = text.encode("utf-16-le")
        return encoded[offset * 2 : (offset + length) * 2].decode("utf-16-le", errors="ignore")
    except Exception:
        return text[offset : offset + length]


def _entity_evidence(text: str, message: Any) -> Optional[Tuple[str, str]]:
    """Hidden or mass mentions carried by message entities."""
    entities = getattr(message, "entities", None) if message is not None else None
    if not entities:
        return None
    from telethon.tl.types import (
        MessageEntityMentionName,
        InputMessageEntityMentionName,
        MessageEntityMention,
        MessageEntityTextUrl,
    )
    user_mentions = 0
    total_mentions = 0
    hidden = False
    for ent in entities:
        is_user_ref = isinstance(ent, (MessageEntityMentionName, InputMessageEntityMentionName)) or (
            isinstance(ent, MessageEntityTextUrl) and "tg://user?id=" in (ent.url or "").lower()
        )
        if is_user_ref:
            user_mentions += 1
            total_mentions += 1
            ent_text = _utf16_slice(text, ent.offset, ent.length)
            if not re.search(r"\w", ent_text):
                hidden = True
        elif isinstance(ent, MessageEntityMention):
            total_mentions += 1
    if hidden:
        return "hidden_ghost_mention", "mention_under_emoji_or_space"
    if user_mentions >= 2 or total_mentions >= 4:
        return "mass_entity_tagging", f"mentions_{total_mentions}"
    return None


def _hard_evidence(text: str, message: Any = None) -> Optional[Tuple[str, str]]:
    if message is not None and getattr(message, "via_bot_id", None):
        return "sent_via_inline_bot", "inline_bot"
    if _INVISIBLE_RE.search(text):
        return "invisible_ghost_ping", "zero_width_ghost_chars"
    ev = _entity_evidence(text, message)
    if ev:
        return ev
    clean = text.lower()
    for pat in SPAM_PATTERNS:
        if pat.search(clean):
            return pat.pattern, "signature_match"
    return None


def _strip_mentions(text: str) -> str:
    return re.sub(r"@[A-Za-z0-9_]{3,32}", " ", text or "").strip()


def _advertising_metadata(message: Any) -> str:
    """Visible button labels and hidden link targets; never fetch remote content."""
    if message is None:
        return ""
    values = []
    for ent in (getattr(message, "entities", None) or []):
        url = getattr(ent, "url", None)
        if isinstance(url, str):
            values.append(url[:2048])
    markup = getattr(message, "reply_markup", None)
    for row in (getattr(markup, "rows", None) or [])[:20]:
        for button in (getattr(row, "buttons", None) or [])[:10]:
            for obj, field in ((button, "text"), (button, "url"),
                               (getattr(button, "type", None), "url")):
                value = getattr(obj, field, None)
                if isinstance(value, str):
                    values.append(value[:2048])
    return "\n".join(dict.fromkeys(values))[:16000]


# Require prices attached to catalogue rows, not arbitrary dates/phone numbers.
_CATALOG_PRICE_ROW_RE = re.compile(
    r"(?:\(\+?\d{1,4}\)|\b(?:19|20)\d{2}\b|[а-яa-z]{3,})"
    r"[^\n]{0,60}?\s[-–—:=]\s*\d+(?:[.,]\d+)?\s*(?:[⭐🌟]|звезд\w*|₽|руб\w*|ton\b|\$|€)?\s*$",
    re.IGNORECASE,
)
_SELLER_HEADER_RE = re.compile(
    r"\b(?:в\s+продаже|прайс(?:[- ]лист)?|актуальн\w*\s+(?:цен\w*|прайс\w*)|наличие|каталог|price\s*list)\b",
    re.IGNORECASE,
)
_CONTACT_SECTION_RE = re.compile(
    r"\b(?:купить|заказать|отзывы|обратная\s+связь|для\s+заказа|контакты|reviews|order|contact)\b",
    re.IGNORECASE,
)


def calculate_spam_score(text: str, message: Any = None, ping_kind: Optional[str] = None) -> Tuple[int, str, List[str]]:
    """
    Returns (score, primary_trigger, matched_factors). Spam when score >= 50.

    ping_kind describes how the message reached us: "reply" (reply to our
    message), "username" (our @handle typed in the text), "name" (a regular
    mention of our name), "stealth" (Telegram flagged it as a mention but it
    is neither a reply nor a visible mention: a hidden tag) or None.
    """
    if ping_kind == "stealth":
        return 100, "stealth_ping", ["hidden_mention_without_username_or_reply"]
    metadata = _advertising_metadata(message)
    if not text and not metadata:
        if message is not None and getattr(message, "via_bot_id", None):
            return 100, "sent_via_inline_bot", ["inline_bot"]
        return 0, "", []

    hard = _hard_evidence(text, message)
    if hard:
        return 100, hard[0], [hard[1]]

    clean, obf = normalize_text((text or "") + ("\n" + metadata if metadata else ""))
    lines = [l.strip() for l in (text or "").splitlines() if l.strip()]
    factors: List[str] = []
    score = 0

    def add(points: int, label: str):
        nonlocal score
        score += points
        factors.append(f"{label}(+{points})")

    # --- obfuscation: people do not type like this ---------------------------
    if "mixed_script" in obf:
        add(30, "lookalike_letters")
    if "fancy_font" in obf:
        add(25, "fancy_unicode_font")
    if "spaced_letters" in obf:
        add(25, "spaced_out_letters")

    # --- commercial lexicon -------------------------------------------------
    topic_points = 0
    strong_topic = False
    multi_hit_topic = False
    topics: Set[str] = set()
    for pat, pts, label in _SPAM_LEXICON:
        hits = {m.group(0) for m in pat.finditer(clean)}
        if not hits:
            continue
        topics.add(label)
        if label in _STRONG_TOPICS:
            strong_topic = True
        extra = min(10 * (len(hits) - 1), 20)
        if extra:
            multi_hit_topic = True
        topic_points += pts + extra
        factors.append(f"topic_{label}(+{pts + extra})")
    topic_points = min(topic_points, 60)
    score += topic_points
    if len(topics) >= 2:
        multi_hit_topic = True

    buyer_purchase = bool(_BUYER_PURCHASE_RE.search(clean))
    has_sale_verb = bool(_SALE_VERB_RE.search(_BUYER_PURCHASE_RE.sub(" ", clean)))
    has_seller_ask = bool(_SELLER_ASK_RE.search(clean))
    if has_sale_verb:
        add(25, "sale_verb")
    if has_seller_ask:
        add(55, "seller_ask")

    # --- contact routing ----------------------------------------------------
    own = {u.lower() for u in OWN_USERNAMES}
    foreign_handles = [h for h in _HANDLE_RE.findall(text) if h.lower() not in own]
    has_emoji_routing = bool(_EMOJI_ROUTING_RE.search(clean))
    has_text_routing = bool(_ROUTING_RE.search(clean)) and bool(foreign_handles)
    has_dm_cta = bool(_DM_CTA_RE.search(clean))
    commercial_core = bool(topic_points or has_sale_verb or has_seller_ask)
    if has_emoji_routing:
        add(30, "emoji_contact_routing")
    elif has_text_routing:
        add(25, "text_seller_routing")
    if has_dm_cta and commercial_core:
        add(20, "dm_call_to_action")

    links = _LINK_RE.findall(clean)
    if links:
        add(25 if _PRIVATE_LINK_RE.search(clean) else 10, "promo_links")
    if foreign_handles and commercial_core and not has_text_routing and not has_emoji_routing:
        add(15, "foreign_handle")
    if len(foreign_handles) >= 2:
        add(15, f"multiple_usernames_{len(foreign_handles)}")

    catalogue_rows = sum(bool(_CATALOG_PRICE_ROW_RE.search(normalize_text(line)[0])) for line in lines)
    seller_header = bool(_SELLER_HEADER_RE.search(clean))
    contact_section = bool(_CONTACT_SECTION_RE.search(clean)) and bool(links or foreign_handles)
    # Flags and a long message alone are not a shop: travel lists stay readable.
    catalogue_offer = catalogue_rows >= 2 and (has_sale_verb or seller_header or contact_section)
    if catalogue_offer:
        add(60, "seller_price_catalogue")
    if contact_section and (commercial_core or catalogue_offer or seller_header):
        add(25, "seller_contact_section")
    if re.search(r"переслано\s+через\s+\w+", clean) and (commercial_core or catalogue_offer):
        add(15, "commercial_forwarder")

    prices = _PRICE_RE.findall(clean)
    if len(prices) >= 2:
        add(20, f"price_list_{len(prices)}")
    elif prices and (topic_points or has_sale_verb):
        add(10, "price")

    flag_count = sum(1 for f in COUNTRY_FLAGS if f in text)
    if flag_count >= 3:
        add(35, f"country_flags_{flag_count}")

    # --- layout -------------------------------------------------------------
    banner = sum(1 for l in lines if _BANNER_RE.match(l))
    if banner:
        add(15 if banner == 1 else 25, "banner_emojis")
    bullets = sum(1 for l in lines if _CATALOG_BULLET_RE.match(l))
    if bullets:
        add(10 if bullets == 1 else 25, "bullet_points")
    if len(lines) >= 4:
        add(15, "multiblock_layout")
    if re.search(r"\b(?:канал[ыа]?|чат[ыа]?|групп[уыа]|сетк[уи]|баз[уы])\b", clean) and has_sale_verb:
        add(15, "asset_specifiers")

    commercial = bool(commercial_core or has_emoji_routing or has_text_routing)
    has_promo = bool(_PROMO_RE.search(clean))
    combo = bool(topic_points) and (
        has_sale_verb or has_seller_ask or has_emoji_routing or has_text_routing or has_dm_cta
        or bool(links) or bool(prices) or has_promo or bool(foreign_handles) or bool(obf)
        or (strong_topic and multi_hit_topic) or len(topics) >= 2
    )
    if combo:
        add(20, "commercial_combo")
    elif has_sale_verb and (has_dm_cta or links or foreign_handles):
        add(15, "offer_with_contact")

    # --- conversational dampeners (capped, never cancel commerce) ----------
    damp = 0
    if "?" in clean and not (has_emoji_routing or has_text_routing):
        damp += 25
        factors.append("question_mark(-25)")
    if len(clean) < 70 and len(lines) == 1:
        damp += 25
        factors.append("short_single_line(-25)")
    if _CONVO_RE.search(clean) and not (has_emoji_routing or bullets):
        damp += 15
        factors.append("conversational_markers(-15)")
    if has_seller_ask or combo or obf or catalogue_offer:
        cap = 0
    elif strong_topic:
        cap = 10
    elif commercial and score >= 70:
        cap = 20
    else:
        cap = 40
    score = max(0, score - min(damp, cap))

    if not metadata and not catalogue_offer:
        strong_commercial = bool(
            has_seller_ask or has_text_routing or has_emoji_routing or links
            or (foreign_handles and (topic_points or has_sale_verb or has_dm_cta))
        )
        if not strong_commercial and is_genuine_buyer_question(text):
            score = 0
            factors.append("genuine_buyer_question(veto)")

    return score, (factors[0] if factors else "low_score"), factors


def is_spam_message(text: str, message: Any = None, ping_kind: Optional[str] = None) -> Tuple[bool, str]:
    score, trigger, _ = calculate_spam_score(text or "", message, ping_kind=ping_kind)
    if score >= SPAM_THRESHOLD:
        return True, f"{trigger} (score={score})"
    return False, ""


_BUYER_BLOCKING_TOPICS = {"earnings", "gambling", "adult", "fraud", "prize", "self_promo", "services", "crypto", "nft_gifts", "tg_goods"}


def is_genuine_buyer_question(text: str) -> bool:
    """A short question from someone who wants to BUY from us. Never spam."""
    if not text:
        return False
    if _INVISIBLE_RE.search(text):
        return False
    clean, obf = normalize_text(text)
    clean = clean.strip()
    if len(clean) >= 220 or obf:
        return False
    if _ROUTING_RE.search(clean) or _EMOJI_ROUTING_RE.search(clean):
        return False
    own = {u.lower() for u in OWN_USERNAMES}
    if any(h.lower() not in own for h in _HANDLE_RE.findall(text)):
        return False
    if _LINK_RE.search(clean) or re.search(r"[1-9]️⃣|[①-⑩]", clean):
        return False
    if sum(1 for f in COUNTRY_FLAGS if f in text) >= 2:
        return False
    if _SELLER_ASK_RE.search(clean):
        return False
    buyer_purchase = bool(_BUYER_PURCHASE_RE.search(clean))
    if _SALE_VERB_RE.search(_BUYER_PURCHASE_RE.sub(" ", clean)):
        return False
    hit_topics = {label for pat, _p, label in _SPAM_LEXICON if pat.search(clean)}
    if len(hit_topics) >= 2:
        return False
    if hit_topics & _BUYER_BLOCKING_TOPICS and not buyer_purchase:
        # "сколько звезд за пост?" is a buyer; "сколько звезд хочешь бесплатно?" is not.
        if hit_topics - {"stars", "crypto", "tg_goods", "nft_gifts"}:
            return False
    has_q = "?" in clean
    has_trigger = buyer_purchase or any(p.search(clean) for p in BUYER_PATTERNS)
    if has_trigger and (has_q or len(clean) < 120):
        return True
    # A bare short question about ads/our channel ("а сколько?", "есть место?")
    if has_q and len(clean) < 120 and not hit_topics:
        return bool(re.search(r"\b(?:реклам\w*|пост\w*|канал\w*|чат\w*|размещ\w*|закреп\w*|стоит|цен\w*)\b", clean))
    return False


def is_hard_spam(text: str, message: Any = None, ping_kind: Optional[str] = None) -> Tuple[bool, str]:
    """Structural evidence a human never produces by accident."""
    if ping_kind == "stealth":
        return True, "stealth_ping"
    if not text and not (message is not None and getattr(message, "via_bot_id", None)):
        return False, ""
    hard = _hard_evidence(text or "", message)
    return (True, hard[0]) if hard else (False, "")


def _is_visual_media(message: Any) -> bool:
    media = getattr(message, "media", None) if message is not None else None
    if media is None:
        return False
    name = type(media).__name__
    return name in ("MessageMediaPhoto", "MessageMediaDocument")


def should_auto_read(text: str, message: Any = None, is_ping: Optional[bool] = None, ping_kind: Optional[str] = None) -> bool:
    """
    Auto-clear gate.

    Hard structural spam is cleared. For messages without a ping, require
    high-confidence sale + contact evidence or a seller price catalogue.
    Regular buyer questions are preserved; history clearing has a separate
    unread-message safety check.
    """
    hard, _ = is_hard_spam(text, message, ping_kind=ping_kind)
    if hard:
        return True
    metadata = _advertising_metadata(message)
    if not metadata and is_genuine_buyer_question(text):
        return False
    if is_ping is False:
        # Ordinary group notifications need no mention. Use a stricter gate:
        # score alone (flags/layout/obfuscation) must not silence conversation.
        score, _trigger, factors = calculate_spam_score(text, message)
        labels = {f.split("(", 1)[0] for f in factors}
        catalogue = "seller_price_catalogue" in labels
        sale = bool(labels & {"sale_verb", "seller_ask"})
        contact = bool(labels & {"seller_contact_section", "text_seller_routing",
                                  "emoji_contact_routing", "dm_call_to_action",
                                  "foreign_handle", "promo_links"})
        return score >= 80 and (catalogue or (contact and (sale or "commercial_combo" in labels)))
    # A stranger tagging us on a picture/video with (almost) no text and not as
    # a reply to our post: the ad is in the image. Real buyers ask in words.
    if ping_kind == "name":
        # Strangers addressing us by name ("Имя, привет! ...") with any
        # commercial content: bots do this, buyers write "@user почем?".
        score, _t, _f = calculate_spam_score(text, message, ping_kind=ping_kind)
        if score >= SPAM_THRESHOLD - 15:
            return True
    if ping_kind in ("reply", "username", "name") and _is_visual_media(message):
        rest = re.sub(r"[\W_]+", "", _strip_mentions(text or ""))
        if len(rest) < 12:
            return True
        score, _t, _f = calculate_spam_score(text, message, ping_kind=ping_kind)
        return score >= SPAM_THRESHOLD - 15
    # Любой пинг (ответ на наш пост, @username, имя, скрытый тег) с коммерческим
    # следом гасим: настоящий покупатель проходит выше через veto-проверку.
    score, _trigger, _factors = calculate_spam_score(text, message, ping_kind=ping_kind)
    if is_ping and score >= SPAM_THRESHOLD - 15:
        return True
    return is_spam_message(text, message, ping_kind=ping_kind)[0]

def is_gatekeeper_text(text: str) -> bool:
    if not text:
        return False
    clean = text.lower()
    return any(p.search(clean) for p in GATEKEEPER_PATTERNS)

def extract_channel_links(text: str) -> List[str]:
    if not text:
        return []
    targets = set()
    for m in re.findall(r"(?:https?://)?(?:t\.me|telegram\.me)/(?:joinchat/|\+)?([a-zA-Z0-9_+-]+)", text):
        clean = m.strip("/")
        if clean:
            targets.add(clean)
    for m in re.findall(r"@([a-zA-Z0-9_]{4,32})", text):
        targets.add(m)
    return list(targets)

def is_verify_button(text: str) -> bool:
    if not text:
        return False
    clean = text.lower().strip()
    return any(v in clean for v in VERIFY_BUTTON_TEXTS)

def serialize_entities(entities: Optional[List[Any]]) -> List[str]:
    if not entities:
        return []
    return [bytes(e).hex() for e in entities]

def deserialize_entities(hex_list: Optional[List[str]]) -> List[Any]:
    if not hex_list:
        return []
    entities = []
    for h in hex_list:
        try:
            reader = BinaryReader(bytes.fromhex(h))
            entities.append(reader.tgread_object())
        except Exception as e:
            # Незнакомый тип (новая фича Telegram, которой нет в этой версии
            # Telethon) не должен молча ломать всё остальное форматирование.
            log_info(f"[ENTITY] Сущность пропущена: {type(e).__name__}")
            continue
    return entities


def _rebase_entities(entities: Optional[List[Any]], prefix_len: int, text_len: int) -> List[str]:
    """Пересчитать смещения сущностей на новый текст, обрезая выход за границы."""
    out: List[str] = []
    for e in entities or []:
        try:
            off = int(getattr(e, "offset", 0)) - int(prefix_len)
            length = int(getattr(e, "length", 0))
            if off < 0:
                length += off
                off = 0
            if length <= 0 or off >= text_len:
                continue
            if off + length > text_len:
                length = text_len - off
            ne = copy.copy(e)
            ne.offset = off
            ne.length = length
            out.append(bytes(ne).hex())
        except Exception:
            continue
    return out

def extract_payload_and_entities(message: Any, raw_text: str, folder_name: str = "") -> Tuple[str, List[str]]:
    lines = raw_text.splitlines()
    if len(lines) > 1:
        first_nl = raw_text.find("\n")
        raw_prefix = raw_text[:first_nl + 1]
        raw_payload = raw_text[first_nl + 1:]
        stripped = raw_payload.strip()
        if not stripped:
            return "", []

        leading_ws = raw_payload[:len(raw_payload) - len(raw_payload.lstrip())]
        m = re.search(r'^"(.*)"$', stripped, re.DOTALL)
        if m:
            text = m.group(1)
            prefix_before_text = raw_prefix + leading_ws + '"'
        else:
            text = stripped
            prefix_before_text = raw_prefix + leading_ws

        prefix_len = len(prefix_before_text.encode("utf-16le")) // 2
        text_len = len(text.encode("utf-16le")) // 2
        out_entities = _rebase_entities(getattr(message, "entities", None), prefix_len, text_len)
        return text, out_entities
    else:
        quoted = re.findall(r'"([^"]+)"', raw_text)
        text = ""
        if quoted:
            if folder_name and len(quoted) > 1:
                text = quoted[1] if quoted[0] == folder_name else quoted[0]
            elif not folder_name:
                text = quoted[0]

        if not text:
            return "", []

        quote_target = f'"{text}"'
        pos = raw_text.find(quote_target)
        if pos == -1:
            pos = raw_text.find(text)
            prefix = raw_text[:pos]
        else:
            prefix = raw_text[:pos + 1]

        prefix_len = len(prefix.encode("utf-16le")) // 2
        text_len = len(text.encode("utf-16le")) // 2
        out_entities = _rebase_entities(getattr(message, "entities", None), prefix_len, text_len)
        return text, out_entities

def _preview_disabled(message: Any, text: str) -> int:
    """1, если у исходного поста превью ссылки было выключено.

    Telegram кладёт включённое превью в message.media как MessageMediaWebPage.
    Ссылка есть, а веб-страницы в media нет — значит превью отключили руками,
    и при рассылке его нужно сохранить отключённым.
    """
    if not text or not _LINK_RE.search(text):
        return 0
    from telethon.tl.types import MessageMediaWebPage
    return 0 if isinstance(getattr(message, "media", None), MessageMediaWebPage) else 1


def _strip_trailing_buttons(text: str) -> Tuple[str, List[Any]]:
    """Вырезать хвост с инлайн-кнопками из текста поста."""
    try:
        return extract_buttons_block(text)
    except Exception as e:
        log_error(f"[BTN] Кнопки не разобраны: {e}")
        return text, []


async def fetch_album(client: TelegramClient, message: Any) -> List[Any]:
    """All parts of the album `message` belongs to, sorted, without duplicates."""
    gid = getattr(message, "grouped_id", None)
    if not gid:
        return [message]
    around = list(range(max(1, message.id - 10), message.id + 11))
    try:
        found = await client.get_messages(message.chat_id, ids=around)
    except Exception:
        found = []
    album = {m.id: m for m in (found or []) if m is not None and getattr(m, "grouped_id", None) == gid}
    album.setdefault(message.id, message)
    return [album[k] for k in sorted(album)][:10]


def _is_downloadable_media(message: Any) -> bool:
    """
    Real attachments only. A link preview (MessageMediaWebPage) is NOT one:
    Telethon happily downloads the preview picture, so a text post with a link
    used to be re-sent as a photo + caption (or as a separate picture).
    """
    from telethon.tl.types import MessageMediaPhoto, MessageMediaDocument
    media = getattr(message, "media", None)
    return isinstance(media, (MessageMediaPhoto, MessageMediaDocument))


async def save_media_from_message(
    client: TelegramClient,
    message: Any,
    template_name: str,
    item_index: int = 0,
    clear_existing: bool = False
) -> List[str]:
    clean_name = re.sub(r'[\\/*?:"<>|]', '_', template_name.strip("<>").strip())
    target_dir = MEDIA_DIR / clean_name
    if clear_existing and target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)
    target_dir.mkdir(parents=True, exist_ok=True)

    saved_paths = []
    if getattr(message, "grouped_id", None):
        album_messages = await fetch_album(client, message)
        for idx, m in enumerate(album_messages):
            if _is_downloadable_media(m):
                file_path = await client.download_media(m, file=str(target_dir / f"item_{item_index}_{idx}"))
                if file_path:
                    saved_paths.append(str(file_path))
    elif _is_downloadable_media(message):
        file_path = await client.download_media(message, file=str(target_dir / f"item_{item_index}_0"))
        if file_path:
            saved_paths.append(str(file_path))

    return saved_paths

def _resolve_media_path(path: str) -> Optional[str]:
    """Saved absolute path, or the same file under the current MEDIA_DIR
    (the bot folder was moved / renamed since the post was saved)."""
    if os.path.exists(path):
        return path
    try:
        p = Path(path)
        alt = MEDIA_DIR / p.parent.name / p.name
        if alt.exists():
            return str(alt)
    except Exception:
        pass
    return None


# "This chat does not allow <media type>" errors. The post is then sent as
# text only instead of failing (and being retried) forever.
_MEDIA_FORBIDDEN_ERRORS = tuple(
    getattr(errors, _n) for _n in (
        "ChatSendMediaForbiddenError", "ChatSendPhotosForbiddenError", "ChatSendVideosForbiddenError",
        "ChatSendGifsForbiddenError", "ChatSendDocsForbiddenError", "ChatSendAudiosForbiddenError",
        "ChatSendVoicesForbiddenError", "ChatSendStickersForbiddenError",
    ) if hasattr(errors, _n)
)


def _looks_like_markup_error(exc: BaseException) -> bool:
    text = str(exc).upper()
    return any(word in text for word in ("BUTTON", "REPLY_MARKUP", "KEYBOARD", "ENTITY_TYPE_INVALID"))


async def send_single_item(
    client: TelegramClient,
    chat_peer: Any,
    text: str,
    entities_hex: List[str],
    media_files: List[str],
    buttons: Optional[Any] = None,
    disable_preview: bool = False,
):
    """
    Send one post (text, one media or one album) exactly as saved.

    parse_mode=None everywhere: without it Telethon re-parsed every post as
    Markdown, so "__", "**" or "[x](y)" in an ad were silently mangled and
    album captions lost their formatting.

    link_preview=False is passed explicitly when the post was saved with the
    preview turned off, otherwise Telegram re-adds the preview card.
    """
    entities = deserialize_entities(entities_hex)
    existing_media = [p for p in (_resolve_media_path(f) for f in (media_files or []) if f) if p]
    if media_files and len(existing_media) != len(media_files):
        log_error(f"[WARN] Не найдено {len(media_files) - len(existing_media)} медиа-файл(ов) поста — отправляю что есть.")
    fmt_entities = entities if entities else None
    markup = build_buttons_markup(buttons) if buttons else None

    if not text and not existing_media:
        log_error("[WARN] Пустой пост: нет текста и медиа-файлы не найдены.")
        return

    if existing_media:
        files: Any = existing_media[0] if len(existing_media) == 1 else existing_media
        try:
            await client.send_file(
                chat_peer,
                file=files,
                caption=text or None,
                formatting_entities=fmt_entities,
                parse_mode=None,
                buttons=markup,
            )
            return
        except errors.RPCError as e:
            if markup is None or not _looks_like_markup_error(e):
                raise
            # Telegram не принял разметку кнопок (например callback на
            # юзер-аккаунте). Пост важнее кнопок — отправляем без них.
            log_error(f"[BTN] Telegram отклонил кнопки ({e}). Отправляю пост без кнопок.")
            await client.send_file(
                chat_peer,
                file=files,
                caption=text or None,
                formatting_entities=fmt_entities,
                parse_mode=None,
            )
            return
        except errors.MediaCaptionTooLongError:
            # Caption above the account's limit: media first, the text right
            # after it (the only way Telegram accepts it).
            await client.send_file(chat_peer, file=files, parse_mode=None)
            if text:
                await client.send_message(
                    chat_peer, message=text, formatting_entities=fmt_entities,
                    parse_mode=None, link_preview=not disable_preview, buttons=markup,
                )
            return
        except _MEDIA_FORBIDDEN_ERRORS:
            if not text:
                raise
            log_error("[MEDIA] В этом чате запрещены медиа — отправляю текст поста без вложений.")

    try:
        await client.send_message(
            chat_peer,
            message=text,
            formatting_entities=fmt_entities,
            parse_mode=None,
            link_preview=not disable_preview,
            buttons=markup,
        )
    except errors.RPCError as e:
        if markup is None or not _looks_like_markup_error(e):
            raise
        log_error(f"[BTN] Telegram отклонил кнопки ({e}). Отправляю пост без кнопок.")
        await client.send_message(
            chat_peer,
            message=text,
            formatting_entities=fmt_entities,
            parse_mode=None,
            link_preview=not disable_preview,
        )

async def send_broadcast_post(
    client: TelegramClient,
    chat_peer: Any,
    text: str = "",
    entities_hex: Optional[List[str]] = None,
    media_files: Optional[List[str]] = None,
    bundle: Optional[List[Dict[str, Any]]] = None,
    buttons: Optional[Any] = None,
    disable_preview: bool = False,
):
    if bundle:
        clean_bundle = [item for item in bundle if not is_internal_bot_message(item.get("text", ""))]
        sent_items = 0
        for idx, item in enumerate(clean_bundle):
            if idx > 0:
                await asyncio.sleep(1.0)
            try:
                await _send_bundle_item(
                    client, chat_peer, item,
                    buttons=buttons if idx == 0 else None,
                    disable_preview=disable_preview,
                )
                sent_items += 1
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if sent_items:
                    raise PartialSendError(sent_items, e) from e
                raise
    else:
        if is_internal_bot_message(text):
            return
        await send_single_item(
            client,
            chat_peer,
            text=text,
            entities_hex=entities_hex or [],
            media_files=media_files or [],
            buttons=buttons,
            disable_preview=disable_preview,
        )


async def _send_bundle_item(
    client: TelegramClient,
    chat_peer: Any,
    item: Dict[str, Any],
    buttons: Optional[Any] = None,
    disable_preview: bool = False,
):
    if item.get("is_forward") and item.get("forward_chat_id") and item.get("forward_msg_ids"):
        try:
            await client.forward_messages(
                chat_peer,
                messages=item["forward_msg_ids"],
                from_peer=item["forward_chat_id"]
            )
            return
        except (errors.SlowModeWaitError, errors.FloodWaitError, errors.UserBannedInChannelError,
                errors.ChannelPrivateError, errors.ChatWriteForbiddenError, asyncio.CancelledError,
                ConnectionError, OSError, asyncio.TimeoutError):
            raise
        except Exception as e:
            log_error(f"[WARN] Не удалось переслать сообщение: {e}. Отправляю сохранённую копию.")

    await send_single_item(
        client,
        chat_peer,
        text=item.get("text", ""),
        entities_hex=item.get("entities_hex", []),
        media_files=item.get("media_files", []),
        buttons=buttons,
        disable_preview=disable_preview,
    )


def _extract_folder_title(dialog_filter: Any) -> str:
    if hasattr(dialog_filter, "title"):
        title = dialog_filter.title
        if hasattr(title, "text"):
            return str(title.text).strip()
        return str(title).strip()
    return ""

async def get_chats_in_folder(client: TelegramClient, folder_name: str) -> List[int]:
    return (await get_folder_chats(client, folder_name)) or []


async def get_folder_chats(client: TelegramClient, folder_name: str) -> Optional[List[int]]:
    """Chat ids of a Telegram folder, or None when no folder has that title."""
    result = await client(GetDialogFiltersRequest())
    target_clean = folder_name.lower().strip()
    target_filter = None

    for f in getattr(result, "filters", []):
        # Duck-typed on purpose: Telegram has shipped several folder filter
        # shapes (DialogFilter, DialogFilterChatlist and their successors), and
        # an isinstance whitelist silently turned every unrecognised one into
        # "folder not found". Matching on the title alone is what actually
        # decides whether this filter is the folder we asked for.
        if hasattr(f, "title") or hasattr(f, "id"):
            title = _extract_folder_title(f).lower()
            if title == target_clean:
                target_filter = f
                break

    if not target_filter:
        return None

    chat_ids = set()
    for peer in list(getattr(target_filter, "include_peers", []) or []) + list(getattr(target_filter, "pinned_peers", []) or []):
        try:
            cid = utils.get_peer_id(peer)
            chat_ids.add(cid)
        except Exception:
            pass

    exclude_ids = set()
    for peer in getattr(target_filter, "exclude_peers", []):
        try:
            cid = utils.get_peer_id(peer)
            exclude_ids.add(cid)
        except Exception:
            pass

    has_flags = any([
        getattr(target_filter, "groups", False),
        getattr(target_filter, "broadcasts", False),
        getattr(target_filter, "contacts", False),
        getattr(target_filter, "non_contacts", False),
        getattr(target_filter, "bots", False),
    ])

    if has_flags:
        try:
            async for dialog in client.iter_dialogs(limit=5000):
                cid = dialog.id
                if cid in exclude_ids:
                    continue
                if getattr(target_filter, "exclude_muted", False) and getattr(getattr(dialog, "dialog", None), "notify_settings", None) and getattr(dialog.dialog.notify_settings, "silent", False):
                    continue
                if getattr(target_filter, "exclude_archived", False) and getattr(dialog, "archived", False):
                    continue

                matched = False
                if getattr(target_filter, "groups", False) and (dialog.is_group or (dialog.is_channel and not getattr(dialog.entity, "broadcast", False))):
                    matched = True
                elif getattr(target_filter, "broadcasts", False) and dialog.is_channel and getattr(dialog.entity, "broadcast", False):
                    matched = True
                elif getattr(target_filter, "contacts", False) and dialog.is_user and getattr(getattr(dialog.entity, "contact", None), "contact", False):
                    matched = True
                elif getattr(target_filter, "non_contacts", False) and dialog.is_user and not getattr(getattr(dialog.entity, "contact", None), "contact", False):
                    matched = True
                elif getattr(target_filter, "bots", False) and dialog.is_user and getattr(dialog.entity, "bot", False):
                    matched = True

                if matched:
                    chat_ids.add(cid)
        except Exception as e:
            log_error(f"[FOLDER] Не удалось прочитать список диалогов папки \"{folder_name}\": {type(e).__name__}: {e}")

    return [cid for cid in chat_ids if cid not in exclude_ids]

async def mute_peer(client: TelegramClient, peer: Any):
    try:
        input_peer = await client.get_input_entity(peer)
        await client(UpdateNotifySettingsRequest(
            peer=InputNotifyPeer(input_peer),
            settings=InputPeerNotifySettings(mute_until=2147483647)
        ))
    except Exception:
        pass

async def add_peer_to_folder(client: TelegramClient, folder_name: str, peer: Any):
    try:
        input_peer = await client.get_input_entity(peer)
        result = await client(GetDialogFiltersRequest())
        filters = getattr(result, "filters", [])
        target_clean = folder_name.lower().strip()

        target_filter = None
        max_id = 1

        for f in filters:
            fid = getattr(f, "id", 0)
            if fid > max_id:
                max_id = fid
            if isinstance(f, (DialogFilter, DialogFilterChatlist)) and _extract_folder_title(f).lower() == target_clean:
                target_filter = f
                break

        if target_filter:
            current_peers = list(getattr(target_filter, "include_peers", []))
            peer_ids = {utils.get_peer_id(p) for p in current_peers}
            new_id = utils.get_peer_id(input_peer)
            if new_id not in peer_ids:
                current_peers.append(input_peer)
                target_filter.include_peers = current_peers
                await client(UpdateDialogFilterRequest(
                    id=target_filter.id,
                    filter=target_filter
                ))
        else:
            new_id = max_id + 1
            new_filter = DialogFilter(
                id=new_id,
                title=TextWithEntities(text=folder_name, entities=[]),
                pinned_peers=[],
                include_peers=[input_peer],
                exclude_peers=[]
            )
            await client(UpdateDialogFilterRequest(id=new_id, filter=new_filter))
    except Exception:
        pass

async def join_and_silence_target(
    client: TelegramClient,
    target: str,
    folder_name: str
) -> bool:
    try:
        entity = None
        clean = target.strip()
        if clean.startswith("+") or "joinchat/" in clean:
            invite_hash = clean.split("+")[-1].split("joinchat/")[-1]
            updates = await client(ImportChatInviteRequest(invite_hash))
            chats = getattr(updates, "chats", [])
            if chats:
                entity = chats[0]
        else:
            username = clean.lstrip("@").split("/")[-1].split("?")[0]
            entity = await client.get_entity(username)
            if getattr(entity, "bot", False):
                start_param = ""
                if "?start=" in clean:
                    start_param = clean.split("?start=")[-1]
                await client.send_message(entity, f"/start {start_param}".strip())
            else:
                await client(JoinChannelRequest(entity))

        if entity:
            await mute_peer(client, entity)
            await add_peer_to_folder(client, folder_name, entity)
            return True
    except Exception:
        pass
    return False


# Highest message id of a *genuine* ping (real reply / mention from a person)
# per (account, chat) plus the time we saw it. Clearing a spam ping must not
# silently mark a real lead as read, but it also must not be blocked forever.
GENUINE_PING_TTL = 1800
_GENUINE_PINGS: Dict[Tuple[int, int], Any] = {}
_PRESERVED_PINGS: Set[Tuple[int, int, int]] = set()


def _pending_ping(key: Tuple[int, int]) -> Tuple[int, float]:
    raw = _GENUINE_PINGS.get(key)
    if raw is None:
        return 0, 0.0
    if isinstance(raw, (tuple, list)):
        try:
            return int(raw[0]), float(raw[1] or 0.0)
        except Exception:
            return 0, 0.0
    try:
        return int(raw), 0.0
    except Exception:
        return 0, 0.0


def note_genuine_ping(account_id: int, chat_id: int, msg_id: int):
    key = (account_id, chat_id)
    old_id, _old_ts = _pending_ping(key)
    if msg_id and msg_id > old_id:
        _GENUINE_PINGS[key] = (msg_id, time.time())
    if len(_GENUINE_PINGS) > 5000:
        for k in list(_GENUINE_PINGS)[:1000]:
            _GENUINE_PINGS.pop(k, None)


async def _preserve_ping(client: TelegramClient, input_peer: Any, chat_key: Any, msg_id: int, account_id: int) -> bool:
    """Скопировать живой пинг в «Избранное», чтобы не потерять лид при чтении чата."""
    key = (int(account_id or 0), int(chat_key or 0), int(msg_id or 0))
    if key in _PRESERVED_PINGS:
        return True
    try:
        await client.forward_messages("me", msg_id, from_peer=input_peer)
        _PRESERVED_PINGS.add(key)
        if len(_PRESERVED_PINGS) > 1000:
            _PRESERVED_PINGS.clear()
        log_info(f"[ANTISPAM] Живой пинг {msg_id} сохранён в Избранное, чат можно читать.")
        return True
    except Exception as e:
        log_info(f"[ANTISPAM] Пинг {msg_id} не сохранён ({type(e).__name__}), историю не трогаю.")
        return False


async def _resolve_input_peer(client: TelegramClient, chat_peer: Any, message: Any):
    from telethon.tl.types import InputPeerChannel, InputPeerChat, InputPeerUser, InputPeerSelf
    if isinstance(chat_peer, (InputPeerChannel, InputPeerChat, InputPeerUser, InputPeerSelf)):
        return chat_peer
    if message is not None and hasattr(message, "get_input_chat"):
        try:
            peer = await message.get_input_chat()
            if peer:
                return peer
        except Exception:
            pass
    if getattr(message, "input_chat", None):
        return message.input_chat
    try:
        return await client.get_input_entity(chat_peer)
    except Exception:
        return None


async def _safe_to_read_ad_history(client: TelegramClient, input_peer: Any, msg_id: int) -> bool:
    """Telegram cannot read just one history item. Fail closed on any doubt.

    Inspect at most 50 preceding unread messages, including after a restart;
    do not wipe conversations/mentions or an unbounded backlog to hide an ad.
    """
    from telethon.tl.functions.messages import GetPeerDialogsRequest
    from telethon.tl.types import InputDialogPeer
    try:
        result = await client(GetPeerDialogsRequest(peers=[InputDialogPeer(peer=input_peer)]))
        if not getattr(result, "dialogs", None):
            return False
        dialog = result.dialogs[0]
        read_max = dialog.read_inbox_max_id
        if read_max >= msg_id:
            return False  # Never re-read old edits.
        if getattr(dialog, "unread_count", 51) > 50:
            return False
        previous = await client.get_messages(input_peer, min_id=read_max, max_id=msg_id, limit=51)
        if previous is None or len(previous) > 50:
            return False
        for item in previous:
            if getattr(item, "out", False):
                continue
            if getattr(item, "mentioned", False):
                return False  # Preserve unknown genuine pings across restarts.
            body = getattr(item, "message", "") or ""
            if not should_auto_read(body, item, is_ping=False):
                return False
        return True
    except Exception as exc:
        log_info(f"[ANTISPAM] История не тронута: не удалось проверить непрочитанные ({type(exc).__name__}).")
        return False


async def clear_spam_mention(
    client: TelegramClient,
    chat_peer: Any,
    message: Any,
    account_id: int = 0,
    chat_id: Optional[int] = None,
    protect_unread_history: bool = False,
):
    """
    Silence one spam ping that reached us.

    1. Mark *only this message's* mention as read (readMessageContents). The
       old code called ReadMentions for the whole chat, which also wiped real
       mentions from people, and ReadReactions, which wiped real reactions.
    2. Read the chat history up to the spam message so the push notification
       disappears, but only when no genuine ping in that chat is still unread.
    """
    from telethon.tl.types import InputPeerChannel
    from telethon.tl.functions.messages import (
        ReadHistoryRequest as MessagesReadHistoryRequest,
        ReadMessageContentsRequest as MessagesReadContentsRequest,
        GetPeerDialogsRequest,
    )
    from telethon.tl.functions.channels import (
        ReadHistoryRequest as ChannelReadHistoryRequest,
        ReadMessageContentsRequest as ChannelReadContentsRequest,
    )
    from telethon.tl.types import InputDialogPeer

    msg_id = getattr(message, "id", 0) or 0
    if not msg_id:
        return
    input_peer = await _resolve_input_peer(client, chat_peer, message)
    if input_peer is None:
        return
    is_channel = isinstance(input_peer, InputPeerChannel)

    try:
        if is_channel:
            await client(ChannelReadContentsRequest(channel=utils.get_input_channel(input_peer), id=[msg_id]))
        else:
            await client(MessagesReadContentsRequest(id=[msg_id]))
    except Exception:
        pass

    if protect_unread_history and not await _safe_to_read_ad_history(client, input_peer, msg_id):
        return

    # Is a real ping in this chat still unread? Then leave the history alone.
    key_chat = chat_id if chat_id is not None else getattr(message, "chat_id", None)
    pending_id, pending_ts = _pending_ping((account_id, key_chat)) if key_chat is not None else (0, 0.0)
    if pending_id and pending_id < msg_id:
        try:
            res = await client(GetPeerDialogsRequest(peers=[InputDialogPeer(peer=input_peer)]))
            read_max = res.dialogs[0].read_inbox_max_id if getattr(res, "dialogs", None) else 0
        except Exception:
            read_max = 0
        if pending_id > read_max:
            expired = pending_ts and (time.time() - pending_ts) > GENUINE_PING_TTL
            if not expired and not await _preserve_ping(client, input_peer, key_chat, pending_id, account_id):
                return
            if expired:
                log_info(f"[ANTISPAM] Живой пинг {pending_id} протух, читаю чат дальше.")
        _GENUINE_PINGS.pop((account_id, key_chat), None)

    try:
        if is_channel:
            await client(ChannelReadHistoryRequest(channel=utils.get_input_channel(input_peer), max_id=msg_id))
        else:
            await client(MessagesReadHistoryRequest(peer=input_peer, max_id=msg_id))
    except Exception:
        pass


_MUTE_WARN_COOLDOWN: Dict[Tuple[int, int], float] = {}


async def mark_message_read(client: TelegramClient, chat_peer: Any, message: Any, chat_id: Optional[int] = None):
    """Снять с сообщения упоминание и прочитать его.

    send_read_acknowledge в Telethon 1.45 делает только readHistory, поэтому
    бейдж упоминания оставался. Здесь явно: readMessageContents (снимает
    упоминание по конкретному id), затем readHistory до этого сообщения
    (убирает пуш и счётчик непрочитанного).
    """
    msg_id = getattr(message, "id", 0) or 0
    if not msg_id:
        return
    target = chat_peer if chat_peer is not None else chat_id
    if target is None:
        return
    input_peer = await _resolve_input_peer(client, target, message)
    if input_peer is None:
        return
    from telethon.tl.types import InputPeerChannel
    from telethon.tl.functions.messages import (
        ReadHistoryRequest as MessagesReadHistoryRequest,
        ReadMessageContentsRequest as MessagesReadContentsRequest,
    )
    from telethon.tl.functions.channels import (
        ReadHistoryRequest as ChannelReadHistoryRequest,
        ReadMessageContentsRequest as ChannelReadContentsRequest,
    )
    is_channel = isinstance(input_peer, InputPeerChannel)
    try:
        if is_channel:
            await client(ChannelReadContentsRequest(channel=utils.get_input_channel(input_peer), id=[msg_id]))
        else:
            await client(MessagesReadContentsRequest(id=[msg_id]))
    except Exception as e:
        log_info(f"[READ] readMessageContents не прошёл ({type(e).__name__})")
    try:
        if is_channel:
            await client(ChannelReadHistoryRequest(channel=utils.get_input_channel(input_peer), max_id=msg_id))
        else:
            await client(MessagesReadHistoryRequest(peer=input_peer, max_id=msg_id))
    except Exception as e:
        log_info(f"[READ] readHistory не прошёл ({type(e).__name__})")


async def apply_mute_action(
    client: TelegramClient,
    message: Any,
    account_id: int,
    chat_id: Optional[int],
    action: str = "silent",
):
    """Реакция на сообщение заглушённого человека.

    Уведомление уже улетело на телефон, когда апдейт дошёл до нас, поэтому
    первым делом сообщение помечается прочитанным: Telegram убирает бейдж и
    гасит пуш. Дальше — то, что выбрал владелец: удалить, предупредить, бан.
    """
    if message is None:
        return
    action = (action or "silent").lower()
    if action not in MUTE_ACTIONS:
        action = "silent"

    await mark_message_read(client, getattr(message, "input_chat", None) or chat_id, message, chat_id)

    msg_id = getattr(message, "id", None)
    if action == "delete" and msg_id:
        try:
            await client.delete_messages(chat_id, [msg_id])
        except Exception as e:
            log_info(f"[MUTE] Не удалось удалить сообщение {msg_id}: {type(e).__name__}")
        return

    if action == "warn":
        key = (int(account_id or 0), int(_strip_peer_id(getattr(message, "sender_id", 0) or 0)))
        now = time.time()
        if now - _MUTE_WARN_COOLDOWN.get(key, 0.0) > 600:
            _MUTE_WARN_COOLDOWN[key] = now
            try:
                await client.send_message(
                    chat_id,
                    "Тебя не слышно: этот человек в игноре. Не пингуй.",
                    reply_to=msg_id,
                )
            except Exception:
                pass
        return

    if action == "ban":
        sender_id = getattr(message, "sender_id", None)
        if sender_id:
            try:
                await client.edit_permissions(chat_id, sender_id, view_messages=False)
            except Exception as e:
                log_info(f"[MUTE] Бан не сработал в чате {chat_id}: {type(e).__name__}")


class PartialSendError(Exception):
    """Some items of a multi-message post were delivered before an error."""

    def __init__(self, sent_items: int, original: BaseException):
        super().__init__(f"{sent_items} item(s) sent before: {original!r}")
        self.sent_items = sent_items
        self.original = original


# Errors after which the server definitely did NOT publish our message.
_DEFINITE_NOT_SENT = (
    errors.SlowModeWaitError,
    errors.FloodWaitError,
    errors.ChatWriteForbiddenError,
    errors.UserBannedInChannelError,
    errors.ChannelPrivateError,
)

# Telegram user ids of every account running in this process. Messages from
# our own accounts must never advance a counter, otherwise two accounts in the
# same chat keep triggering each other forever.
OWN_ACCOUNT_IDS: Set[int] = set()


class BroadcasterService:
    _ACTIVE_INSTANCES: Dict[int, 'BroadcasterService'] = {}
    FOLDER_SYNC_INTERVAL = 60.0
    RETRY_DELAY = 30.0          # seconds before retrying a definitely-failed send
    PAUSE_BETWEEN_CHATS = 1.5   # anti-flood pause between different chats

    def __init__(self, client: TelegramClient, account_id: int = 0):
        self.client = client
        self.account_id = account_id
        self.is_running = False
        self._task: Optional[asyncio.Task] = None
        self._chat_locks: Dict[int, asyncio.Lock] = {}
        self._sending_chats: Set[int] = set()
        self._last_sent_chat: Dict[int, float] = {}
        self._flood_until = 0.0
        self._folder_cache: Dict[Tuple[str, str], Tuple[float, List[int]]] = {}
        self._last_folder_log: Dict[Tuple[str, str], float] = {}
        self._bg_tasks: Set[asyncio.Task] = set()
        self._folder_missing: Dict[Tuple[str, str], int] = {}
        self._force_folder_sync = False
        self._last_folder_sync = 0.0
        self._wake_event: Optional[asyncio.Event] = None

    def _wakeup(self):
        if self._wake_event is not None:
            self._wake_event.set()

    # ------------------------------------------------------------------ life
    def start(self):
        old = BroadcasterService._ACTIVE_INSTANCES.get(self.account_id)
        if old and old is not self:
            old.stop()
        BroadcasterService._ACTIVE_INSTANCES[self.account_id] = self
        if self.account_id:
            OWN_ACCOUNT_IDS.add(int(self.account_id))
            try:
                db.adopt_legacy_rows(self.account_id)
            except Exception as e:
                log_error(f"[DB] Не удалось привязать старые рассылки к аккаунту: {e}")

        if self.is_running and self._task and not self._task.done():
            return
        self.is_running = True
        try:
            db.reset_pending_sends(self.account_id)
        except Exception:
            pass
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            self._wake_event = asyncio.Event()
            self._task = loop.create_task(self._loop())

    def stop(self):
        self.is_running = False
        if self._task and not self._task.done():
            self._task.cancel()
        for t in list(self._bg_tasks):
            if not t.done():
                t.cancel()
        self._bg_tasks.clear()
        self._sending_chats.clear()
        self._folder_cache.clear()
        self._wake_event = None
        if BroadcasterService._ACTIVE_INSTANCES.get(self.account_id) is self:
            BroadcasterService._ACTIVE_INSTANCES.pop(self.account_id, None)

    def request_folder_sync(self):
        """Run the folder sync on the next scheduler tick (after .продолжить)."""
        self._force_folder_sync = True

    def _chat_lock(self, chat_id: int) -> asyncio.Lock:
        lock = self._chat_locks.get(chat_id)
        if lock is None:
            lock = asyncio.Lock()
            self._chat_locks[chat_id] = lock
        return lock

    # --------------------------------------------------------------- folders
    async def sync_folder_broadcasts(self) -> int:
        """Enrol chats that appeared in a folder, park chats that left it."""
        folder_broadcasts = db.get_active_folder_broadcasts(account_id=self.account_id)
        if not folder_broadcasts:
            return 0

        enrolled_total = 0
        folder_cache: Dict[str, Optional[List[int]]] = {}
        for fb in folder_broadcasts:
            folder_name = (fb.get("folder_name") or "").strip()
            template_name = fb.get("template_name") or ""
            if not folder_name or not template_name:
                continue

            cache_key = (folder_name, template_name)
            try:
                if folder_name not in folder_cache:
                    folder_cache[folder_name] = await get_folder_chats(self.client, folder_name)
                live_chats = folder_cache[folder_name]
            except Exception as e:
                log_error(f"[FOLDER] Не удалось прочитать папку \"{folder_name}\": {e}")
                continue

            if live_chats is None:
                # Folder renamed or deleted. Park its chats after a few misses
                # instead of broadcasting into them forever.
                misses = self._folder_missing.get(cache_key, 0) + 1
                self._folder_missing[cache_key] = misses
                if misses < 10:
                    log_info(f"[FOLDER] Папка \"{folder_name}\" не читается ({misses}/10), чаты пока не трогаю.")
                    continue
                live_chats = []
            else:
                self._folder_missing.pop(cache_key, None)

            live_set = set(live_chats)
            enrolled_set = db.get_enrolled_chat_ids(template_name, folder_name, account_id=self.account_id)
            added = live_set - enrolled_set
            removed = enrolled_set - live_set

            for cid in sorted(added):
                try:
                    if db.ensure_broadcast_task(
                        account_id=self.account_id,
                        chat_id=cid,
                        template_name=template_name,
                        mode=fb.get("mode") or "interval",
                        interval_seconds=fb.get("interval_seconds") or 0,
                        counter_threshold=fb.get("counter_threshold") or 0,
                        folder_name=folder_name,
                    ):
                        enrolled_total += 1
                        log_info(f"[FOLDER] Новый чат {cid} добавлен в рассылку '{template_name}' (папка \"{folder_name}\")")
                except Exception as e:
                    log_error(f"[FOLDER] Не удалось добавить чат {cid} в рассылку \"{template_name}\": {e}")

            for cid in sorted(removed):
                try:
                    db.deactivate_broadcast_task(cid, template_name, account_id=self.account_id)
                except Exception as e:
                    log_error(f"[FOLDER] Не удалось снять чат {cid} с рассылки \"{template_name}\": {e}")

            self._folder_cache[cache_key] = (time.time(), list(live_chats))
            if added or removed:
                last_log = self._last_folder_log.get(cache_key, 0.0)
                if time.time() - last_log > 60.0:
                    self._last_folder_log[cache_key] = time.time()
                    log_info(
                        f"[FOLDER] \"{template_name}\" (\"{folder_name}\"): +{len(added)} / -{len(removed)}, всего {len(live_set)}"
                    )
        return enrolled_total

    # ------------------------------------------------------------ scheduler
    async def _sleep(self, wait: float) -> None:
        """Спать до ближайшего события или таймаута, без опроса базы каждую секунду."""
        wait = max(float(wait), 0.2)
        if self._wake_event is None:
            await asyncio.sleep(wait)
            return
        try:
            await asyncio.wait_for(self._wake_event.wait(), timeout=wait)
        except asyncio.TimeoutError:
            pass
        except asyncio.CancelledError:
            raise
        finally:
            if self._wake_event is not None:
                self._wake_event.clear()

    async def _loop(self):
        import gc
        last_gc = time.time()
        last_collector_clean = time.time()

        while self.is_running:
            try:
                now = time.time()
                if now - last_collector_clean > 30:
                    for k in [k for k, s in ACTIVE_COLLECTORS.items() if now - s.get("last_active", 0) > 300]:
                        ACTIVE_COLLECTORS.pop(k, None)
                    last_collector_clean = now
                if now - last_gc > 600:
                    gc.collect()
                    last_gc = now
                if self._force_folder_sync or now - self._last_folder_sync >= self.FOLDER_SYNC_INTERVAL:
                    self._force_folder_sync = False
                    self._last_folder_sync = now
                    try:
                        await self.sync_folder_broadcasts()
                    except Exception as e:
                        log_error(f"[FOLDER] Ошибка синхронизации папок: {e}")

                if now < self._flood_until:
                    await self._sleep(min(5.0, self._flood_until - now))
                    continue

                for task in db.get_active_interval_tasks(account_id=self.account_id):
                    if not self.is_running:
                        break
                    if time.time() < self._flood_until:
                        break
                    sent = await self._run_scheduled(task)
                    if sent:
                        await asyncio.sleep(self.PAUSE_BETWEEN_CHATS)

                for task in db.get_due_retries(account_id=self.account_id):
                    if not self.is_running or time.time() < self._flood_until:
                        break
                    if not db.claim_retry(task["id"], time.time()):
                        continue
                    if await self._deliver(task):
                        await asyncio.sleep(self.PAUSE_BETWEEN_CHATS)

                await self._sleep(self._next_wake())
            except asyncio.CancelledError:
                break
            except Exception as e:
                log_error(f"[LOOP] Ошибка планировщика: {type(e).__name__}: {e}")
                await asyncio.sleep(3.0)

    def _next_wake(self) -> float:
        now = time.time()
        try:
            tasks = db.get_active_interval_tasks(account_id=self.account_id)
            retry_at = db.next_retry_at(account_id=self.account_id)
        except Exception:
            return 5.0
        # Потолок в 30 секунд: если сон длиннее, событие вроде смены сети или
        # возврата из Doze всё равно должно быстро разбудить планировщик.
        wait = 30.0
        for t in tasks:
            mode = t.get("mode", "interval")
            if mode == "hybrid":
                if int(t.get("current_count") or 0) < max(int(t.get("counter_threshold") or 0), 1):
                    continue
            left = (t.get("interval_seconds") or 0) - (now - (t.get("last_sent_at") or 0))
            wait = min(wait, max(left, 0.2))
        if retry_at:
            wait = min(wait, max(retry_at - now, 0.2))
        folder_left = self.FOLDER_SYNC_INTERVAL - (now - self._last_folder_sync)
        if folder_left > 0:
            wait = min(wait, folder_left)
        return max(0.2, wait)

    async def _run_scheduled(self, task: Dict[str, Any]) -> bool:
        """Claim a due interval/hybrid task atomically, then send it."""
        mode = task.get("mode", "interval")
        if mode == "hybrid":
            interval = int(task.get("interval_seconds") or 0)
            claimed = db.claim_hybrid_task(task["id"], time.time(), stale_after=max(interval * 3, 1800))
        else:
            claimed = db.claim_interval_task(task["id"], time.time())
        if not claimed:
            return False
        return await self._deliver(task)

    # -------------------------------------------------------------- counter
    def on_incoming_message(self, chat_id: int):
        """Called from the event handler. Never blocks update processing."""
        if not self.is_running:
            return
        t = asyncio.ensure_future(self.handle_counter_event(chat_id))
        self._bg_tasks.add(t)
        t.add_done_callback(self._bg_tasks.discard)
        self._wakeup()

    async def handle_counter_event(self, chat_id: int):
        # increment_and_check_counter() resets the counter in the same
        # statement that reports it ready, so a task can only be claimed once.
        try:
            ready = db.increment_and_check_counter(chat_id, account_id=self.account_id)
        except Exception as e:
            log_error(f"[COUNT] Ошибка счётчика чата {chat_id}: {e}")
            return
        for task in ready:
            if time.time() < self._flood_until:
                db.schedule_retry(task, delay=self._flood_until - time.time() + 2, failed=False)
                continue
            # Атомарный claim: два события подряд не отправят пост дважды.
            if not db.claim_counter_task(task["id"], time.time()):
                continue
            await self._deliver(task)

    # ---------------------------------------------------------------- send
    def _backoff(self, task: Dict[str, Any], base: float, cap: float = 6 * 3600) -> float:
        try:
            fails = db.get_fail_count(task["id"])
        except Exception:
            fails = 0
        return min(cap, base * (2 ** min(fails, 10)))

    async def _deliver(self, task: Dict[str, Any]) -> bool:
        chat_id = task["chat_id"]
        template_name = task["template_name"]
        rotation_tpl = db.get_next_rotation_template(
            chat_id,
            account_id=self.account_id,
            rotation_name=template_name,
            member_of_chat_rotation=template_name,
        )
        effective_name = rotation_tpl or template_name

        outcome = await self._send_task(task["id"], chat_id, effective_name, task=task)
        if outcome == "sent":
            try:
                db.mark_task_sent(task["id"])
            except Exception:
                pass
        elif outcome == "retry":
            db.schedule_retry(task, delay=self._backoff(task, self.RETRY_DELAY, cap=3600))
        elif outcome == "busy":
            db.schedule_retry(task, delay=5.0, failed=False)
        elif outcome == "skip":
            db.clear_pending(task["id"])
        return outcome == "sent"

    async def _send_task(self, task_id: int, chat_id: int, template_name: str, task: Optional[Dict[str, Any]] = None) -> str:
        """
        Returns "sent", "retry" (server rejected it, try again later), "busy"
        (another send to this chat is running) or "skip".

        A network error in the middle of a send is ambiguous: Telegram may well
        have published the message already. Those are treated as sent, because
        resending them is exactly how one scheduled post turned into two.
        """
        template = db.get_template(template_name)
        if not template:
            log_error(f"[ERROR] Шаблон '{template_name}' не найден — задача рассылки отключена")
            try:
                db.deactivate_task(task_id)
            except Exception:
                pass
            return "skip"

        lock = self._chat_lock(chat_id)
        if lock.locked():
            log_info(f"[DEDUP] Чат {chat_id}: отправка уже идёт, дубликат пропущен.")
            return "busy"

        async with lock:
            self._sending_chats.add(chat_id)
            try:
                try:
                    peer = await self.client.get_input_entity(chat_id)
                except Exception:
                    peer = await self.client.get_entity(chat_id)
                await send_broadcast_post(
                    self.client,
                    peer,
                    text=template["text"],
                    entities_hex=template["entities_hex"],
                    media_files=template["media_files"],
                    bundle=template.get("bundle"),
                    buttons=template.get("buttons"),
                    disable_preview=bool(template.get("disable_preview")),
                )
                self._last_sent_chat[chat_id] = time.time()
                return "sent"
            except PartialSendError as e:
                log_error(f"[PARTIAL] Чат {chat_id}: отправлено {e.sent_items} из пачки, остаток пропущен ({e.original}).")
                self._last_sent_chat[chat_id] = time.time()
                return "sent"
            except errors.SlowModeWaitError as e:
                log_error(f"[SLOWMODE] Чат {chat_id}: медленный режим, ждать {e.seconds}с")
                if task is not None:
                    db.schedule_retry(task, delay=e.seconds + 2, failed=False)
                return "skip"
            except errors.FloodWaitError as e:
                log_error(f"[FLOOD] FloodWait {e.seconds}с (чат {chat_id}) — пауза всех отправок аккаунта")
                self._flood_until = time.time() + e.seconds + 1
                if task is not None:
                    db.schedule_retry(task, delay=e.seconds + 2, failed=False)
                return "skip"
            except (errors.UserBannedInChannelError, errors.ChannelPrivateError, errors.ChatWriteForbiddenError,
                    errors.ChatAdminRequiredError, errors.ChatRestrictedError) as e:
                # Not deactivated: a folder sync would re-enable it a minute
                # later and the cycle would repeat forever. Back off instead.
                delay = self._backoff(task or {"id": task_id}, 600) if task is not None else 600
                log_error(f"[PERM] Чат {chat_id}: писать нельзя ({type(e).__name__}). Повтор через {_format_seconds(int(delay))}.")
                if task is not None:
                    db.schedule_retry(task, delay=delay)
                return "skip"
            except errors.RPCError as e:
                log_error(f"[ERROR] Telegram отклонил отправку в чат {chat_id}: {e}")
                return "retry"
            except asyncio.CancelledError:
                raise
            except (ConnectionError, OSError, asyncio.TimeoutError) as e:
                log_error(f"[NET] Чат {chat_id}: связь оборвалась во время отправки ({e}). Не повторяю, чтобы не было дубля.")
                return "sent"
            except Exception as e:
                log_error(f"[ERROR] Ошибка отправки в чат {chat_id}: {type(e).__name__}: {e}")
                return "retry"
            finally:
                self._sending_chats.discard(chat_id)

HELP_TEXT = """
**⚙️ Управление юзерботом**

**1. Обычная рассылка (одно сообщение или альбом):**
• `.рассыл каждое 15 секунд <название>`
• `.рассыл каждые 10 минут <название> "папка"`
• `.рассыл через 1 <название>`
• `.рассыл через 3 <название> "папка"`
• `.рассыл через 10 соо минимум 10 минут <название>` — **совмещенный (гибридный) режим**: отправка через 10 сообщений, но не чаще раза в 10 минут
• `.рассыл комби 10 10м <название> "папка"` — краткая форма комбинированного режима
• Английские аналоги: `.broadcast every 15s <name>`, `.broadcast after 10 <name>`, `.broadcast hybrid 10 10m <name>`
*(Текст можно писать со 2-й строки или отправить команду в ответ на готовое сообщение)*

**2. Рассылка пересланных сообщений (с каналов / чатов):**
• `.рассыл-пересланное каждое 15 секунд <название>`
• `.рассыл-пересланное через 10 соо минимум 10 минут <название>`
• Английский аналог: `.broadcast-forwarded`
*(Бот включит сбор: пересылайте любые посты в чат, затем отправьте `.закрыть`)*

**3. Рассылка нескольких сообщений подряд (пачкой):**
• `.рассыл через 10 10м <название> "папка" -мульти` — быстрый запуск сбора пачки постов
• `.рассыл-несколько каждое 15 секунд <название>`
• `.рассыл-несколько через 10 соо минимум 10 минут <название>`
• Английские аналоги: `.broadcast-multi`, `.broadcast-multiple`
*(Бот включит сбор: отправляйте любые сообщения, медиа, премиум-эмодзи, затем отправьте `.закончить`)*

**4. Завершение и отмена сбора:**
• `.закончить` (или `.закрыть`, `.close`) — сохранить сообщения и запустить рассылку
• `.отменить` (или `.cancel`) — отменить текущую сессию сбора
*(Тайм-аут бездействия: 5 минут)*

**5. Чередование постов (ротации):**
• `.чередовать <название> <пост1> <пост2>...` — создать именованное чередование
• `.чередование <название> <пост1> <пост2>...`
• `.чередования` (или `.ротации`, `.rotations`) — посмотреть все чередования и их порядок
• `.удалить-чередование <название>` (или `.delete-rotation <name>`) — удалить чередование
• `.чередовать` (со следующей строки названия постов) — настроить чередование только для текущего чата
*(Имя чередования можно сразу передавать в `.рассыл`, например: `.рассыл через 10 соо минимум 10 минут связка1 "папка"`)*

**6. Управление статусом:**
• `.стоп <название>` / `.stop <name>` — остановить пост **во всех чатах**
• `.стоп <название> тут` — только в этом чате
• `.стоп <название> "папка"` — только в чатах папки
• `.стоп` (без аргументов) — всё в этом чате; `.стоп все` / `.stop all` — всё на аккаунте
• `.продолжить <название>` / `.resume <name>` — те же варианты (`тут`, `"папка"`, `все`)
• `.удалить <название>` / `.delete <name>` — удалить пост и его рассылки везде
• `.удалить <название> тут` / `.удалить все`
*(Остановленные вручную рассылки не оживают сами после перезапуска или синхронизации папки)*

**7. Просмотр и статистика:**
• `.рассылки` / `.broadcasts` / `.list` — **все активные и остановленные рассылки по всем чатам** (удобно найти «забытые»)
• `.просмотр <название>` / `.view <name>` — тестовая отправка поста со всеми медиа (или проверка чередования)
• `.просмотр все` / `.view all` — список всех рассылок и чередований в этом чате

**8. Антиспам и авто-подписка:**
• Гасит спам-пинги и явную рекламу **без упоминания**: прайсы, продажу с контактами, рекламные ссылки и скрытые теги. Проверяет также правки сообщений и ссылки в кнопках.
• Не читает историю ради рекламы без пинга, если выше остались обычные непрочитанные сообщения или проверить их не удалось. Текст внутри картинок не распознаётся; звук push-уведомления может успеть проиграть до обработки.
• Медиа (фото/видео) с пингом и рекламной подписью или почти без текста — спам.
• Понимает обфускацию: латиница вместо кириллицы (`3вёзды`, `zвезды`), буквы через точки/пробелы, «красивые» шрифты, транслит.
• Ловит скупку/продажу звёзд, TON, NFT-подарков, Premium/бустов, юзов, аккаунтов, «заработок», казино, накрутку, 18+, мошенничество, рекламу каналов и вотермарки автопостеров.
• Живые вопросы («где купить рекламу?», «сколько стоит?») не трогаются. Если в чате есть непрочитанный ответ от живого человека, он остаётся непрочитанным.
• Автоматически вступает в каналы/боты по требованию капчи админов, мьютит их и убирает в папку `автосабнутое`.

**9. Заглушение конкретных людей:**
• `.мутить` — ответьте командой на сообщение (самый точный способ)
• `.мутить @username` / `.мутить 123456789` — тихий режим: сообщения помечаются прочитанными, пинг и уведомление снимаются
• `.мутить @username удалить` — его сообщения сразу удаляются
• `.мутить @username варн` — бот отвечает предупреждением
• `.мутить @username бан` — снимает право писать (нужны права админа)
• `.мутить чат` — тишина во всём этом чате
• `.размутить @username` / `.заглушенные` — снять мьют и посмотреть список
*(Заглушенные не запускают авто-подписку и не увеличивают счётчик рассылки)*

**10. Кнопки под постом:**
• `.кнопки <название>` — пришли раскладку одним сообщением, одна строка = один ряд:
  `[Купить](https://t.me/manager) || [Прайс](https://t.me/price)`
  `[Написать](cb:hello)` — `cb:` делает callback-кнопку
• `.кнопки очистить <название>` — убрать кнопки

**11. Превью ссылок:**
• `.превью выкл <название>` — рассылать без карточки ссылки
• `.превью вкл <название>` — вернуть превью
*(Если пост собран из сообщения, где превью уже было выключено, бот запомнит это сам)*

**12. Служебное:**
• `.версия` — версия бота
• `.рассылки` — все рассылки аккаунта
• `.синк` — перечитать папки и подхватить новые чаты сразу
"""

def _extract_collector_flag(text: str) -> Tuple[Optional[str], str]:
    flag_fwd = re.compile(r'(?:^|\s)(?:--?пересланн\w*|--?fwd|--?forwarded)(?=\s|$)', re.IGNORECASE)
    flag_multi = re.compile(r'(?:^|\s)(?:--?мульти|--?multi|--?пачк\w*|--?несколько)(?=\s|$)', re.IGNORECASE)

    if flag_fwd.search(text):
        cleaned = flag_fwd.sub(' ', text).strip()
        cleaned = re.sub(r'\s+', ' ', cleaned)
        return 'forwarded', cleaned

    if flag_multi.search(text):
        cleaned = flag_multi.sub(' ', text).strip()
        cleaned = re.sub(r'\s+', ' ', cleaned)
        return 'multi', cleaned

    return None, text

def _extract_quoted_folder(text: str) -> Tuple[str, str]:
    match = re.search(r'"([^"]+)"', text)
    if match:
        folder = match.group(1).strip()
        cleaned = text[:match.start()] + text[match.end():]
        return folder, cleaned.strip()
    return "", text.strip()

def _strip_command_word(text: str) -> str:
    """
    Drop the leading command word (and its dot) from an argument string.

    Commands reach the handlers as the full raw line, so without this the first
    token is always ".мутить"/".mute" rather than the actual argument. Both mute
    handlers compare parts[0] against the numeric and username patterns, so an
    unstripped command word made every ".мутить @user" and ".мутить 123456789"
    form fail silently.
    """
    text = (text or "").strip()
    tokens = text.split(None, 1)
    if not tokens:
        return ""
    first = tokens[0]
    if first.startswith("."):
        return tokens[1] if len(tokens) > 1 else ""

    # Multiline form: the command sits alone on the first line and the target
    # follows on the next one.
    lines = text.splitlines()
    if len(lines) > 1 and not lines[0].strip().startswith("@"):
        return "\n".join(lines[1:]).strip()

    # Single-line form without a dot (some clients strip the leading dot): strip
    # the first word so the argument, not the verb, reaches the resolver.
    if len(tokens) > 1:
        return tokens[1]
    return ""

def _format_seconds(sec: int) -> str:
    if sec <= 0:
        return "0с"
    if sec % 86400 == 0:
        return f"{sec // 86400} д"
    if sec % 3600 == 0:
        return f"{sec // 3600} ч"
    if sec % 60 == 0:
        return f"{sec // 60} мин"
    return f"{sec}с"

def _parse_time_unit(val_str: str, unit_str: Optional[str]) -> Optional[int]:
    val = int(val_str)
    if not unit_str:
        return val
    u = unit_str.lower()
    if u.startswith(("с", "s")):
        return val
    if u.startswith(("м", "m")):
        return val * 60
    if u.startswith(("ч", "h")):
        return val * 3600
    if u.startswith(("д", "d")):
        return val * 86400
    return val

def _parse_interval_str(s: str) -> Optional[int]:
    clean = s.strip().lower()
    m = re.match(r"^(\d+)\s*(секунд\w*|сек|с|s|минут\w*|мин|м|m|час\w*|ч|h|дн\w*|день|д|d)?$", clean)
    if m:
        return _parse_time_unit(m.group(1), m.group(2))
    return None

def parse_broadcast_params(first_line: str) -> Tuple[str, int, int, str, str, str]:
    _, unflagged_line = _extract_collector_flag(first_line)
    folder_name, remaining_first_line = _extract_quoted_folder(unflagged_line)
    text = remaining_first_line.strip()
    tokens = text.split()

    if len(tokens) < 3:
        return "", 0, 0, "", "", "⚠️ Ошибка синтаксиса. Напишите `.инструкция`"

    sub_cmd = tokens[1].lower()
    mode = ""
    interval_sec = 0
    threshold_count = 0
    template_name = ""

    time_units = r"секунд\w*|сек|с|s|минут\w*|мин|м|m|час\w*|ч|h|дн\w*|день|д|d"

    # Match hybrid/combined broadcast pattern first:
    # e.g.:
    # .рассыл через 10 соо минимум 10 минут <название>
    # .рассыл через 10 соо кд 10м <название>
    # .рассыл через 10 10м <название>
    # .рассыл комби 10 10м <название>
    # .рассыл гибрид 10 10м <название>
    pattern_hybrid_kw = re.compile(
        rf"^(?:через|after)\s+(\d+)(?:\s*(?:соо\w*|сообщени\w*|messages?|msg\w*))?"
        rf"\s+(?:но\s+что\s*бы\s+|но\s+|что\s*бы\s+)?(?:кд|cd|минимум|min|пауза|задержка|от|не\s+чаще)\s*(\d+)\s*({time_units})?"
        rf"(?:\s+(?:прошло|пройдет|было|истекло))?"
        rf"\s+(.+)$",
        re.IGNORECASE
    )
    pattern_hybrid_unit = re.compile(
        rf"^(?:через|after)\s+(\d+)(?:\s*(?:соо\w*|сообщени\w*|messages?|msg\w*))?"
        rf"\s+(\d+)\s*({time_units})"
        rf"(?:\s+(?:прошло|пройдет|было|истекло))?"
        rf"\s+(.+)$",
        re.IGNORECASE
    )
    pattern_hybrid_direct = re.compile(
        rf"^(?:комби|комбинированное|гибрид|hybrid)\s+(\d+)(?:\s*(?:соо\w*|сообщени\w*|messages?|msg\w*))?"
        rf"\s+(?:(?:но\s+что\s*бы\s+|но\s+|что\s*бы\s+)?(?:кд|cd|минимум|min|пауза|задержка|от|не\s+чаще)\s*)?(\d+)\s*({time_units})?"
        rf"(?:\s+(?:прошло|пройдет|было|истекло))?"
        rf"\s+(.+)$",
        re.IGNORECASE
    )

    args_text = " ".join(tokens[1:])
    m_hyb = pattern_hybrid_kw.match(args_text) or pattern_hybrid_unit.match(args_text) or pattern_hybrid_direct.match(args_text)
    if m_hyb:
        count_str, time_str, unit_str, name_part = m_hyb.groups()
        try:
            threshold_count = int(count_str)
        except ValueError:
            return "", 0, 0, "", "", "⚠️ Число сообщений должно быть числом."
        interval_sec = _parse_time_unit(time_str, unit_str)
        if threshold_count <= 0:
            return "", 0, 0, "", "", "⚠️ Число сообщений должно быть > 0."
        if not interval_sec or interval_sec <= 0:
            return "", 0, 0, "", "", "⚠️ Неверно указано минимальное время задержки."
        template_name = name_part.strip("<>\"'").strip()
        if not template_name:
            return "", 0, 0, "", "", "⚠️ Не указано название рассылки."
        return "hybrid", interval_sec, threshold_count, template_name, folder_name, ""

    if sub_cmd in ("каждое", "каждые", "каждый", "every"):
        time_part = tokens[2]
        name_idx = 3
        if len(tokens) >= 4 and not tokens[3].startswith('"'):
            if not re.search(r"[a-zA-Zа-яА-Я]", time_part):
                time_part = f"{tokens[2]} {tokens[3]}"
                name_idx = 4

        interval_sec = _parse_interval_str(time_part)
        if not interval_sec or interval_sec <= 0:
            return "", 0, 0, "", "", "⚠️ Неверно указано время интервала."

        mode = "interval"
        if len(tokens) > name_idx:
            template_name = tokens[name_idx].strip("<>").strip()

    elif sub_cmd in ("через", "after"):
        try:
            threshold_count = int(tokens[2])
        except ValueError:
            return "", 0, 0, "", "", "⚠️ Число сообщений должно быть числом."

        if threshold_count <= 0:
            return "", 0, 0, "", "", "⚠️ Число сообщений должно быть > 0."

        mode = "counter"
        name_idx = 3
        if len(tokens) > 3 and re.match(r"^(?:соо\w*|сообщени\w*|messages?|msg\w*)$", tokens[3], re.IGNORECASE):
            name_idx = 4
        if len(tokens) > name_idx:
            template_name = tokens[name_idx].strip("<>").strip()
    else:
        return "", 0, 0, "", "", "⚠️ Неизвестный режим рассылки (ожидается: каждое / через / комби)."

    if not template_name:
        return "", 0, 0, "", "", "⚠️ Не указано название рассылки."

    return mode, interval_sec, threshold_count, template_name, folder_name, ""

_BG_NOTIFY_TASKS: Set["asyncio.Future"] = set()

async def _notify(event: Any, text: str, auto_delete: int = 5, force_respond: bool = False):
    msg = None
    try:
        if getattr(event, "out", False) and not getattr(event.message, "media", None) and not force_respond:
            msg = await event.edit(text)
        else:
            msg = await event.respond(text)
    except Exception:
        try:
            msg = await event.respond(text)
        except Exception as e:
            log_error(f"[ERROR] Ошибка отправки ответа на команду: {e}")

    if msg and hasattr(msg, "id"):
        _BOT_SYSTEM_MSG_IDS.add(msg.id)
        if len(_BOT_SYSTEM_MSG_IDS) > 2000:
            try:
                _BOT_SYSTEM_MSG_IDS.pop()
            except Exception:
                pass

    if auto_delete > 0 and msg:
        async def _delayed_delete(target_msg: Any, delay: int):
            try:
                await asyncio.sleep(delay)
                await target_msg.delete()
            except Exception:
                pass
        t = asyncio.ensure_future(_delayed_delete(msg, auto_delete))
        _BG_NOTIFY_TASKS.add(t)
        t.add_done_callback(_BG_NOTIFY_TASKS.discard)

class MessageDedupRing:
    """O(1) ring buffer for message deduplication across reconnects and burst updates."""
    def __init__(self, maxsize: int = 2000):
        self.maxsize = maxsize
        self._deque: Deque[Tuple[Any, int]] = collections.deque()
        self._set: Set[Tuple[Any, int]] = set()

    def check_and_add(self, chat_id: Any, msg_id: int) -> bool:
        """Returns True if already seen (duplicate), False if new."""
        key = (chat_id, msg_id)
        if key in self._set:
            return True
        if len(self._deque) >= self.maxsize:
            old = self._deque.popleft()
            self._set.discard(old)
        self._deque.append(key)
        self._set.add(key)
        return False

_GLOBAL_DEDUP_RING = MessageDedupRing(2000)

def _letters(s: str) -> str:
    return re.sub(r"[^0-9a-zа-яё]", "", unicodedata.normalize("NFKC", s or "").lower())


def _mention_entity_kind(text: str, message: Any, my_id: int, names: List[str], usernames: List[str]) -> Optional[str]:
    """
    Look at entities that point at OUR account. "name" when the visible label
    looks like our name / username (a normal mention), "hidden" when it is an
    emoji, a space or unrelated words (a stealth tag), None when absent.
    """
    entities = getattr(message, "entities", None) if message is not None else None
    if not entities or not my_id:
        return None
    from telethon.tl.types import MessageEntityMentionName, InputMessageEntityMentionName, MessageEntityTextUrl
    own_labels = [_letters(n) for n in list(names) + list(usernames) if _letters(n)]
    kind: Optional[str] = None
    for ent in entities:
        target = None
        if isinstance(ent, MessageEntityMentionName):
            target = getattr(ent, "user_id", None)
        elif isinstance(ent, InputMessageEntityMentionName):
            target = getattr(getattr(ent, "user_id", None), "user_id", None)
        elif isinstance(ent, MessageEntityTextUrl):
            url = (ent.url or "").lower()
            m = re.search(r"tg://user\?id=(\d+)", url)
            if m:
                target = int(m.group(1))
            else:
                m = re.search(r"t\.me/([a-z0-9_]{4,32})/?$", url)
                if m and m.group(1) in [u.lower() for u in usernames]:
                    target = my_id
        if target is None or int(target) != int(my_id):
            continue
        label = _letters(_utf16_slice(text or "", ent.offset, ent.length))
        looks_like_us = bool(label) and any(
            lbl in label or (len(label) >= 3 and (label in lbl or label[:4] == lbl[:4]))
            for lbl in own_labels
        )
        if not looks_like_us:
            return "hidden"
        kind = "name"
    return kind


async def classify_ping(event: Any, message: Any, text: str, my_id: int,
                        usernames: List[str], names: List[str]) -> Optional[str]:
    """
    How a message reached us: "reply", "username", "name", "stealth" or None.

    A reply to our own post is a ping even without @username or an entity: the
    old gate returned None before it ever looked at the reply, so ads sent as
    answers to our message were never cleared. "stealth" stays as it was: a
    mention Telegram flags but that is neither a reply nor a visible @handle.
    """
    mentioned = bool(getattr(message, "mentioned", False))
    typed_username = bool(text) and any(
        re.search(rf"(?<![\w@])@{re.escape(u)}(?!\w)", text, re.IGNORECASE) for u in usernames if u
    )
    ent_kind = _mention_entity_kind(text, message, my_id, names, usernames)

    reply_is_ours = False
    if getattr(event, "is_reply", False):
        try:
            reply_msg = await event.get_reply_message()
        except Exception:
            reply_msg = None
        if reply_msg is not None and (
            getattr(reply_msg, "sender_id", None) == my_id or getattr(reply_msg, "out", False)
        ):
            reply_is_ours = True

    if ent_kind == "hidden":
        return "stealth"
    if reply_is_ours:
        return "reply"
    if typed_username:
        return "username"
    if ent_kind == "name":
        return "name"
    if mentioned:
        return "stealth"
    return None


def register_events(client: TelegramClient, broadcaster: BroadcasterService, my_id: int, acc_cfg: Optional[Dict[str, Any]] = None):
    # Always keep client's broadcaster reference current
    client._colemailer_broadcaster = broadcaster
    client._spambuster_broadcaster = broadcaster

    # Guard against duplicate handler registration on client reconnection or re-init
    if getattr(client, "_colemailer_events_registered", False):
        log_info(f"[LIFECYCLE] Обработчики событий уже зарегистрированы для клиента {my_id}. Пропуск повторной регистрации.")
        return

    client._colemailer_events_registered = True
    client._spambuster_events_registered = True

    if acc_cfg is None:
        acc_cfg = CONFIG

    auto_read_spam = acc_cfg.get("auto_read_spam_pings", True)
    auto_sub = acc_cfg.get("auto_sub_enabled", True)
    auto_folder = acc_cfg.get("auto_sub_folder", "автосабнутое")
    me_obj = getattr(client, "_self_user", None)
    my_username = getattr(me_obj, "username", None) or acc_cfg.get("username") or ""
    my_usernames: List[str] = [u for u in {my_username.lower()} if u]
    for un in (getattr(me_obj, "usernames", None) or []):
        u = (getattr(un, "username", "") or "").lower()
        if u and getattr(un, "active", True) and u not in my_usernames:
            my_usernames.append(u)
    my_names: List[str] = [n for n in (getattr(me_obj, "first_name", None), getattr(me_obj, "last_name", None)) if n]
    OWN_USERNAMES.update(my_usernames)

    # Warm the mute index so the very first incoming message is filtered too.
    mute_cache_rebuild(my_id)

    @client.on(events.NewMessage(incoming=True))
    async def incoming_handler(event: Any):
        chat_id = event.chat_id
        msg_id = getattr(event, "id", None)
        if msg_id and chat_id:
            # Keyed per account: with two accounts in one chat the second one
            # used to see the message as a "duplicate" and ignore it.
            if _GLOBAL_DEDUP_RING.check_and_add((my_id, chat_id), msg_id):
                return

        sender_id = event.sender_id
        # Our own other accounts never count and are never "spam".
        if sender_id is not None and _strip_peer_id(sender_id) in OWN_ACCOUNT_IDS:
            return

        active_broadcaster = getattr(client, "_colemailer_broadcaster", broadcaster)
        mute_action = mute_action_for(my_id, sender_id, chat_id)
        if mute_action:
            if mute_scope_for(my_id, sender_id, chat_id) == "chat" and mute_action in ("ban", "warn"):
                # В чате нельзя банить/предупреждать всех подряд — только тишина.
                mute_action = "silent"
            log_info(f"[MUTE] Чат {chat_id}: сообщение от {sender_id}, действие '{mute_action}'.")
            if mute_action != "silent":
                await apply_mute_action(client, event.message, my_id, chat_id, mute_action)
            else:
                await mark_message_read(client, getattr(event, "input_chat", None) or chat_id, event.message, chat_id)
            return

        # Counter broadcasts run in the background: a slow media upload must
        # not delay spam clearing or command handling.
        active_broadcaster.on_incoming_message(chat_id)
        if event.is_private:
            return

        text = event.raw_text or ""
        message = event.message

        # Did this message actually reach us, and how? reply to our post /
        # our @handle typed / a mention of our name / a hidden ("stealth") tag.
        # Only mentions trigger a reply lookup: fetching the replied message
        # for every reply in every chat flooded the account with requests.
        try:
            ping_kind = await classify_ping(event, message, text, my_id, my_usernames, my_names)
        except Exception as e:
            log_error(f"[PING] Не удалось разобрать упоминание: {e}")
            ping_kind = "unknown" if getattr(message, "mentioned", False) else None
        is_ping = ping_kind is not None

        if auto_read_spam:
            target_peer = getattr(event, "input_chat", None) or chat_id
            if should_auto_read(text, message, is_ping=is_ping, ping_kind=ping_kind if ping_kind != "unknown" else None):
                await clear_spam_mention(client, target_peer, message, account_id=my_id, chat_id=chat_id,
                                         protect_unread_history=not is_ping)
            elif is_ping:
                note_genuine_ping(my_id, chat_id, msg_id or 0)

        if auto_sub and is_gatekeeper_text(text):
            if is_ping or str(my_id) in text:
                targets = set(extract_channel_links(text))
                verify_coords = None

                if event.message.reply_markup and hasattr(event.message.reply_markup, "rows"):
                    for r_idx, row in enumerate(event.message.reply_markup.rows):
                        for c_idx, button in enumerate(row.buttons):
                            url = getattr(button, "url", None)
                            if url:
                                targets.update(extract_channel_links(url))
                            btn_text = getattr(button, "text", "")
                            if is_verify_button(btn_text):
                                verify_coords = (r_idx, c_idx)

                for target in targets:
                    await join_and_silence_target(client, target, auto_folder)

                if verify_coords:
                    try:
                        await event.message.click(*verify_coords)
                    except Exception:
                        pass

    @client.on(events.MessageEdited(incoming=True))
    async def edited_spam_handler(event: Any):
        # Spammers can add ads/hidden mentions after a harmless first message.
        # Do not touch counter broadcasts, subscriptions, or new-message dedup.
        if not auto_read_spam or event.is_private:
            return
        sender_id = event.sender_id
        if sender_id is not None and _strip_peer_id(sender_id) in OWN_ACCOUNT_IDS:
            return
        if is_peer_muted(my_id, sender_id, event.chat_id):
            await mark_message_read(
                client, getattr(event, "input_chat", None) or event.chat_id, event.message, event.chat_id
            )
            return
        text = event.raw_text or ""
        message = event.message
        try:
            kind = await classify_ping(event, message, text, my_id, my_usernames, my_names)
        except Exception:
            kind = "unknown" if getattr(message, "mentioned", False) else None
        if should_auto_read(text, message, is_ping=kind is not None,
                            ping_kind=kind if kind != "unknown" else None):
            await clear_spam_mention(client, getattr(event, "input_chat", None) or event.chat_id,
                                     message, account_id=my_id, chat_id=event.chat_id,
                                     protect_unread_history=kind is None)
        elif kind is not None:
            note_genuine_ping(my_id, event.chat_id, event.id)

    @client.on(events.Raw())
    async def folder_update_handler(update: Any):
        """Папку поправили на другом устройстве — сразу пересобрать список чатов."""
        name = type(update).__name__
        if "DialogFilter" in name or "FolderPeer" in name:
            current = getattr(client, "_colemailer_broadcaster", broadcaster)
            try:
                current.request_folder_sync()
            except Exception:
                pass

    @client.on(events.NewMessage())
    async def command_dispatcher(event: Any):
        if not getattr(event, "out", False) and event.sender_id != my_id:
            return

        msg_id = getattr(event, "id", None)
        if msg_id and msg_id in _BOT_SYSTEM_MSG_IDS:
            return

        raw = event.raw_text or ""
        if is_internal_bot_message(raw):
            if msg_id:
                _BOT_SYSTEM_MSG_IDS.add(msg_id)
            return

        chat_id = event.chat_id
        collector_key = (my_id, chat_id)

        if collector_key in ACTIVE_COLLECTORS or chat_id in ACTIVE_COLLECTORS:
            c_key = collector_key if collector_key in ACTIVE_COLLECTORS else chat_id
            session = ACTIVE_COLLECTORS[c_key]
            if time.time() - session.get("last_active", 0) > 300:
                ACTIVE_COLLECTORS.pop(c_key, None)
                if raw.strip().lower() in (
                    ".закрыть", ".close", "закрыть", "close",
                    ".закончить", ".завершить", "закончить", "завершить",
                    ".готово", "готово", ".done", "done",
                    ".отменить", ".cancel", "отменить", "cancel", ".отмена", "отмена"
                ):
                    await _notify(event, "⚠️ Время ожидания сообщений (5 минут) истекло. Сессия сброшена.")
                    return
            else:
                low = raw.strip().lower()
                if low in (
                    ".закрыть", ".close", "закрыть", "close",
                    ".закончить", ".завершить", "закончить", "завершить",
                    ".готово", "готово", ".done", "done",
                    ".finish", "finish", ".end", "end"
                ):
                    await finish_collector_session(event, session, c_key)
                    return
                elif low in (
                    ".отменить", ".cancel", "отменить", "cancel",
                    ".отмена", "отмена", ".стоп", "стоп"
                ):
                    template_name = session["template_name"]
                    target_dir = MEDIA_DIR / re.sub(r'[\\/*?:"<>|]', '_', template_name.strip("<>").strip())
                    if target_dir.exists():
                        shutil.rmtree(target_dir, ignore_errors=True)
                    ACTIVE_COLLECTORS.pop(c_key, None)
                    await _notify(event, f"❌ Настройка рассылки **{template_name}** отменена.")
                    return
                elif raw.startswith(".") and any(raw.lower().startswith(c) for c in (
                    ".рассыл", ".broadcast", ".чередовать", ".чередование", ".ротация", ".rotate", ".стоп", ".stop",
                    ".продолжить", ".resume", ".удалить", ".delete", ".просмотр", ".view",
                    ".инструкция", ".help", ".чередования", ".ротации", ".rotations",
                    ".закончить", ".завершить", ".готово",
                    ".мутить", ".мут", ".mute", ".ignore",
                    ".размутить", ".размут", ".unmute", ".unignore",
                    ".заглушенные", ".мутлист", ".mutelist", ".рассылки", ".broadcasts",
                    ".кнопки", ".buttons", ".превью", ".preview",
                    ".синк", ".sync", ".версия", ".version"
                )):
                    ACTIVE_COLLECTORS.pop(c_key, None)
                else:
                    await collect_message_to_session(event, session)
                    return

        if not raw.startswith("."):
            return

        first_line = raw.splitlines()[0].strip()
        parts = first_line.split()
        if not parts:
            return

        cmd = parts[0].lower()
        log_info(f"[CMD][{my_id}] Распознана команда '{cmd}' в чате {event.chat_id}")

        if cmd in (".инструкция", ".help"):
            await _notify(event, HELP_TEXT, auto_delete=0)
            return

        if cmd in (".версия", ".version"):
            await _notify(event, f"{APP_NAME} {APP_VERSION}", auto_delete=20)
            return

        if cmd in (".рассыл", ".broadcast"):
            await handle_broadcast_create(event, parts, raw)
            return

        if cmd in (".рассыл-пересланное", ".broadcast-forwarded"):
            await handle_collector_start(event, raw, session_type="forwarded")
            return

        if cmd in (".рассыл-несколько", ".рассыл-мульти", ".broadcast-multi", ".broadcast-multiple"):
            await handle_collector_start(event, raw, session_type="multi")
            return

        if cmd in (".чередовать", ".чередование", ".ротация", ".создать-чередование", ".rotate", ".rotation", ".create-rotation"):
            await handle_rotation_create(event, raw)
            return

        if cmd in (".удалить-чередование", ".удалить-ротацию", ".delete-rotation"):
            await handle_delete_rotation(event, parts)
            return

        if cmd in (".чередования", ".ротации", ".rotations"):
            await handle_list_rotations(event)
            return

        if cmd in (".мутить", ".мут", ".mute", ".ignore"):
            await handle_mute(event, raw)
            return

        if cmd in (".размутить", ".размут", ".unmute", ".unignore"):
            await handle_unmute(event, raw)
            return

        if cmd in (".заглушенные", ".мутлист", ".mutelist"):
            await handle_mute_list(event)
            return

        if cmd in (".стоп", ".stop"):
            await handle_stop(event, parts, raw)
            return

        if cmd in (".продолжить", ".resume"):
            await handle_resume(event, parts, raw)
            return

        if cmd in (".удалить", ".delete"):
            await handle_delete(event, parts, raw)
            return

        if cmd in (".просмотр", ".view"):
            await handle_view(event, parts)
            return

        if cmd in (".рассылки", ".все-рассылки", ".broadcasts", ".list"):
            await handle_list_all(event)
            return

        if cmd in (".кнопки", ".buttons"):
            await handle_buttons_command(event, raw)
            return

        if cmd in (".превью", ".preview"):
            await handle_preview_command(event, raw)
            return

        if cmd in (".синк", ".sync", ".папки-обновить"):
            active_b = getattr(client, "_colemailer_broadcaster", None) or broadcaster
            try:
                added = await active_b.sync_folder_broadcasts()
            except Exception as e:
                await _notify(event, f"⚠️ Синхронизация не удалась: {type(e).__name__}: {e}")
                return
            await _notify(event, f"🔄 Папки перечитаны. Новых чатов в рассылках: {added}.")
            return

    async def handle_collector_start(event: Any, raw: str, session_type: str):
        mode, interval_sec, threshold_count, template_name, folder_name, err = parse_broadcast_params(raw.splitlines()[0])
        if err:
            await _notify(event, err)
            return

        chat_id = event.chat_id
        items = []

        clean_name = re.sub(r'[\\/*?:"<>|]', '_', template_name.strip("<>").strip())
        target_dir = MEDIA_DIR / clean_name
        if target_dir.exists():
            shutil.rmtree(target_dir, ignore_errors=True)

        if event.is_reply:
            reply_msg = await event.get_reply_message()
            if reply_msg:
                grouped_id = getattr(reply_msg, "grouped_id", None)
                saved_media = []
                if reply_msg.media:
                    saved_media = await save_media_from_message(
                        client,
                        reply_msg,
                        template_name,
                        item_index=0,
                        clear_existing=False
                    )
                caption_msg = reply_msg
                msg_ids = [reply_msg.id]
                if grouped_id:
                    # The whole album, not just the photo the command replied
                    # to (forwarding one id sent a single picture of the album).
                    album = await fetch_album(client, reply_msg)
                    msg_ids = [m.id for m in album]
                    caption_msg = next((m for m in album if m.raw_text or m.entities), reply_msg)
                text = caption_msg.raw_text or ""
                entities_hex = serialize_entities(caption_msg.entities)
                is_fwd = bool(getattr(reply_msg, "fwd_from", None))
                items.append({
                    "text": text,
                    "entities_hex": entities_hex,
                    "media_files": saved_media,
                    "is_forward": is_fwd,
                    "forward_chat_id": reply_msg.chat_id,
                    "forward_msg_ids": msg_ids,
                    "grouped_id": grouped_id,
                    "disable_preview": _preview_disabled(caption_msg, text),
                })

        collector_key = (my_id, chat_id)
        ACTIVE_COLLECTORS[collector_key] = {
            "account_id": my_id,
            "chat_id": chat_id,
            "template_name": template_name,
            "mode": mode,
            "interval_seconds": interval_sec,
            "counter_threshold": threshold_count,
            "folder_name": folder_name,
            "session_type": session_type,
            "items": items,
            "started_at": time.time(),
            "last_active": time.time()
        }

        kind_desc = "пересланных сообщений" if session_type == "forwarded" else "сообщений пачкой"
        action_prompt = "Пересылайте сообщения" if session_type == "forwarded" else "Отправляйте или пересылайте сообщения"
        reply_note = f"\n📎 Сообщение из ответа уже добавлено как #1 (всего: {len(items)})." if items else ""

        await _notify(
            event,
            f"📥 **Режим сбора {kind_desc} начат!**\n"
            f"Имя рассылки: **{template_name}**\n"
            f"{action_prompt} в этот чат.{reply_note}\n\n"
            f"• Напишите `.закончить` (или `.закрыть`) — когда закончите добавление и нужно запустить рассылку.\n"
            f"• Напишите `.отменить` — чтобы прервать и сбросить.\n"
            f"⏱ Тайм-аут бездействия: 5 минут.",
            auto_delete=0
        )

    async def collect_message_to_session(event: Any, session: Dict[str, Any]):
        msg = event.message
        if getattr(msg, "id", None) in _BOT_SYSTEM_MSG_IDS:
            return

        text = msg.raw_text or ""
        if is_internal_bot_message(text):
            if hasattr(msg, "id"):
                _BOT_SYSTEM_MSG_IDS.add(msg.id)
            return

        if session.get("session_type") == "buttons":
            from cole.buttons import ButtonError, parse_row
            rows: List[Any] = []
            try:
                for line in text.splitlines():
                    if not line.strip():
                        continue
                    row = parse_row(line)
                    if row:
                        rows.append(row)
            except ButtonError as e:
                await _notify(event, f"⚠️ Кнопки не разобраны: {e}\nПопробуй ещё раз.")
                return
            name = session["template_name"]
            tpl = db.get_template(name)
            if not rows or not tpl:
                await _notify(event, "⚠️ Не вижу ни одной кнопки. Пример: `[Купить](https://t.me/manager)`")
                return
            db.save_template(
                name, tpl["text"], tpl["entities_hex"], tpl["media_files"],
                bundle_json=json.dumps(tpl["bundle"], ensure_ascii=False) if tpl.get("bundle") else "",
                buttons_json=buttons_to_json(rows), disable_preview=tpl.get("disable_preview") or 0,
            )
            ACTIVE_COLLECTORS.pop((my_id, event.chat_id), None)
            ACTIVE_COLLECTORS.pop(event.chat_id, None)
            await _notify(event, f"✅ Кнопки для **{name}** сохранены:\n{describe_buttons(rows)}")
            return

        session["last_active"] = time.time()
        template_name = session["template_name"]
        grouped_id = getattr(msg, "grouped_id", None)

        # Albums arrive as N separate messages, handled concurrently. The old
        # code downloaded the whole album for EVERY part (an album of 3 became
        # 9 files) and, because the item was appended only after an await,
        # parts could also become separate items. Both meant one post was sent
        # as two or more. Register the album synchronously, download it once.
        if grouped_id:
            albums = session.setdefault("_albums", {})
            existing = albums.get(grouped_id)
            if existing is not None:
                if msg.id not in existing["forward_msg_ids"]:
                    existing["forward_msg_ids"].append(msg.id)
                    existing["forward_msg_ids"].sort()
                if (not existing["text"]) and (msg.raw_text or msg.entities):
                    existing["text"] = msg.raw_text or ""
                    existing["entities_hex"] = serialize_entities(msg.entities)
                return
            item = {
                "text": text,
                "entities_hex": serialize_entities(msg.entities),
                "media_files": [],
                "is_forward": bool(getattr(msg, "fwd_from", None)),
                "forward_chat_id": event.chat_id,
                "forward_msg_ids": [msg.id],
                "grouped_id": grouped_id,
                "disable_preview": _preview_disabled(msg, text),
            }
            albums[grouped_id] = item
            session["items"].append(item)
            item_index = len(session["items"]) - 1
            await asyncio.sleep(1.5)  # let the remaining album parts arrive
            try:
                item["media_files"] = await save_media_from_message(
                    client, msg, template_name, item_index=item_index, clear_existing=False
                )
            except Exception as e:
                log_error(f"[COLLECT] Не удалось скачать альбом: {e}")
            await _notify(
                event,
                f"📥 Сообщение #{item_index + 1} (альбом, {len(item['media_files'])} медиа) добавлено в рассылку **{template_name}**.\n"
                f"Отправьте следующее сообщение или напишите `.закрыть` (для отмены `.отменить`).",
                auto_delete=4,
                force_respond=True
            )
            return

        item_index = len(session["items"])
        placeholder: Dict[str, Any] = {}
        session["items"].append(placeholder)  # reserve the slot before awaiting
        saved_media = []
        if msg.media:
            saved_media = await save_media_from_message(
                client,
                msg,
                template_name,
                item_index=item_index,
                clear_existing=False
            )

        entities_hex = serialize_entities(msg.entities)
        is_fwd = bool(getattr(msg, "fwd_from", None))

        item = {
            "text": text,
            "entities_hex": entities_hex,
            "media_files": saved_media,
            "is_forward": is_fwd,
            "forward_chat_id": event.chat_id,
            "forward_msg_ids": [msg.id],
            "grouped_id": grouped_id,
            "disable_preview": _preview_disabled(msg, text),
        }
        placeholder.update(item)
        count = item_index + 1
        await _notify(
            event,
            f"📥 Сообщение #{count} добавлено в рассылку **{template_name}**.\n"
            f"Отправьте следующее сообщение или напишите `.закрыть` (для отмены `.отменить`).",
            auto_delete=4,
            force_respond=True
        )

    async def finish_collector_session(event: Any, session: Dict[str, Any], session_key: Any = None):
        if session_key is None:
            session_key = (my_id, event.chat_id) if (my_id, event.chat_id) in ACTIVE_COLLECTORS else event.chat_id
        chat_id = event.chat_id
        template_name = session["template_name"]
        items = [
            {k: v for k, v in it.items() if not k.startswith("_")}
            for it in session["items"]
            if it and (it.get("text") or it.get("media_files") or it.get("forward_msg_ids"))
            and not is_internal_bot_message(it.get("text", ""))
        ]
        session["items"] = items

        if not items:
            clean_name = re.sub(r'[\\/*?:"<>|]', '_', template_name.strip("<>").strip())
            target_dir = MEDIA_DIR / clean_name
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
            ACTIVE_COLLECTORS.pop(session_key, None)
            await _notify(event, "⚠️ Не было добавлено ни одного сообщения. Сессия закрыта.")
            return

        first = items[0]
        root_text = first.get("text", "")
        root_entities = first.get("entities_hex", [])
        root_media = first.get("media_files", [])
        buttons_rows: List[Any] = []
        if items:
            last_text = items[-1].get("text", "") or ""
            trimmed, buttons_rows = _strip_trailing_buttons(last_text)
            if buttons_rows:
                items[-1]["text"] = trimmed
                if items[-1] is first:
                    root_text = trimmed
        disable_preview = 1 if any(int(it.get("disable_preview") or 0) for it in items) else 0
        bundle_json = json.dumps(items, ensure_ascii=False)

        db.save_template(
            template_name, root_text, root_entities, root_media,
            bundle_json=bundle_json,
            buttons_json=buttons_to_json(buttons_rows),
            disable_preview=disable_preview,
        )

        folder_name = session["folder_name"]
        mode = session["mode"]
        interval_sec = session["interval_seconds"]
        threshold_count = session["counter_threshold"]

        target_chats = []
        if folder_name:
            target_chats = await get_chats_in_folder(client, folder_name)
            if not target_chats:
                ACTIVE_COLLECTORS.pop(session_key, None)
                await _notify(event, f"⚠️ Папка \"{folder_name}\" не найдена или пуста.")
                return
        else:
            target_chats = [chat_id]

        for cid in target_chats:
            db.add_or_update_broadcast(
                account_id=my_id,
                chat_id=cid,
                template_name=template_name,
                mode=mode,
                interval_seconds=interval_sec,
                counter_threshold=threshold_count,
                folder_name=folder_name
            )

        if folder_name:
            db.register_folder_broadcast(
                folder_name=folder_name,
                template_name=template_name,
                mode=mode,
                interval_seconds=interval_sec,
                counter_threshold=threshold_count,
                account_id=my_id
            )

        ACTIVE_COLLECTORS.pop(session_key, None)

        if mode == "interval":
            details = f"каждые {_format_seconds(interval_sec)}"
        elif mode == "hybrid":
            details = f"через {threshold_count} соо (кд {_format_seconds(interval_sec)})"
        else:
            details = f"через каждые {threshold_count} соо"
        target_info = f"в папке \"{folder_name}\" ({len(target_chats)} чатов)" if folder_name else "в этом чате"
        kind_str = "пересланных сообщений" if session["session_type"] == "forwarded" else "сообщений пачкой"
        await _notify(
            event,
            f"✅ Рассылка {kind_str} **{template_name}** успешно запущена!\n"
            f"📦 Сообщений в пачке: {len(items)}\n"
            f"⏱ Режим: {details} {target_info}."
        )

    async def handle_broadcast_create(event: Any, parts: List[str], raw: str):
        flag, cleaned_first_line = _extract_collector_flag(raw.splitlines()[0])
        if flag:
            other_lines = raw.splitlines()[1:]
            cleaned_raw = "\n".join([cleaned_first_line] + other_lines)
            await handle_collector_start(event, cleaned_raw, session_type=flag)
            return

        mode, interval_sec, threshold_count, template_name, folder_name, err = parse_broadcast_params(raw.splitlines()[0])
        if err:
            await _notify(event, err)
            return

        text = ""
        entities_hex = []
        media_files = []
        buttons_rows: List[Any] = []
        disable_preview = 0

        if event.is_reply:
            reply_msg = await event.get_reply_message()
            if reply_msg:
                if getattr(reply_msg, "grouped_id", None):
                    album_messages = await fetch_album(client, reply_msg)

                    caption_msg = reply_msg
                    for m in album_messages:
                        if m.raw_text or m.entities:
                            caption_msg = m
                            break
                    text = caption_msg.raw_text or ""
                    entities_hex = serialize_entities(caption_msg.entities)
                else:
                    text = reply_msg.raw_text or ""
                    entities_hex = serialize_entities(reply_msg.entities)

                disable_preview = _preview_disabled(reply_msg, text)
                media_files = await save_media_from_message(client, reply_msg, template_name, clear_existing=True)

            cmd_text, cmd_entities = extract_payload_and_entities(event.message, raw, folder_name)
            if cmd_text:
                text = cmd_text
                entities_hex = cmd_entities
                disable_preview = 0
        else:
            text, entities_hex = extract_payload_and_entities(event.message, raw, folder_name)
            if getattr(event.message, "media", None):
                media_files = await save_media_from_message(client, event.message, template_name, clear_existing=True)
            if not media_files:
                disable_preview = _preview_disabled(event.message, text)

        text, buttons_rows = _strip_trailing_buttons(text)

        existing = db.get_template(template_name)
        named_rot = db.get_named_rotation(template_name, account_id=my_id)
        if not text and not media_files:
            if existing:
                text = existing["text"]
                entities_hex = existing["entities_hex"]
                media_files = existing["media_files"]
                buttons_rows = existing.get("buttons") or []
                disable_preview = int(existing.get("disable_preview") or 0)
            elif named_rot:
                pass
            else:
                await _notify(event, "⚠️ Нет текста или медиа. Ответьте командой на сообщение с рекламой или укажите текст со следующей строки.")
                return

        existing_bundle_json = json.dumps(existing["bundle"], ensure_ascii=False) if existing and existing.get("bundle") else ""
        content_is_new = bool(text or media_files) and not (
            existing and text == existing["text"] and media_files == existing["media_files"]
            and entities_hex == existing["entities_hex"]
        )
        if content_is_new:
            # Only when new content was given: re-saving the old text used to
            # wipe the saved multi-message bundle, so a pack of posts turned
            # into its first message only.
            db.save_template(
                template_name, text, entities_hex, media_files,
                bundle_json=existing_bundle_json,
                buttons_json=buttons_to_json(buttons_rows),
                disable_preview=disable_preview,
            )
        elif existing and (buttons_rows or disable_preview):
            db.save_template(
                template_name, existing["text"], existing["entities_hex"], existing["media_files"],
                bundle_json=existing_bundle_json,
                buttons_json=buttons_to_json(buttons_rows) or buttons_to_json(existing.get("buttons")),
                disable_preview=disable_preview or int(existing.get("disable_preview") or 0),
            )

        target_chats = []
        if folder_name:
            target_chats = await get_chats_in_folder(client, folder_name)
            if not target_chats:
                await _notify(event, f"⚠️ Папка \"{folder_name}\" не найдена или пуста.")
                return
        else:
            target_chats = [event.chat_id]

        for cid in target_chats:
            db.add_or_update_broadcast(
                account_id=my_id,
                chat_id=cid,
                template_name=template_name,
                mode=mode,
                interval_seconds=interval_sec,
                counter_threshold=threshold_count,
                folder_name=folder_name
            )

        if folder_name:
            db.register_folder_broadcast(
                folder_name=folder_name,
                template_name=template_name,
                mode=mode,
                interval_seconds=interval_sec,
                counter_threshold=threshold_count,
                account_id=my_id
            )

        if mode == "interval":
            details = f"каждые {_format_seconds(interval_sec)}"
        elif mode == "hybrid":
            details = f"через {threshold_count} соо (кд {_format_seconds(interval_sec)})"
        else:
            details = f"через каждые {threshold_count} соо"

        rot_note = f" (чередование **{template_name}**)" if named_rot else ""
        target_info = f"в папке \"{folder_name}\" ({len(target_chats)} чатов)" if folder_name else "в этом чате"
        await _notify(event, f"✅ Рассылка{rot_note} **{template_name}** запущена ({details}) {target_info}.")

    async def handle_rotation_create(event: Any, raw: str):
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        first_line = lines[0]
        cmd_tokens = first_line.split()
        cmd = cmd_tokens[0].lower()

        if len(lines) > 1:
            if len(cmd_tokens) > 1:
                name = cmd_tokens[1].strip("<>:").strip()
                templates = [l.strip("<>").strip() for l in lines[1:] if l.strip("<>").strip()]
                if not templates:
                    await _notify(event, "⚠️ Укажите названия рассылок для чередования со следующих строк.")
                    return
                db.set_named_rotation(name, templates, chat_id=event.chat_id, account_id=my_id)
                joined = " ➔ ".join(templates)
                await _notify(event, f"✅ Создано чередование **{name}**:\n{joined}\n\nЗапуск: `.рассыл <время/соо> {name}`")
                return
            else:
                templates = [l.strip("<>").strip() for l in lines[1:] if l.strip("<>").strip()]
                if not templates:
                    await _notify(event, "⚠️ Укажите названия рассылок для чередования со следующих строк.")
                    return
                db.set_chat_rotation(event.chat_id, templates, account_id=my_id)
                joined = " ➔ ".join(templates)
                await _notify(event, f"✅ Чередование настроено для этого чата:\n{joined}")
                return
        else:
            args = cmd_tokens[1:]
            if not args:
                await _notify(event, "⚠️ Использование:\n• `.чередовать <название> <пост1> <пост2>...`\n• `.чередование <название> <пост1> <пост2>...`\n• `.чередовать` (со следующей строки посты для этого чата)")
                return

            is_explicit_named_cmd = cmd in (".чередование", ".ротация", ".создать-чередование", ".create-rotation", ".rotation")
            if is_explicit_named_cmd or len(args) >= 3 or (len(args) == 2 and not (db.get_template(args[0]) and db.get_template(args[1]))):
                name = args[0].strip("<>:").strip()
                templates = [n.strip("<>").strip() for n in args[1:] if n.strip("<>").strip()]
                if not templates:
                    await _notify(event, f"⚠️ Укажите шаблоны для чередования **{name}**.")
                    return
                db.set_named_rotation(name, templates, chat_id=event.chat_id, account_id=my_id)
                joined = " ➔ ".join(templates)
                await _notify(event, f"✅ Создано чередование **{name}**:\n{joined}\n\nЗапуск: `.рассыл <время/соо> {name}`")
            else:
                templates = [n.strip("<>").strip() for n in args if n.strip("<>").strip()]
                db.set_chat_rotation(event.chat_id, templates, account_id=my_id)
                joined = " ➔ ".join(templates)
                await _notify(event, f"✅ Чередование настроено для этого чата:\n{joined}")

    async def handle_delete_rotation(event: Any, parts: List[str]):
        if len(parts) < 2:
            db.delete_chat_rotation(chat_id=event.chat_id, account_id=my_id)
            await _notify(event, "🗑 Чередование для этого чата удалено.")
            return

        target_name = parts[1].strip("<>").strip()
        if target_name.lower() in ("все", "all"):
            db.delete_all_named_rotations(account_id=my_id)
            db.delete_chat_rotation(chat_id=event.chat_id, account_id=my_id)
            await _notify(event, "🗑 Все чередования удалены.")
            return

        deleted = db.delete_named_rotation(target_name, account_id=my_id)
        if deleted:
            await _notify(event, f"🗑 Чередование **{target_name}** удалено.")
        else:
            rot = db.get_chat_rotation(event.chat_id, account_id=my_id)
            if rot:
                db.delete_chat_rotation(chat_id=event.chat_id, account_id=my_id)
                await _notify(event, f"🗑 Чередование для этого чата удалено.")
            else:
                await _notify(event, f"⚠️ Чередование **{target_name}** не найдено.")

    async def handle_buttons_command(event: Any, raw: str):
        """`.кнопки <пост>` — задать инлайн-кнопки и их раскладку."""
        lines = raw.splitlines()
        words = lines[0].split()
        if len(words) < 2:
            await _notify(
                event,
                "⚠️ Формат: `.кнопки <название поста>`\n"
                "Потом пришли одним сообщением раскладку, по строке на ряд:\n"
                "`[Купить](https://t.me/manager) || [Прайс](https://t.me/price)`\n"
                "`[Написать](cb:hello)`\n"
                "`cb:` — callback-кнопка, без него — ссылка.\n"
                "`.кнопки очистить <название>` убирает кнопки.",
            )
            return
        if words[1].lower() in ("очистить", "clear", "удалить"):
            name = " ".join(words[2:]).strip("<>\"' ")
            tpl = db.get_template(name) if name else None
            if not tpl:
                await _notify(event, "⚠️ Укажи название поста: `.кнопки очистить promo`")
                return
            db.save_template(
                name, tpl["text"], tpl["entities_hex"], tpl["media_files"],
                bundle_json=json.dumps(tpl["bundle"], ensure_ascii=False) if tpl.get("bundle") else "",
                buttons_json="", disable_preview=tpl.get("disable_preview") or 0,
            )
            await _notify(event, f"🧹 Кнопки у поста **{name}** убраны.")
            return

        name = " ".join(words[1:]).strip("<>\"' ")
        tpl = db.get_template(name)
        if not tpl:
            await _notify(event, f"⚠️ Пост **{name}** не найден. Сначала создай рассылку с этим названием.")
            return

        from cole.buttons import ButtonError, parse_row
        rows: List[Any] = []
        try:
            for line in lines[1:]:
                if not line.strip():
                    continue
                row = parse_row(line)
                if row:
                    rows.append(row)
        except ButtonError as e:
            await _notify(event, f"⚠️ Кнопки не разобраны: {e}")
            return

        if rows:
            db.save_template(
                name, tpl["text"], tpl["entities_hex"], tpl["media_files"],
                bundle_json=json.dumps(tpl["bundle"], ensure_ascii=False) if tpl.get("bundle") else "",
                buttons_json=buttons_to_json(rows), disable_preview=tpl.get("disable_preview") or 0,
            )
            await _notify(event, f"✅ Кнопки сохранены:\n{describe_buttons(rows)}")
            return

        ACTIVE_COLLECTORS[(my_id, event.chat_id)] = {
            "account_id": my_id,
            "chat_id": event.chat_id,
            "template_name": name,
            "mode": "buttons",
            "interval_seconds": 0,
            "counter_threshold": 0,
            "folder_name": "",
            "session_type": "buttons",
            "items": [],
            "started_at": time.time(),
            "last_active": time.time(),
        }
        await _notify(
            event,
            f"🔘 Пришли раскладку кнопок для **{name}** одним сообщением.\n"
            "Одна строка — один ряд, кнопки в ряду через `||`:\n"
            "`[Купить](https://t.me/manager) || [Прайс](https://t.me/price)`\n"
            "`[Написать](cb:hello)`",
            auto_delete=0,
        )

    async def handle_preview_command(event: Any, raw: str):
        """`.превью вкл|выкл <пост>` — превью ссылок при рассылке."""
        words = raw.split()
        if len(words) < 3:
            await _notify(event, "⚠️ Формат: `.превью выкл promo` или `.превью вкл promo`")
            return
        state = words[1].lower()
        name = " ".join(words[2:]).strip("<>\"' ")
        tpl = db.get_template(name)
        if not tpl:
            await _notify(event, f"⚠️ Пост **{name}** не найден.")
            return
        value = {"выкл": 1, "off": 1, "0": 1, "вкл": 0, "on": 0, "1": 0}.get(state)
        if value is None:
            await _notify(event, "⚠️ Вторым словом должно быть `вкл` или `выкл`.")
            return
        db.save_template(
            name, tpl["text"], tpl["entities_hex"], tpl["media_files"],
            bundle_json=json.dumps(tpl["bundle"], ensure_ascii=False) if tpl.get("bundle") else "",
            buttons_json=buttons_to_json(tpl.get("buttons")), disable_preview=value,
        )
        await _notify(event, f"{'🚫 Превью ссылок выключено' if value else '🖼 Превью ссылок включено'} для **{name}**.")

    async def _resolve_mute_target(event: Any, raw_args: str) -> Optional[Dict[str, Any]]:
        """
        Resolve a mute target from a command argument.

        Accepted forms, in priority order:
          .мутить                    -> reply to the message (recommended)
          .мутить @username          -> resolve the handle
          .мутить 123456789          -> bare user id
          .мутить 123456789 причина  -> bare user id plus a stored reason
        """
        args = raw_args.strip()
        reason = ""
        parts = [p for p in args.split() if p]
        if len(parts) > 1 and re.fullmatch(r"-?\d{5,}", parts[0]):
            reason = " ".join(parts[1:]).strip()

        # 1. Reply form wins: it is the only unambiguous source of identity.
        if event.is_reply:
            try:
                reply_msg = await event.get_reply_message()
            except Exception:
                reply_msg = None
            if reply_msg is not None:
                sender_id = getattr(reply_msg, "sender_id", None)
                if sender_id is None:
                    return None
                peer_key = _strip_peer_id(sender_id)
                display_name = ""
                username = ""
                try:
                    sender = await reply_msg.get_sender()
                    display_name = getattr(sender, "title", None) or " ".join(
                        filter(None, [getattr(sender, "first_name", None), getattr(sender, "last_name", None)])
                    )
                    username = getattr(sender, "username", None) or ""
                except Exception:
                    pass
                if not reason:
                    reason = (reply_msg.raw_text or "")[:80].strip()
                return {
                    "peer_id": sender_id,
                    "peer_key": peer_key,
                    "username": username,
                    "display_name": display_name or f"id {peer_key}",
                    "scope": "user",
                    "reason": reason,
                }

        if not parts:
            return None

        token = parts[0]

        # 2. Numeric id
        if re.fullmatch(r"-?\d{5,}", token):
            raw_id = int(token)
            peer_key = _strip_peer_id(raw_id)
            display_name = f"id {peer_key}"
            username = ""
            try:
                entity = await client.get_entity(peer_key)
                display_name = (
                    getattr(entity, "title", None)
                    or " ".join(filter(None, [getattr(entity, "first_name", None), getattr(entity, "last_name", None)]))
                    or display_name
                )
                username = getattr(entity, "username", None) or ""
            except Exception:
                pass
            return {
                "peer_id": raw_id,
                "peer_key": peer_key,
                "username": username,
                "display_name": display_name,
                "scope": "user",
                "reason": reason,
            }

        # 3. Username
        if token.startswith("@") or re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{3,31}", token):
            handle = token.lstrip("@")
            try:
                entity = await client.get_entity(handle)
            except Exception:
                return None
            raw_id = utils.get_peer_id(entity)
            peer_key = _strip_peer_id(raw_id)
            display_name = (
                getattr(entity, "title", None)
                or " ".join(filter(None, [getattr(entity, "first_name", None), getattr(entity, "last_name", None)]))
                or f"@{handle}"
            )
            return {
                "peer_id": raw_id,
                "peer_key": peer_key,
                "username": getattr(entity, "username", None) or handle,
                "display_name": display_name,
                "scope": "user",
                "reason": reason,
            }

        return None

    async def handle_mute(event: Any, raw: str):
        _, args = _extract_quoted_folder(raw)
        args = _strip_command_word(args).strip()
        words = [w for w in args.split() if w]
        action = "silent"
        rest_words: List[str] = []
        chat_scope = False
        for word in words:
            low = word.lower()
            if low in MUTE_ACTION_ALIASES:
                action = MUTE_ACTION_ALIASES[low]
                continue
            if low in ("чат", "chat", "беседа"):
                chat_scope = True
                continue
            rest_words.append(word)
        rest = " ".join(rest_words).strip()

        if chat_scope:
            title = ""
            try:
                entity = await event.get_chat()
                title = getattr(entity, "title", "") or ""
            except Exception:
                pass
            target = {
                "peer_id": event.chat_id,
                "peer_key": event.chat_id,
                "username": "",
                "display_name": title or f"чат {event.chat_id}",
                "scope": "chat",
                "reason": rest,
            }
        else:
            target = await _resolve_mute_target(event, rest)

        if not target:
            await _notify(
                event,
                "⚠️ Не понял кого мутить.\n"
                "Формы:\n"
                "• `.мутить` — ответьте командой на сообщение\n"
                "• `.мутить @username`\n"
                "• `.мутить 123456789`\n"
                "• `.мутить @username удалить` — удалять его сообщения\n"
                "• `.мутить @username варн` — предупреждать в ответ\n"
                "• `.мутить @username бан` — снимать право писать (нужны права)\n"
                "• `.мутить чат` — тишина в этом чате",
            )
            return

        added = db.add_muted_peer(
            peer_id=target["peer_id"],
            account_id=my_id,
            peer_key=target["peer_key"],
            username=target["username"],
            display_name=target["display_name"],
            scope=target["scope"],
            reason=target["reason"],
            action=action,
        )
        mute_cache_rebuild(my_id)
        verb = "Заглушен" if added else "Обновлён мьют"
        action_hint = {
            "silent": "сообщения помечаются прочитанными, пинг снимается",
            "delete": "сообщения удаляются",
            "warn": "в ответ уходит предупреждение",
            "ban": "снимается право писать в чате",
        }.get(action, action)
        reason_str = f"\nПричина: {target['reason']}" if target["reason"] else ""
        await _notify(event, f"🔇 {verb}: **{target['display_name']}**\nРежим: {action_hint}{reason_str}")

    async def handle_unmute(event: Any, raw: str):
        _, args = _extract_quoted_folder(raw)
        args_clean = _strip_command_word(args).strip()
        if not args_clean:
            await _notify(event, "⚠️ Укажите @username или id, либо ответьте командой на сообщение.")
            return

        if args_clean.lower() in ("чат", "chat", "беседа"):
            removed = db.remove_muted_peer(event.chat_id, account_id=my_id, scope="chat")
            mute_cache_rebuild(my_id)
            if removed:
                await _notify(event, "🔊 Чат разглушен.")
            else:
                await _notify(event, "ℹ️ Этот чат не был заглушен.")
            return

        target = await _resolve_mute_target(event, args_clean)
        if target:
            removed = db.remove_muted_peer(target["peer_key"], account_id=my_id, scope=target["scope"])
        else:
            token = args_clean.split()[0].lstrip("@")
            found = db.find_muted_peer_by_username(token, account_id=my_id)
            if found:
                removed = db.remove_muted_peer(found["peer_key"], account_id=my_id, scope=found.get("scope") or "user")
                target = {"display_name": found.get("display_name") or f"@{token}"}
            else:
                removed = 0
                target = {"display_name": token}

        mute_cache_rebuild(my_id)
        if removed:
            await _notify(event, f"🔊 Разглушен: **{target['display_name']}**")
        else:
            await _notify(event, f"ℹ️ **{target['display_name']}** не был в списке заглушенных.")

    async def handle_mute_list(event: Any):
        rows = db.list_muted_peers(account_id=my_id)
        if not rows:
            await _notify(event, "🔇 Список заглушенных пуст.")
            return
        lines = ["🔇 **Заглушенные:**\n"]
        mode_titles = {"silent": "тихо", "delete": "удаление", "warn": "варн", "ban": "бан"}
        for r in rows[:50]:
            handle = f"@{r['username']}" if r["username"] else f"id {r['peer_key']}"
            label = r["display_name"] or handle
            reason = f" — {r['reason']}" if r["reason"] else ""
            mode = mode_titles.get(r.get("action") or "silent", "тихо")
            scope = "чат" if (r.get("scope") or "user") == "chat" else "юзер"
            lines.append(f"• {label} (`{handle}`, {scope}, {mode}){reason}")
        if len(rows) > 50:
            lines.append(f"\n…и ещё {len(rows) - 50}")
        await _notify(event, "\n".join(lines), auto_delete=25)

    async def handle_list_rotations(event: Any):
        named = db.list_named_rotations(account_id=my_id)
        chat_rot = db.get_chat_rotation(event.chat_id, account_id=my_id)

        if not named and not chat_rot:
            await _notify(event, "🔄 Нет активных чередований.\nСоздать: `.чередовать <название> <пост1> <пост2>`")
            return

        lines = ["🔄 **Чередования постов:**\n"]
        if named:
            lines.append("**Именованные (для любых чатов/папок):**")
            for r in named:
                seq = " ➔ ".join(r["template_names"])
                curr = r["template_names"][r["current_index"] % len(r["template_names"])] if r["template_names"] else "—"
                lines.append(f"• **{r['name']}**: {seq} (след: `{curr}`)")

        if chat_rot and chat_rot.get("template_names"):
            lines.append("\n**Текущий чат:**")
            seq = " ➔ ".join(chat_rot["template_names"])
            curr = chat_rot["template_names"][chat_rot["current_index"] % len(chat_rot["template_names"])] if chat_rot["template_names"] else "—"
            lines.append(f"• {seq} (след: `{curr}`)")

        await _notify(event, "\n".join(lines), auto_delete=20)

    _HERE_WORDS = ("тут", "здесь", "here")

    def _parse_scope(raw: str) -> Tuple[str, str, bool, bool]:
        """
        (target_name, folder_name, here, explicit_name) for .стоп/.продолжить/.удалить.

        .стоп X            -> X everywhere (every chat and folder)
        .стоп X "папка"    -> X only in that folder
        .стоп X тут        -> X only in this chat
        .стоп все          -> everything of this account
        .стоп              -> everything in this chat
        """
        folder_name, remaining = _extract_quoted_folder(raw.splitlines()[0] if raw else "")
        tokens = remaining.split()[1:]
        here = any(t.lower() in _HERE_WORDS for t in tokens)
        tokens = [t for t in tokens if t.lower() not in _HERE_WORDS]
        if tokens:
            return tokens[0].strip("<>").strip(), folder_name, here, True
        # No name: the current chat (or the folder, if one was given).
        return "все", folder_name, not folder_name, False

    def _scope_label(target_name: str, folder_name: str, here: bool) -> str:
        what = "все рассылки" if target_name.lower() in ("все", "all") else f"**{target_name}**"
        if folder_name:
            return f"{what} в папке \"{folder_name}\""
        if here:
            return f"{what} в этом чате"
        return f"{what} во всех чатах и папках"

    async def handle_stop(event: Any, parts: List[str], raw: str):
        target_name, folder_name, here, _ = _parse_scope(raw)
        is_all = target_name.lower() in ("все", "all")
        target_chats = (await get_chats_in_folder(client, folder_name)) if folder_name else []
        chat_scope = [event.chat_id] if here else (target_chats or None)

        count = db.stop_tasks(
            account_id=my_id,
            name=target_name,
            chat_ids=chat_scope,
            folder_name=folder_name or None,
            manual=here,
        )
        if not here:
            db.set_folder_broadcast_status(folder_name=folder_name or None, name=target_name, is_active=0, account_id=my_id)
        if is_all:
            db.set_rotation_status(
                account_id=my_id,
                chat_id=event.chat_id if here else None,
                chat_ids=target_chats if folder_name else None,
                is_active=0,
            )
        elif not here and not folder_name and db.get_named_rotation(target_name, account_id=my_id):
            with db._conn() as conn:
                conn.execute(
                    "UPDATE chat_rotations SET is_active = 0 WHERE (name = ? OR name = ?) AND (account_id = ? OR account_id = 0)",
                    (target_name, f"<{target_name}>", my_id),
                )
        await _notify(event, f"⏹ Остановлено: {_scope_label(target_name, folder_name, here)} (задач: {count})")

    async def handle_resume(event: Any, parts: List[str], raw: str):
        target_name, folder_name, here, _ = _parse_scope(raw)
        is_all = target_name.lower() in ("все", "all")
        target_chats = (await get_chats_in_folder(client, folder_name)) if folder_name else []
        chat_scope = [event.chat_id] if here else (target_chats or None)

        count = db.resume_tasks(
            account_id=my_id,
            name=target_name,
            chat_ids=chat_scope,
            folder_name=folder_name or None,
        )
        if not here:
            db.set_folder_broadcast_status(folder_name=folder_name or None, name=target_name, is_active=1, account_id=my_id)
        if is_all:
            db.set_rotation_status(
                account_id=my_id,
                chat_id=event.chat_id if here else None,
                chat_ids=target_chats if folder_name else None,
                is_active=1,
            )
        elif not here and not folder_name:
            with db._conn() as conn:
                conn.execute(
                    "UPDATE chat_rotations SET is_active = 1 WHERE (name = ? OR name = ?) AND (account_id = ? OR account_id = 0)",
                    (target_name, f"<{target_name}>", my_id),
                )
        active_b = getattr(client, "_colemailer_broadcaster", None) or getattr(client, "_spambuster_broadcaster", broadcaster)
        try:
            active_b.request_folder_sync()
        except Exception:
            pass
        await _notify(event, f"▶️ Возобновлено: {_scope_label(target_name, folder_name, here)} (задач: {count})")

    async def handle_delete(event: Any, parts: List[str], raw: str):
        target_name, folder_name, here, _ = _parse_scope(raw)
        is_all = target_name.lower() in ("все", "all")
        target_chats = (await get_chats_in_folder(client, folder_name)) if folder_name else []
        chat_scope = [event.chat_id] if here else (target_chats or None)

        count = db.delete_tasks(
            account_id=my_id,
            name=target_name,
            chat_ids=chat_scope,
            folder_name=folder_name or None,
            keep_folder_tombstones=here,
        )

        if here:
            if is_all:
                db.delete_chat_rotation(chat_id=event.chat_id, account_id=my_id)
        else:
            db.delete_folder_broadcasts(folder_name=folder_name or None, name=target_name, account_id=my_id)
            if is_all and not folder_name:
                for tpl in db.list_templates():
                    db.delete_template(tpl["name"])
                db.delete_chat_rotation(account_id=my_id)
                db.delete_all_named_rotations(account_id=my_id)
            elif is_all and folder_name:
                db.delete_chat_rotation(chat_ids=target_chats, account_id=my_id)
            elif not folder_name:
                # ".удалить X": X is gone everywhere - template, tasks, rotation.
                db.delete_template(target_name)
                db.delete_named_rotation(target_name, account_id=my_id)

        if not is_all and (here or folder_name) and db.count_live_tasks_for_template(target_name) == 0:
            # Nothing uses the post any more: drop it so it cannot come back.
            if not db.get_named_rotation(target_name, account_id=my_id):
                db.delete_template(target_name)

        await _notify(event, f"🗑 Удалено: {_scope_label(target_name, folder_name, here)} (задач: {count})")

    async def handle_list_all(event: Any):
        """Every broadcast of this account in every chat: finds forgotten ones."""
        tasks = [t for t in db.list_all_tasks(account_id=my_id) if not t.get("manual_stop")]
        folders = db.list_folder_broadcasts(account_id=my_id)
        if not tasks and not folders:
            await _notify(event, "📭 Рассылок нет ни в одном чате.", auto_delete=15)
            return

        groups: Dict[str, List[Dict[str, Any]]] = {}
        for t in tasks:
            groups.setdefault(t["template_name"], []).append(t)

        lines = ["📋 **Все рассылки аккаунта (во всех чатах):**\n"]
        for name in sorted(set(groups) | {f["template_name"] for f in folders}):
            items = groups.get(name, [])
            active = [t for t in items if t["is_active"]]
            sample = (active or items or [{}])[0]
            mode = sample.get("mode") or next((f["mode"] for f in folders if f["template_name"] == name), "")
            if mode == "interval":
                mode_str = f"каждые {_format_seconds(int(sample.get('interval_seconds') or 0))}"
            elif mode == "hybrid":
                mode_str = f"через {sample.get('counter_threshold')} соо (кд {_format_seconds(int(sample.get('interval_seconds') or 0))})"
            elif mode == "counter":
                mode_str = f"через {sample.get('counter_threshold')} соо"
            else:
                mode_str = "—"
            fnames = sorted({f["folder_name"] for f in folders if f["template_name"] == name and f["is_active"]})
            folder_str = f" | папки: {', '.join(fnames)}" if fnames else ""
            status = "🟢" if active else "🔴"
            lines.append(f"{status} **{name}** — {mode_str} | активных чатов: {len(active)}/{len(items)}{folder_str}")
            titles = []
            for t in active[:5]:
                title = str(t["chat_id"])
                try:
                    ent = await client.get_entity(t["chat_id"])
                    title = getattr(ent, "title", None) or getattr(ent, "first_name", None) or title
                except Exception:
                    pass
                titles.append(title)
            if titles:
                more = f" и ещё {len(active) - 5}" if len(active) > 5 else ""
                lines.append(f"   ↳ {', '.join(titles)}{more}")
        lines.append("\nУдалить везде: `.удалить <название>` · только тут: `.удалить <название> тут`")
        await _notify(event, "\n".join(lines), auto_delete=60)

    async def handle_view(event: Any, parts: List[str]):
        if len(parts) < 2:
            await _notify(event, "⚠️ Укажите название рассылки или `все`.")
            return

        target = parts[1].strip("<>").strip()
        if target.lower() in ("все", "all"):
            tasks = db.get_chat_broadcasts(event.chat_id, account_id=my_id)
            if not tasks:
                await _notify(event, "В этом чате нет активных рассылок.")
                return

            lines = ["**📋 Рассылки в этом чате:**\n"]
            for t in tasks:
                status = "🟢 Вкл" if t["is_active"] else "🔴 Выкл"
                if t["mode"] == "interval":
                    mode_str = f"каждые {_format_seconds(t['interval_seconds'])}"
                elif t["mode"] == "hybrid":
                    mode_str = f"через {t['counter_threshold']} соо (кд {_format_seconds(t['interval_seconds'])})"
                else:
                    mode_str = f"через {t['counter_threshold']} соо"
                folder_str = f" (папка: {t['folder_name']})" if t["folder_name"] else ""

                named_rot = db.get_named_rotation(t["template_name"], account_id=my_id)
                rot_info = f" [чередование: {' ➔ '.join(named_rot['template_names'])}]" if named_rot else ""
                lines.append(f"• **{t['template_name']}**{rot_info} — {status} | {mode_str}{folder_str}")

            rot = db.get_chat_rotation(event.chat_id, account_id=my_id)
            if rot and rot.get("template_names"):
                seq = " ➔ ".join(rot["template_names"])
                lines.append(f"\n🔄 **Очередь чередования этого чата:** {seq}")

            named_rots = db.list_named_rotations(account_id=my_id)
            if named_rots:
                lines.append("\n🔄 **Все сохраненные чередования:**")
                for nr in named_rots:
                    seq = " ➔ ".join(nr["template_names"])
                    lines.append(f"• **{nr['name']}**: {seq}")

            await _notify(event, "\n".join(lines), auto_delete=20)
        else:
            named_rot = db.get_named_rotation(target, account_id=my_id)
            if named_rot:
                tpls = named_rot["template_names"]
                seq = " ➔ ".join(tpls)
                next_tpl = db.get_next_rotation_template(account_id=my_id, rotation_name=target)
                await _notify(event, f"🔄 Чередование **{target}**: {seq}\n👁 Тестовый предпросмотр: **{next_tpl}** (отправляю ниже)", auto_delete=5)
                if next_tpl:
                    tpl_data = db.get_template(next_tpl)
                    if tpl_data:
                        await send_broadcast_post(
                            client,
                            event.chat_id,
                            text=tpl_data["text"],
                            entities_hex=tpl_data["entities_hex"],
                            media_files=tpl_data["media_files"],
                            bundle=tpl_data.get("bundle"),
                            buttons=tpl_data.get("buttons"),
                            disable_preview=bool(tpl_data.get("disable_preview")),
                        )
                return

            tpl = db.get_template(target)
            if not tpl:
                await _notify(event, f"⚠️ Рассылка с именем **{target}** не найдена.")
                return

            await _notify(event, f"👁 Тестовый предпросмотр: **{target}** (отправляю ниже)", auto_delete=3)
            await send_broadcast_post(
                client,
                event.chat_id,
                text=tpl["text"],
                entities_hex=tpl["entities_hex"],
                media_files=tpl["media_files"],
                bundle=tpl.get("bundle"),
                buttons=tpl.get("buttons"),
                disable_preview=bool(tpl.get("disable_preview")),
            )

# Мост для Android/UI: приложение подставляет свои функции ввода, потому что
# stdin в APK нет. Формат: callable(prompt: str) -> str.
CODE_PROVIDER = None
PASSWORD_PROVIDER = None


def _prompt(prompt: str, secret: bool = False) -> str:
    provider = PASSWORD_PROVIDER if secret else CODE_PROVIDER
    if provider is not None:
        return str(provider(prompt) or "")
    if not sys.stdin.isatty():
        raise RuntimeError("нужен ввод с клавиатуры, но консоли нет")
    return getpass.getpass(prompt) if secret else input(prompt)


async def authenticate_client(client: TelegramClient, phone_cfg: str, acc_name: str = "default"):
    await client.connect()
    if await client.is_user_authorized():
        return

    phone = phone_cfg.strip()
    if not phone:
        phone = _prompt(f"[{acc_name}] Введите номер телефона (с кодом страны, напр. +79991234567): ").strip()

    print(f"[{acc_name}] Отправка кода подтверждения на номер {phone}...")
    await client.send_code_request(phone)
    code = _prompt(f"[{acc_name}] Введите код из Telegram: ").strip()

    try:
        await client.sign_in(phone=phone, code=code)
    except SessionPasswordNeededError:
        print(f"[{acc_name}] На аккаунте включена двухфакторная аутентификация (2FA).")
        password = _prompt(f"[{acc_name}] Введите облачный пароль (2FA): ", secret=True)
        await client.sign_in(password=password)

# ---------------------------------------------------------------------------
# Single instance per Telegram account.
#
# Two copies of the bot on the same account (autostart + a manual start, an
# old copy in another folder, Termux + the APK...) each run their own
# scheduler: every post is sent twice, and the old copy keeps sending
# broadcasts that were deleted in the new one ("phantom" broadcasts).
# An OS-level lock keyed by the Telegram user id makes the second copy exit.
# ---------------------------------------------------------------------------
_INSTANCE_LOCKS: Dict[str, Any] = {}


def _instance_lock_path(key: str) -> Path:
    import tempfile
    return Path(tempfile.gettempdir()) / f"colemailer_{re.sub(r'[^A-Za-z0-9_]', '_', key)}.lock"


def acquire_instance_lock(key: str) -> bool:
    """True when this process now owns `key`; False when another copy runs."""
    if key in _INSTANCE_LOCKS:
        return False
    try:
        fh = open(_instance_lock_path(key), "a+")
    except Exception:
        return True  # cannot even create the file: do not block the bot
    try:
        if os.name == "nt":
            import msvcrt
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (OSError, IOError):
        try:
            fh.close()
        except Exception:
            pass
        return False
    except Exception:
        pass  # locking not supported on this platform
    _INSTANCE_LOCKS[key] = fh
    return True


def release_instance_lock(key: str):
    fh = _INSTANCE_LOCKS.pop(key, None)
    if fh is not None:
        try:
            fh.close()
        except Exception:
            pass


HEALTH_CHECK_SECONDS = 180
HEALTH_CHECK_TIMEOUT = 25


async def connection_watchdog(client: TelegramClient, label: str = ""):
    """
    Telegram silently stops pushing updates to a client that looks idle, and
    a socket can die without the library noticing (NAT timeout, Wi-Fi <->
    mobile switch, laptop sleep). Each 3 minutes make a real request; two
    failures in a row force a reconnect — but never in the middle of a send.
    """
    from telethon.tl.functions.updates import GetStateRequest
    failures = 0
    while True:
        await asyncio.sleep(HEALTH_CHECK_SECONDS)
        try:
            if not client.is_connected():
                raise ConnectionError("not connected")
            await asyncio.wait_for(client(GetStateRequest()), timeout=HEALTH_CHECK_TIMEOUT)
            failures = 0
        except asyncio.CancelledError:
            raise
        except Exception as e:
            failures += 1
            if failures >= 2:
                broadcaster = getattr(client, "_colemailer_broadcaster", None)
                if broadcaster is not None and getattr(broadcaster, "_sending_chats", None):
                    # Не рвать соединение посреди отправки: это даёт дубли.
                    failures = 1
                    continue
                log_error(f"[WATCHDOG]{label} Соединение не отвечает ({type(e).__name__}). Переподключение...")
                failures = 0
                try:
                    await client.disconnect()
                except Exception:
                    pass


async def run_single_account(acc_cfg: Dict[str, Any]):
    acc_name = acc_cfg.get("name", "default")
    api_id = acc_cfg.get("api_id")
    api_hash = acc_cfg.get("api_hash")

    if not api_id or not api_hash:
        log_error(f"[ERROR][{acc_name}] Не заполнены api_id и api_hash в config.txt")
        return

    session_name = acc_cfg.get("session_name") or f"session_{acc_name}"
    session_path = BASE_DIR / session_name
    client = TelegramClient(
        str(session_path),
        api_id,
        api_hash,
        catch_up=False,
        connection_retries=None,
        retry_delay=2,
        auto_reconnect=True,
        timeout=15,
        flood_sleep_threshold=60,
    )

    while True:
        try:
            await authenticate_client(client, acc_cfg.get("phone", ""), acc_name=acc_name)
            break
        except (ConnectionError, OSError, asyncio.TimeoutError) as conn_err:
            log_error(f"[START][{acc_name}] Ошибка сети (нет интернета / VPN): {conn_err}. Повторное подключение через 5с...")
            await asyncio.sleep(5)

    me = await client.get_me()
    username_str = f"@{me.username}" if me.username else me.first_name

    lock_key = f"acct_{me.id}"
    if not acquire_instance_lock(lock_key):
        log_error(
            f"[START][{acc_name}] Бот для аккаунта {username_str} уже запущен в другом окне/процессе. "
            f"Этот экземпляр закрывается, чтобы не было двойных рассылок. "
            f"Закрой старый (scripts/stop_*) и запусти заново, если нужно."
        )
        try:
            await client.disconnect()
        except Exception:
            pass
        return

    broadcaster = BroadcasterService(client, account_id=me.id)
    broadcaster.start()

    client._self_user = me
    register_events(client, broadcaster, me.id, acc_cfg=acc_cfg)

    print(f"✅ Аккаунт [{acc_name}] {username_str} (ID: {me.id}) подключен и запущен 24/7!")

    watchdog = asyncio.ensure_future(connection_watchdog(client, f"[{acc_name}]"))
    try:
        while True:
            try:
                if not client.is_connected():
                    await client.connect()
                await client.run_until_disconnected()
                await asyncio.sleep(2)
            except (ConnectionError, OSError, asyncio.TimeoutError) as e:
                log_error(f"[RECONNECT][{acc_name}] Потеря связи (VPN/сеть): {e}. Автоматический реконнект через 3с...")
                try:
                    await client.disconnect()
                except Exception:
                    pass
                await asyncio.sleep(3)
            except asyncio.CancelledError:
                break
            except (errors.AuthKeyUnregisteredError, errors.AuthKeyDuplicatedError, errors.UserDeactivatedError,
                    errors.UserDeactivatedBanError, errors.SessionRevokedError) as e:
                log_error(f"[FATAL][{acc_name}] Сессия недействительна ({type(e).__name__}). Удалите файл сессии и войдите заново.")
                break
            except Exception as e:
                log_error(f"[RECONNECT][{acc_name}] Неожиданная ошибка: {type(e).__name__}: {e}. Перезапуск через 10с...")
                try:
                    await client.disconnect()
                except Exception:
                    pass
                await asyncio.sleep(10)
    finally:
        watchdog.cancel()
        broadcaster.stop()
        release_instance_lock(lock_key)

def _write_credentials(api_id: int, api_hash: str, phone: str = ""):
    """Вписать ключи в config.txt, не ломая остальные настройки и аккаунты."""
    try:
        text = CONFIG_PATH.read_text(encoding="utf-8") if CONFIG_PATH.exists() else DEFAULT_CONFIG
    except Exception:
        text = DEFAULT_CONFIG
    lines = text.splitlines()
    has_sections = any(re.match(r"^\s*\[.+\]\s*$", l) for l in lines)

    if has_sections:
        # Ключи живут в первой секции аккаунта, а не в глобальной шапке.
        first = next(i for i, l in enumerate(lines) if re.match(r"^\s*\[.+\]\s*$", l))
        end = len(lines)
        for i in range(first + 1, len(lines)):
            if re.match(r"^\s*\[.+\]\s*$", lines[i]):
                end = i
                break
        section = lines[first + 1:end]
        tail = lines[end:]
        seen = {"api_id": False, "api_hash": False, "phone": False}
        new_section: List[str] = []
        for line in section:
            key = line.split("=", 1)[0].strip().lower() if "=" in line else ""
            if key == "api_id":
                new_section.append(f"api_id = {api_id}"); seen["api_id"] = True; continue
            if key == "api_hash":
                new_section.append(f"api_hash = {api_hash}"); seen["api_hash"] = True; continue
            if key == "phone" and phone:
                new_section.append(f"phone = {phone}"); seen["phone"] = True; continue
            new_section.append(line)
        added = []
        if not seen["api_id"]:
            added.append(f"api_id = {api_id}")
        if not seen["api_hash"]:
            added.append(f"api_hash = {api_hash}")
        if phone and not seen["phone"]:
            added.append(f"phone = {phone}")
        new_section[0:0] = added
        out = lines[:first + 1] + new_section + tail
        CONFIG_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")
        return

    in_first_section = False
    seen_id = seen_hash = False
    out = []
    for line in lines:
        stripped = line.strip()
        key = stripped.split("=", 1)[0].strip().lower() if "=" in stripped else ""
        if not in_first_section and key == "api_id":
            out.append(f"api_id = {api_id}"); seen_id = True; continue
        if not in_first_section and key == "api_hash":
            out.append(f"api_hash = {api_hash}"); seen_hash = True; continue
        if not in_first_section and key == "phone" and phone:
            out.append(f"phone = {phone}"); continue
        out.append(line)
    if not seen_id:
        out.insert(0, f"api_id = {api_id}")
    if not seen_hash:
        out.insert(1, f"api_hash = {api_hash}")
    if phone and not any(l.strip().lower().startswith("phone") for l in out):
        out.insert(2, f"phone = {phone}")
    CONFIG_PATH.write_text("\n".join(out) + "\n", encoding="utf-8")


def auto_api_setup(phone_hint: str = "") -> Optional[Dict[str, object]]:
    """Диалог авто-получения api_id/api_hash через my.telegram.org."""
    from cole.api_autoreg import ApiAuthError, MyTelegramAuth

    print("=" * 60)
    print("Получение api_id и api_hash через my.telegram.org")
    print("Код придёт в Telegram от официального сервиса (не SMS).")
    print("=" * 60)
    phone = (phone_hint or "").strip()
    if not phone:
        phone = _prompt("Номер телефона (+79991234567): ").strip()
    if not phone:
        print("Номер не указан.")
        return None

    auth = MyTelegramAuth()
    try:
        auth.send_code(phone)
        code = _prompt("Код из Telegram: ").strip()
        auth.sign_in(code)
        app = auth.fetch_app()
        if app:
            print("Приложение уже создано на аккаунте — забираю готовые ключи.")
        else:
            app = auth.create_app(title="Colemailer", shortname="colemailer")
            print("Приложение создано.")
        api_id = int(app["api_id"])
        api_hash = str(app["api_hash"])
        _write_credentials(api_id, api_hash, phone)
        print(f"Готово: api_id={api_id}, api_hash={api_hash[:6]}…")
        print(f"Записано в {CONFIG_PATH.name}")
        return {"api_id": api_id, "api_hash": api_hash, "phone": phone}
    except ApiAuthError as e:
        print(f"Не получилось: {e}")
        print("Можно сделать вручную: https://my.telegram.org -> API development tools")
        return None
    except (EOFError, KeyboardInterrupt):
        print("\nОтменено.")
        return None
    finally:
        auth.close()


async def main():
    accounts = CONFIG.get("accounts", [])
    if not accounts:
        accounts = [{
            "name": "default",
            "api_id": CONFIG.get("api_id"),
            "api_hash": CONFIG.get("api_hash"),
            "phone": CONFIG.get("phone", ""),
            "session_name": CONFIG.get("session_name", "session_userbot"),
            "auto_sub_folder": CONFIG.get("auto_sub_folder", "автосабнутое"),
            "auto_read_spam_pings": CONFIG.get("auto_read_spam_pings", True),
            "auto_sub_enabled": CONFIG.get("auto_sub_enabled", True),
        }]

    valid_accounts = [a for a in accounts if a.get("api_id") and a.get("api_hash")]

    if not valid_accounts:
        print("=" * 60)
        print("[!] В config.txt нет api_id и api_hash")
        print("Можно получить их автоматически — код придёт в Telegram.")
        print("=" * 60)

        if not sys.stdin.isatty():
            log_error("[ERROR] Ключей нет, а консоли для ввода нет. Заполни api_id/api_hash в config.txt.")
            return

        answer = input("Получить ключи автоматически через my.telegram.org? [д/н]: ").strip().lower()
        creds = None
        if answer in ("", "д", "да", "y", "yes"):
            creds = auto_api_setup()
        if not creds:
            raw_id = input("Или введите api_id прямо сейчас: ").strip()
            raw_hash = input("Введите api_hash прямо сейчас: ").strip()
            if raw_id.isdigit() and raw_hash:
                creds = {"api_id": int(raw_id), "api_hash": raw_hash, "phone": ""}
                _write_credentials(int(raw_id), raw_hash)
        if not creds:
            sys.exit(1)
        acc = {
            "name": "default",
            "api_id": creds["api_id"],
            "api_hash": creds["api_hash"],
            "phone": creds.get("phone") or "",
            "session_name": "session_userbot",
            "auto_sub_folder": "автосабнутое",
            "auto_read_spam_pings": True,
            "auto_sub_enabled": True,
        }
        valid_accounts = [acc]

    print("=" * 55)
    print(f"🚀 {APP_NAME} {APP_VERSION} — юзербот для Telegram (24/7)")
    print(f"📡 Активных аккаунтов в конфигурации: {len(valid_accounts)}")
    print(f"🔇 Режим скрытия спама в логах: {'ВКЛ (только ошибки)' if CONFIG.get('log_errors_only', True) else 'ВЫКЛ (полные логи)'}")
    print("💬 Команды: напишите .инструкция или .help в любом чате")
    print("=" * 55)

    tasks = [run_single_account(acc) for acc in valid_accounts]
    # return_exceptions: one broken account must not take the others down.
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for acc, res in zip(valid_accounts, results):
        if isinstance(res, BaseException) and not isinstance(res, asyncio.CancelledError):
            log_error(f"[FATAL][{acc.get('name')}] {type(res).__name__}: {res}")

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(prog="bot.py", description=f"{APP_NAME} — юзербот для Telegram")
    parser.add_argument("--auto-api", nargs="?", const="", metavar="PHONE",
                        help="получить api_id/api_hash через my.telegram.org")
    parser.add_argument("--version", action="store_true", help="показать версию")
    parser.add_argument("--check", action="store_true", help="проверить config.txt")
    args, _unknown = parser.parse_known_args()

    if args.version:
        print(f"{APP_NAME} {APP_VERSION}")
        sys.exit(0)

    if args.check:
        accounts = CONFIG.get("accounts") or []
        print(f"{APP_NAME} {APP_VERSION}")
        print(f"config: {CONFIG_PATH}")
        print(f"база:   {DB_PATH}")
        print(f"аккаунтов: {len(accounts)}")
        for a in accounts:
            ok = "ok" if (a.get("api_id") and a.get("api_hash")) else "нет api_id/api_hash"
            print(f"  • {a.get('name')}: {a.get('phone') or 'номер не задан'} — {ok}")
        sys.exit(0 if accounts else 2)

    if args.auto_api is not None:
        result = auto_api_setup(args.auto_api)
        sys.exit(0 if result else 2)

    try:
        asyncio.run(main())
    except (KeyboardInterrupt, SystemExit):
        pass
