"""Мост между Android-сервисом (Kotlin, Chaquopy) и bot.py.

Правила этого файла:

* ``kick`` / ``stop_bot`` / ``is_running`` / ``get_*_json`` вызываются из Kotlin
  с любого потока и обязаны быть быстрыми и потокобезопасными.
* ``start_bot`` держит свой поток всё время работы бота (внутри свой asyncio
  loop), как и раньше.
* ``auto_api`` блокирующая (HTTP к my.telegram.org): Kotlin запускает её в
  отдельном потоке, код подтверждения приходит через callback.
* Структурированные ответы отдаются строками JSON — их проще и безопаснее
  разбирать на стороне Kotlin, чем вложенные PyObject.

Ввод кода и пароля 2FA идёт через хуки bot.py (CODE_PROVIDER /
PASSWORD_PROVIDER). Хуки дергают ``callback.requestCode()`` /
``callback.requestPassword()``; ожидание живёт в сервисе (Kotlin AuthQueue),
поэтому погашенный экран или убитая Activity вход не ломают.
"""

from __future__ import annotations

import asyncio
import collections
import hashlib
import json
import os
import random
import re
import threading
import time
import traceback
from typing import Any, Dict, List, Optional

from telethon import TelegramClient, errors
from telethon.errors import SessionPasswordNeededError
from telethon.tl.functions.updates import GetStateRequest

import bot

# Имя файла сессии Telethon (SQLite с авторизационным ключом).
SESSION_NAME = "colemailer_session"

# Супервизор просыпается по таймауту только чтобы проверить ближайшую задачу;
# любой kick() из Kotlin (сеть/будильник/UI) будит его сразу.
SUPERVISOR_POLL_SECONDS = 30.0
# Проверка сессии настоящим запросом — только если апдейтов не было долго:
# живой поток апдейтов сам доказывает, что сокет жив.
IDLE_HEALTH_SECONDS = 300.0
HEALTH_CHECK_TIMEOUT = 25.0
RECONNECT_MAX_DELAY = 300.0

LOG_MAX_LINES = 500

_FATAL_AUTH_ERRORS = (
    errors.ApiIdInvalidError,
    errors.PhoneNumberInvalidError,
    errors.PhoneNumberBannedError,
    errors.PhoneCodeInvalidError,
    errors.PhoneCodeExpiredError,
    errors.PasswordHashInvalidError,
    errors.AuthKeyDuplicatedError,
    errors.AuthKeyUnregisteredError,
    errors.UserDeactivatedError,
    errors.UserDeactivatedBanError,
)

_client: Optional[TelegramClient] = None
_broadcaster = None
_loop: Optional[asyncio.AbstractEventLoop] = None
_is_running = False
_callback = None
_kick_event: Optional[asyncio.Event] = None
_bridge_lock = threading.Lock()

_storage_ready = False
_started_at = 0.0
_user_name = ""
_last_status = "Остановлен"
_next_due_ms: Optional[int] = None

_LOG_RING: "collections.deque" = collections.deque(maxlen=LOG_MAX_LINES)
_log_lock = threading.Lock()
_log_seq = 0


class _InputCancelled(Exception):
    """Пользователь не ввёл код/пароль или закрыл запрос."""


# --------------------------------------------------------------------------- лог
def log_line(level: str, message: str) -> None:
    """Положить строку в кольцевой буфер и отдать её в UI."""
    global _log_seq
    text = " ".join(str(message).split())
    if len(text) > 400:
        text = text[:400] + "…"
    line = "%s %-5s %s" % (time.strftime("%H:%M:%S"), level, text)
    with _log_lock:
        _log_seq += 1
        _LOG_RING.append((_log_seq, line))
    cb = _callback
    if cb is not None:
        try:
            cb.onLog(line)
        except Exception:
            pass
    if level in ("ERROR", "WARN"):
        print(line)


def get_logs_since(seq: int = 0) -> str:
    """Строки лога новее ``seq`` в виде JSON {"seq": N, "lines": [...]}."""
    try:
        since = int(seq)
    except Exception:
        since = 0
    with _log_lock:
        last = _log_seq
        lines = [line for number, line in _LOG_RING if number > since]
    return json.dumps({"seq": last, "lines": lines}, ensure_ascii=False)


# ------------------------------------------------------------------------ статус
def _status(text: str, running: bool = True) -> None:
    global _last_status
    _last_status = str(text)
    cb = _callback
    if cb is None:
        return
    try:
        cb.onStatusChange(str(text), bool(running))
    except Exception:
        pass


def _note_next_due(epoch_ms: Optional[int]) -> None:
    """Сообщить Kotlin точное время ближайшей задачи (для точного будильника)."""
    cb = _callback
    if cb is None or not epoch_ms:
        return
    try:
        cb.onNextDue(int(epoch_ms))
    except Exception:
        pass


def _note_logged_in(username: str, user_id: int) -> None:
    cb = _callback
    if cb is None:
        return
    try:
        cb.onLoggedIn(str(username), int(user_id))
    except Exception:
        pass


def _note_error(message: str) -> None:
    cb = _callback
    if cb is None:
        return
    try:
        cb.onError(str(message))
    except Exception:
        pass


# ------------------------------------------------------- ввод кода и пароля 2FA
def _ask_code(prompt: str = "") -> str:
    cb = _callback
    if cb is None:
        raise _InputCancelled("нет интерфейса для ввода кода")
    log_line("INFO", prompt.strip() or "Нужен код из Telegram")
    _status("Ожидание кода из Telegram…")
    try:
        code = str(cb.requestCode() or "").strip()
    except Exception as exc:
        raise _InputCancelled("ввод кода не удался: %s" % exc)
    if not code:
        raise _InputCancelled("код не введён")
    return code


def _ask_password(prompt: str = "") -> str:
    cb = _callback
    if cb is None:
        raise _InputCancelled("нет интерфейса для ввода пароля")
    log_line("INFO", prompt.strip() or "Нужен пароль 2FA")
    _status("Ожидание пароля 2FA…")
    try:
        password = str(cb.requestPassword() or "").strip()
    except Exception as exc:
        raise _InputCancelled("ввод пароля не удался: %s" % exc)
    if not password:
        raise _InputCancelled("пароль 2FA не введён")
    return password


def _code_provider(prompt: str = "") -> str:
    return _ask_code(prompt)


def _password_provider(prompt: str = "") -> str:
    return _ask_password(prompt)


def _install_providers() -> None:
    """Подставить хуки ввода в bot.py (в APK stdin нет)."""
    bot.CODE_PROVIDER = _code_provider
    bot.PASSWORD_PROVIDER = _password_provider


def install_callback(callback) -> bool:
    """Привязать Kotlin-колбэк до старта бота.

    Нужно для auto_api: получение ключей идёт в отдельном потоке ещё до того,
    как сервис запустил бота, а код подтверждения уже надо спрашивать у UI.
    """
    global _callback
    _callback = callback
    _install_providers()
    return True



# ------------------------------------------------------------------- хранилище
def _ensure_storage(app_dir: str) -> None:
    """Один раз инициализировать каталог приложения для bot.py."""
    global _storage_ready
    if _storage_ready:
        return
    if not app_dir:
        raise RuntimeError("не передан каталог приложения")
    bot.init_app_storage(app_dir)
    try:
        bot.CONFIG = bot.load_config()
    except Exception:
        pass
    _storage_ready = True


def _config() -> Dict[str, Any]:
    try:
        cfg = bot.load_config()
        if isinstance(cfg, dict):
            return cfg
    except Exception:
        pass
    cfg = getattr(bot, "CONFIG", None)
    return cfg if isinstance(cfg, dict) else {}


def _saved_account() -> Dict[str, str]:
    """api_id/api_hash/phone из config.txt — то, что ввёл пользователь."""
    cfg = _config()
    return {
        "api_id": str(cfg.get("api_id") or ""),
        "api_hash": str(cfg.get("api_hash") or ""),
        "phone": str(cfg.get("phone") or ""),
    }


def _config_update(updates: Dict[str, str]) -> None:
    """Аккуратно обновить key = value в первой секции config.txt.

    Комментарии и остальные секции сохраняются как есть: файл правит человек.
    """
    path = bot.CONFIG_PATH
    try:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
    except Exception:
        text = ""
    lines = text.splitlines()
    head_end = len(lines)
    for index, raw in enumerate(lines):
        if re.match(r"^\s*\[.+\]\s*$", raw):
            head_end = index
            break
    head, tail = lines[:head_end], lines[head_end:]

    applied = set()
    for index, raw in enumerate(head):
        match = re.match(r"^\s*([A-Za-z_][\w.]*)\s*=", raw)
        if not match:
            continue
        key = match.group(1).lower()
        if key in updates and key not in applied:
            head[index] = "%s = %s" % (key, updates[key])
            applied.add(key)
    for key, value in updates.items():
        if key not in applied:
            head.append("%s = %s" % (key, value))

    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(head + tail).rstrip() + "\n", encoding="utf-8")
    except Exception as exc:
        log_line("ERROR", "не удалось записать config.txt: %s" % exc)
        raise
    try:
        bot.CONFIG = bot.load_config()
    except Exception:
        pass


def _save_credentials(api_id: int, api_hash: str, phone: str) -> None:
    save = getattr(bot, "_write_credentials", None)
    if callable(save):
        save(api_id, api_hash, phone)
        try:
            bot.CONFIG = bot.load_config()
        except Exception:
            pass
        return
    _config_update({"api_id": str(api_id), "api_hash": str(api_hash), "phone": str(phone)})


# ---------------------------------------------------------------------- утилиты
def _app_version() -> str:
    return str(getattr(bot, "APP_VERSION", "0.0.0"))


async def _safe_disconnect(client) -> None:
    try:
        await client.disconnect()
    except Exception:
        pass


def _schedule_disconnect(client) -> None:
    try:
        asyncio.ensure_future(_safe_disconnect(client))
    except Exception:
        pass


async def _health_check(client) -> bool:
    try:
        await asyncio.wait_for(client(GetStateRequest()), timeout=HEALTH_CHECK_TIMEOUT)
        return True
    except asyncio.CancelledError:
        raise
    except Exception:
        return False


def _num(value) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value > 0:
        return float(value)
    return None


def _compute_next_due(broadcaster=None) -> Optional[int]:
    """Когда просыпаться для следующей рассылки/ретрая (epoch ms)."""
    getter = getattr(broadcaster, "next_due_ms", None)
    if callable(getter):
        try:
            value = _num(getter())
            if value is not None:
                return int(value)
        except Exception:
            pass

    db = getattr(bot, "db", None)
    if db is None:
        return None

    candidates: List[float] = []
    for name in ("next_due_at", "next_retry_at", "next_task_at"):
        fn = getattr(db, name, None)
        if not callable(fn):
            continue
        value = None
        for call in (lambda: fn(account_id=0), lambda: fn()):
            try:
                value = call()
                break
            except TypeError:
                continue
            except Exception:
                value = None
                break
        number = _num(value)
        if number is not None:
            candidates.append(number)

    lister = getattr(db, "get_active_interval_tasks", None)
    if callable(lister):
        try:
            for task in lister(account_id=0) or []:
                if not isinstance(task, dict):
                    continue
                for key in ("next_at", "next_run_at", "due_at"):
                    number = _num(task.get(key))
                    if number is not None:
                        candidates.append(number)
                        break
        except Exception:
            pass

    if not candidates:
        return None
    earliest = min(candidates)
    if earliest > 1e11:  # уже миллисекунды
        return int(earliest)
    return int(earliest * 1000)


def _preview(text: Any, limit: int = 90) -> str:
    raw = " ".join(str(text or "").split())
    return raw[:limit] + ("…" if len(raw) > limit else "")


# ------------------------------------------------------------------ управление
def is_running() -> bool:
    return bool(_is_running)


def kick() -> bool:
    """Попросить супервизор немедленно проверить связь.

    Вызывается из Kotlin при смене сети, из будильника и из UI, чтобы мёртвый
    после Doze сокет заменялся сразу, а не на следующем тике.
    """
    with _bridge_lock:
        loop = _loop
        event = _kick_event
    if loop is None or event is None or not _is_running:
        return False
    try:
        loop.call_soon_threadsafe(event.set)
        return True
    except Exception:
        return False


def stop_bot(wait_seconds: float = 0.0) -> None:
    """Остановить бота. Идемпотентно, можно звать с любого потока."""
    global _client, _broadcaster, _is_running
    with _bridge_lock:
        _is_running = False
        broadcaster_to_stop = _broadcaster
        client_to_disconnect = _client
        loop_to_stop = _loop
        _broadcaster = None
        _client = None

    if loop_to_stop is None or not loop_to_stop.is_running():
        return

    def _stop_in_loop():
        if broadcaster_to_stop is not None:
            try:
                broadcaster_to_stop.stop()
            except Exception:
                pass
        event = _kick_event
        if event is not None:
            event.set()
        if client_to_disconnect is not None:
            _schedule_disconnect(client_to_disconnect)

    try:
        loop_to_stop.call_soon_threadsafe(_stop_in_loop)
    except Exception:
        pass

    # Дать прошлому loop'у закрыться, чтобы два экземпляра бота не жили
    # одновременно на одном аккаунте.
    wait = max(float(wait_seconds or 0.0), 0.0)
    if wait <= 0:
        return
    deadline = time.time() + wait
    while time.time() < deadline:
        with _bridge_lock:
            if _loop is None:
                return
        time.sleep(0.1)


# ----------------------------------------------------------------------- запуск
async def _login(client, phone: str, password_2fa: str) -> bool:
    """Вход через хуки bot.py; код и 2FA спрашиваются у UI."""
    if password_2fa:
        # Пароль сохранён пользователем в настройках — спрашивать не нужно.
        bot.PASSWORD_PROVIDER = lambda prompt="": password_2fa

    authenticate = getattr(bot, "authenticate_client", None)
    if callable(authenticate):
        await authenticate(client, phone, "android")
        return True

    # Запасной путь, если bot.py старее хуков ввода.
    await client.connect()
    if await client.is_user_authorized():
        return True
    await client.send_code_request(phone)
    code = _ask_code("Код из Telegram")
    try:
        await client.sign_in(phone=phone, code=code)
    except SessionPasswordNeededError:
        await client.sign_in(password=_ask_password("Пароль 2FA"))
    return True


def _account_cfg(username: str) -> Dict[str, Any]:
    cfg = _config()
    return {
        "name": "android",
        "auto_sub_folder": cfg.get("auto_sub_folder", "автосабнутое"),
        "auto_read_spam_pings": bool(cfg.get("auto_read_spam_pings", True)),
        "auto_sub_enabled": bool(cfg.get("auto_sub_enabled", True)),
        "log_errors_only": bool(cfg.get("log_errors_only", True)),
        "username": username,
    }


async def _supervise(client, broadcaster, kick_event: asyncio.Event, username: str) -> None:
    """Держать сессию живой, отдавать статус и точное время следующей задачи."""
    global _next_due_ms, _started_at
    last_health = time.monotonic()
    healthy = True
    last_due_sent: Optional[int] = None

    while _is_running:
        kick_wait = asyncio.ensure_future(kick_event.wait())
        try:
            await asyncio.wait(
                {client.disconnected, kick_wait},
                timeout=SUPERVISOR_POLL_SECONDS,
                return_when=asyncio.FIRST_COMPLETED,
            )
        finally:
            if not kick_wait.done():
                kick_wait.cancel()

        kicked = kick_event.is_set()
        kick_event.clear()
        if not _is_running:
            break

        # Telethon пересоздаёт future при reconnect; если он уже завершён,
        # ждать нечего — иначе получится холостой цикл.
        if client.disconnected.done() and client.is_connected():
            await asyncio.sleep(0.5)
            continue

        due = _compute_next_due(broadcaster)
        _next_due_ms = due
        if due is not None and due != last_due_sent:
            last_due_sent = due
            _note_next_due(due)

        now = time.monotonic()
        dead = not client.is_connected()
        if not dead and (kicked or now - last_health >= IDLE_HEALTH_SECONDS):
            last_health = now
            dead = not await _health_check(client)

        if dead:
            if healthy:
                log_line("WARN", "Связь с Telegram потеряна, переподключаюсь")
                _status("Нет связи, переподключаюсь…", True)
            healthy = False
            await _safe_disconnect(client)
            delay = 5.0 + random.uniform(0.0, 2.0)
            while _is_running:
                try:
                    await client.connect()
                    if await _health_check(client):
                        healthy = True
                        last_health = time.monotonic()
                        log_line("OK", "Соединение восстановлено")
                        _status("Работает (%s)" % username, True)
                        try:
                            broadcaster.request_folder_sync()
                        except Exception:
                            pass
                        break
                except (ConnectionError, OSError, asyncio.TimeoutError) as exc:
                    log_line("WARN", "Переподключение не удалось: %s" % exc)
                await asyncio.sleep(delay)
                delay = min(delay * 2, RECONNECT_MAX_DELAY)
                if delay >= 60:
                    _status("Нет связи с Telegram, ждём сеть…", True)
        elif not healthy:
            healthy = True
            _status("Работает (%s)" % username, True)


async def _run(client, phone: str, password_2fa: str) -> None:
    global _broadcaster, _kick_event, _user_name, _started_at
    broadcaster = None
    lock_key = None
    kick_event = asyncio.Event()
    with _bridge_lock:
        _kick_event = kick_event

    try:
        log_line("INFO", "Подключение к Telegram…")
        _status("Подключение к Telegram…", True)

        delay = 3.0
        while _is_running:
            try:
                await _login(client, phone, password_2fa)
                break
            except _InputCancelled:
                raise
            except _FATAL_AUTH_ERRORS:
                raise
            except (ConnectionError, OSError, asyncio.TimeoutError) as exc:
                log_line("WARN", "Нет сети: %s. Повтор через %d с" % (exc, delay))
                _status("Ожидание сети / VPN…", True)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 60.0)
        if not _is_running:
            return

        me = await client.get_me()
        if me is None:
            raise RuntimeError("Telegram не вернул аккаунт после входа")

        lock_key = "acct_%s" % me.id
        waited = 0
        while not bot.acquire_instance_lock(lock_key):
            if not _is_running:
                lock_key = None
                return
            if waited == 0:
                _status("Ждём остановки предыдущего запуска…", True)
                log_line("WARN", "Аккаунт уже запущен в другом процессе, ждём")
            if waited >= 90:
                lock_key = None
                raise RuntimeError("этот аккаунт уже запущен в другом процессе")
            await asyncio.sleep(2)
            waited += 2

        username = "@%s" % me.username if me.username else (me.first_name or "Пользователь")
        _user_name = username
        try:
            client._self_user = me
        except Exception:
            pass

        broadcaster = bot.BroadcasterService(client, account_id=me.id)
        with _bridge_lock:
            _broadcaster = broadcaster
        broadcaster.start()
        bot.register_events(client, broadcaster, me.id, acc_cfg=_account_cfg(username))

        # Сказать Telegram, что мы хотим апдейты, и только потом говорить UI,
        # что всё работает.
        await _health_check(client)
        _started_at = time.time()
        _note_logged_in(username, int(me.id))
        _status("Работает (%s)" % username, True)
        log_line("OK", "Вход выполнен: %s" % username)

        await _supervise(client, broadcaster, kick_event, username)
    finally:
        if broadcaster is not None:
            try:
                broadcaster.stop()
            except Exception:
                pass
        with _bridge_lock:
            if _broadcaster is broadcaster:
                _broadcaster = None
            if _kick_event is kick_event:
                _kick_event = None
        await _safe_disconnect(client)
        if lock_key:
            try:
                bot.release_instance_lock(lock_key)
            except Exception:
                pass


def start_bot(api_id_val, api_hash_val, phone_val, password_2fa_val, files_dir_val, callback):
    """Заблокировать вызвавший поток на всё время работы бота."""
    global _client, _loop, _is_running, _callback, _started_at, _user_name, _next_due_ms

    _callback = callback
    _install_providers()
    stop_bot(wait_seconds=10.0)

    _started_at = 0.0
    _user_name = ""
    _next_due_ms = None

    try:
        api_id = int(str(api_id_val).strip())
        api_hash = str(api_hash_val).strip()
        phone = str(phone_val).strip().replace(" ", "")
        password_2fa = str(password_2fa_val).strip() if password_2fa_val else ""
        app_dir = str(files_dir_val).strip()
        if not api_id or not api_hash:
            raise ValueError("api_id и api_hash не заполнены")
        _ensure_storage(app_dir)
    except Exception as exc:
        error = "%s: %s" % (type(exc).__name__, exc)
        log_line("ERROR", "Запуск невозможен: %s" % error)
        _status("Ошибка: %s" % error, False)
        _note_error(error)
        return

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    client = TelegramClient(
        os.path.join(app_dir, SESSION_NAME),
        api_id,
        api_hash,
        catch_up=False,
        connection_retries=None,  # переподключаться бесконечно, сквозь VPN и смену сети
        retry_delay=3,
        auto_reconnect=True,
        timeout=20,
        request_retries=3,
        flood_sleep_threshold=60,
        device_model="Android",
        system_version="Colemailer",
        app_version=_app_version(),
    )

    with _bridge_lock:
        _loop = loop
        _client = client
        _is_running = True

    try:
        loop.run_until_complete(_run(client, phone, password_2fa))
    except _InputCancelled as exc:
        log_line("WARN", "Вход отменён: %s" % exc)
        _status("Вход отменён: %s" % exc, False)
        _note_error(str(exc))
    except _FATAL_AUTH_ERRORS as exc:
        error = "%s: %s" % (type(exc).__name__, exc)
        log_line("ERROR", "Ошибка входа: %s" % error)
        _status("Ошибка входа: %s" % error, False)
        _note_error(error)
    except Exception as exc:
        error = "%s: %s" % (type(exc).__name__, exc)
        traceback.print_exc()
        log_line("ERROR", "Бот остановлен: %s" % error)
        _status("Ошибка: %s" % error, False)
        _note_error(error)
    finally:
        with _bridge_lock:
            _is_running = False
            if _client is client:
                _client = None
            if _loop is loop:
                _loop = None
        _status("Остановлен", False)
        try:
            pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:
            pass
        try:
            loop.close()
        except Exception:
            pass


# ---------------------------------------------------------------- данные для UI
def get_state_json() -> str:
    now = time.time()
    running = bool(_is_running)
    payload = {
        "running": running,
        "status": _last_status,
        "user": _user_name,
        "uptime_ms": int((now - _started_at) * 1000) if running and _started_at else 0,
        "next_due_ms": _next_due_ms,
        "version": _app_version(),
    }
    return json.dumps(payload, ensure_ascii=False)


def next_due_ms() -> Optional[int]:
    return _next_due_ms


def get_tasks_json() -> str:
    """Шаблоны и активные задачи рассылок (только чтение)."""
    templates: List[Dict[str, Any]] = []
    tasks: List[Dict[str, Any]] = []
    db = getattr(bot, "db", None)
    if db is None:
        return json.dumps({"templates": [], "tasks": [], "ready": False}, ensure_ascii=False)

    lister = getattr(db, "list_templates", None)
    if callable(lister):
        try:
            for item in lister() or []:
                if not isinstance(item, dict):
                    continue
                templates.append({
                    "name": str(item.get("name", "")),
                    "preview": _preview(item.get("text", "")),
                    "media": len(item.get("media_files") or []),
                    "buttons": len(item.get("buttons") or []),
                })
        except Exception as exc:
            log_line("WARN", "Шаблоны не прочитались: %s" % exc)

    task_lister = getattr(db, "get_active_interval_tasks", None)
    if callable(task_lister):
        try:
            for item in task_lister(account_id=0) or []:
                if not isinstance(item, dict):
                    continue
                tasks.append({
                    "id": int(item.get("id") or 0),
                    "chat_id": int(item.get("chat_id") or 0),
                    "template": str(item.get("template_name") or item.get("name") or ""),
                    "mode": str(item.get("mode") or "interval"),
                    "count": int(item.get("count") or 0),
                    "next_at": float(_num(item.get("next_at")) or 0.0),
                })
        except Exception as exc:
            log_line("WARN", "Задачи рассылок не прочитались: %s" % exc)

    return json.dumps({"templates": templates, "tasks": tasks, "ready": True}, ensure_ascii=False)


def get_settings_json() -> str:
    cfg = _config()
    saved = _saved_account()
    return json.dumps({
        "antispam": bool(cfg.get("auto_read_spam_pings", True)),
        "auto_sub": bool(cfg.get("auto_sub_enabled", True)),
        "folder": str(cfg.get("auto_sub_folder", "автосабнутое")),
        "quiet_logs": bool(cfg.get("log_errors_only", True)),
        "api_id": saved["api_id"],
        "phone": saved["phone"],
        "version": _app_version(),
    }, ensure_ascii=False)


def save_settings_json(payload: str) -> str:
    """Сохранить настройки в config.txt (те же ключи читает bot.py)."""
    try:
        data = json.loads(payload or "{}")
    except Exception as exc:
        return json.dumps({"ok": False, "error": "кривой запрос: %s" % exc}, ensure_ascii=False)
    if not isinstance(data, dict):
        return json.dumps({"ok": False, "error": "кривой запрос"}, ensure_ascii=False)

    mapping = {
        "antispam": "auto_read_spam_pings",
        "auto_sub": "auto_sub_enabled",
        "folder": "auto_sub_folder",
        "quiet_logs": "log_errors_only",
    }
    updates: Dict[str, str] = {}
    for ui_key, cfg_key in mapping.items():
        if ui_key not in data:
            continue
        value = data[ui_key]
        if isinstance(value, bool):
            updates[cfg_key] = "true" if value else "false"
        else:
            updates[cfg_key] = str(value).strip()

    try:
        _config_update(updates)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    log_line("INFO", "Настройки сохранены в config.txt")
    return json.dumps({"ok": True, "settings": json.loads(get_settings_json())}, ensure_ascii=False)


def save_account_json(api_id, api_hash, phone, password_2fa="") -> str:
    """Записать введённые вручную ключи в config.txt."""
    try:
        api_id_int = int(str(api_id).strip())
        api_hash_str = str(api_hash).strip()
        phone_str = str(phone).strip()
        if not api_id_int or len(api_hash_str) < 16:
            raise ValueError("api_id — число, api_hash — 32 символа")
        _save_credentials(api_id_int, api_hash_str, phone_str)
    except Exception as exc:
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    if password_2fa:
        # Пароль 2FA в config.txt не пишем: он живёт в SecretStore на устройстве.
        log_line("INFO", "Пароль 2FA сохранён на устройстве")
    log_line("OK", "Ключи сохранены в config.txt")
    return json.dumps({"ok": True, "api_id": api_id_int, "phone": phone_str}, ensure_ascii=False)


def auto_api(phone_val: str, files_dir_val: str) -> str:
    """Получить api_id/api_hash через my.telegram.org.

    Блокирующая: Kotlin зовёт её в отдельном потоке. Код подтверждения
    запрашивается у UI через тот же CODE_PROVIDER.
    """
    phone = str(phone_val or "").strip().replace(" ", "").replace("-", "")
    if not phone:
        return json.dumps({"ok": False, "error": "номер не указан"}, ensure_ascii=False)
    try:
        _ensure_storage(str(files_dir_val).strip())
    except Exception as exc:
        return json.dumps({"ok": False, "error": "каталог приложения: %s" % exc}, ensure_ascii=False)

    try:
        from cole.api_autoreg import MyTelegramAuth
    except Exception as exc:
        log_line("ERROR", "Модуль авто-получения недоступен: %s" % exc)
        return json.dumps(
            {"ok": False, "error": "модуль авто-получения недоступен: %s" % exc},
            ensure_ascii=False,
        )

    auth = None
    try:
        _status("Проверяю my.telegram.org…", False)
        # Old cookies have no account identity; never reuse them for another number.
        phone_key = hashlib.sha256(phone.encode("utf-8")).hexdigest()
        cookie_path = os.path.join(str(files_dir_val).strip(), f"tg_api_cookies_{phone_key}.txt")
        auth = MyTelegramAuth(cookie_path=cookie_path)
        # Сначала пробуем сохранённую cookie: если приложение уже создано,
        # код из Telegram вообще не нужен.
        has_session = auth.has_session()
        app = auth.fetch_app() if has_session else None
        source = "cookie"
        if not app and has_session:
            app = auth.create_app(title="Colemailer", shortname="colemailer")
            source = "cookie"
        if not app:
            log_line("INFO", "Запрос кода на my.telegram.org для %s" % phone)
            _status("Запрос кода на my.telegram.org…", False)
            auth.send_code(phone)
            log_line("INFO", "Код отправлен в Telegram от сервиса")
            code = _ask_code("Код из Telegram (my.telegram.org)")
            auth.sign_in(code)
            app = auth.fetch_app()
            source = "existing"
            if not app:
                app = auth.create_app(title="Colemailer", shortname="colemailer")
                source = "created"
        api_id = int(app["api_id"])
        api_hash = str(app["api_hash"])
        auth.save_cookies()
        _save_credentials(api_id, api_hash, phone)
        log_line("OK", "api_id получен (%s): %s" % (source, api_id))
        _status("Ключи получены", False)
        return json.dumps({
            "ok": True,
            "api_id": api_id,
            "api_hash": api_hash,
            "phone": phone,
            "source": source,
        }, ensure_ascii=False)
    except _InputCancelled as exc:
        log_line("WARN", "Авто-получение отменено: %s" % exc)
        return json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False)
    except Exception as exc:
        error = str(exc) or type(exc).__name__
        log_line("ERROR", "Авто-получение не удалось: %s" % error)
        return json.dumps({"ok": False, "error": error}, ensure_ascii=False)
    finally:
        if auth is not None:
            try:
                auth.close()
            except Exception:
                pass


def version() -> str:
    return _app_version()
