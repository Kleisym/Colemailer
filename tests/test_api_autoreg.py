# -*- coding: utf-8 -*-
"""cole.api_autoreg: получение api_id/api_hash через my.telegram.org.

Сеть здесь не нужна: проверяются разбор реальной страницы `/apps`, вход по
коду (сервер отвечает литералом `true`, а не JSON-объектом) и запись ключей в
`config.txt` так, чтобы не затереть чужие секции и аккаунты.
"""
import http.server
import threading
import urllib.parse

import pytest

import bot
from cole import api_autoreg
from cole.api_autoreg import (
    ApiAuthError,
    MyTelegramAuth,
    NotAuthorized,
    obtain_credentials,
    parse_apps_page,
)

APPS_PAGE = """<!DOCTYPE html>
<html>
<head><title>Telegram Messenger</title></head>
<body>
  <div class="page_section">
    <h4>App configuration</h4>
    <div class="panel">
      <p>App api_id: <strong>1234567</strong></p>
      <p>App api_hash: <strong>0123456789abcdef0123456789abcdef</strong></p>
      <p>App title: Colemailer</p>
      <p>Short name: colemailer</p>
    </div>
  </div>
</body>
</html>
"""

CREATE_FORM_PAGE = """<!DOCTYPE html>
<html><body>
  <div id="app_edit">
    <h4>Create new application</h4>
    <form method="post" action="/apps">
      <input type="hidden" name="hash" value="a1b2c3d4e5f6a7b8c9d0"/>
      <input type="text" name="app_title" value=""/>
      <input type="text" name="app_shortname" value=""/>
      <input type="text" name="app_url" value=""/>
      <input type="text" name="app_platform" value="other"/>
      <textarea name="app_desc"></textarea>
      <button type="submit">Create application</button>
    </form>
  </div>
</body></html>
"""

APPS_PAGE_UPPERCASE_HASH = """<div class="panel">
  <p>api_hash: <code>ABCDEF0123456789ABCDEF0123456789</code></p>
  <p>api_id: <span>7654321</span></p>
</div>"""


# --------------------------------------------------------------------------- #
# parse_apps_page
# --------------------------------------------------------------------------- #
def test_parse_apps_page_reads_real_markup():
    parsed = parse_apps_page(APPS_PAGE)
    assert parsed == {"api_id": 1234567, "api_hash": "0123456789abcdef0123456789abcdef"}


def test_parse_apps_page_normalises_uppercase_hash():
    parsed = parse_apps_page(APPS_PAGE_UPPERCASE_HASH)
    assert parsed["api_id"] == 7654321
    assert parsed["api_hash"] == "abcdef0123456789abcdef0123456789"


def test_parse_apps_page_reads_input_values():
    """Реальная страница может держать значения в value=, а не в тексте."""
    page = """
    <html><body>
      <label for="app_id">App api_id:</label>
      <div><span><input id="app_id" value="1234567" readonly></span></div>
      <label for="app_hash">App api_hash:</label>
      <div><span><input value="0123456789abcdef0123456789abcdef" name="app_hash" readonly></span></div>
    </body></html>
    """
    assert parse_apps_page(page) == {
        "api_id": 1234567,
        "api_hash": "0123456789abcdef0123456789abcdef",
    }


def test_parse_apps_page_reads_label_and_strong():
    page = """
    <label for="app_id">App api_id:</label>
    <div class="input-group"><span class="form-control"><strong>1234567</strong></span></div>
    <label for="app_hash">App api_hash:</label>
    <div class="input-group"><span class="form-control">0123456789abcdef0123456789abcdef</span></div>
    """
    assert parse_apps_page(page) == {
        "api_id": 1234567,
        "api_hash": "0123456789abcdef0123456789abcdef",
    }


def test_parse_apps_page_normalises_spaces_in_hash():
    page = """
    <label for="app_id">App api_id:</label><div><strong>1234567</strong></div>
    <label for="app_hash">App api_hash:</label>
    <div><span>0123 4567 89ab cdef 0123 4567 89ab cdef</span></div>
    """
    assert parse_apps_page(page) == {
        "api_id": 1234567,
        "api_hash": "0123456789abcdef0123456789abcdef",
    }


def test_parse_apps_page_reads_camel_case_json():
    page = '{"apiId": 1234567, "apiHash": "0123456789abcdef0123456789abcdef"}'
    assert parse_apps_page(page) == {
        "api_id": 1234567,
        "api_hash": "0123456789abcdef0123456789abcdef",
    }


def test_parse_apps_page_does_not_steal_api_id_from_hash():
    page = """
    <label for="app_id">App api_id:</label><div><span></span></div>
    <label for="app_hash">App api_hash:</label>
    <div><span>12345678901234567890123456789012</span></div>
    """
    assert parse_apps_page(page) is None


def test_create_app_uses_the_create_form_hash_not_a_delete_form():
    page = """
    <form method="post" action="/apps/delete">
      <input type="hidden" name="hash" value="DELETE_TOKEN">
      <input type="text" name="app_id" value="1">
    </form>
    <form method="post" action="/apps">
      <input type="hidden" name="hash" value="CREATE_TOKEN">
      <input type="text" name="app_title" value="">
      <input type="text" name="app_shortname" value="">
      <textarea name="app_description"></textarea>
    </form>
    """
    opener = FakeOpener(
        get_pages={"/apps": page},
        post_pages={"/apps": APPS_PAGE},
    )
    auth = make_auth(opener)
    auth.create_app(title="Colemailer", shortname="colemailer")

    body = [c for c in opener.calls if c[0] == "POST"][0][2]
    assert b"hash=CREATE_TOKEN" in body
    assert b"DELETE_TOKEN" not in body
    assert b"app_description=" in body


def test_fetch_app_follows_the_active_app_link():
    list_page = """
    <h4>App configuration</h4>
    <a href="/apps?app_id=1234567">Active App · created 22 Dec 2024</a>
    """
    opener = FakeOpener(
        get_pages={
            "/apps": list_page,
            "/apps?app_id=1234567": APPS_PAGE,
        }
    )
    auth = make_auth(opener)

    found = auth.fetch_app()

    assert found == {"api_id": 1234567, "api_hash": "0123456789abcdef0123456789abcdef"}
    assert any("app_id=1234567" in call[1] for call in opener.calls)


def test_fetch_app_submits_the_app_selection_form():
    list_page = """
    <form method="post" action="/apps">
      <input type="hidden" name="hash" value="SELECT_TOKEN">
      <input type="hidden" name="app_id" value="1234567">
      <button>Open</button>
    </form>
    """
    opener = FakeOpener(
        get_pages={"/apps": list_page},
        post_pages={"/apps": APPS_PAGE},
    )
    auth = make_auth(opener)

    found = auth.fetch_app()

    assert found == {"api_id": 1234567, "api_hash": "0123456789abcdef0123456789abcdef"}
    post = [c for c in opener.calls if c[0] == "POST"][0]
    assert b"app_id=1234567" in post[2]


def test_parse_apps_page_returns_none_when_the_app_is_not_created_yet():
    assert parse_apps_page(CREATE_FORM_PAGE) is None


def test_parse_apps_page_returns_none_for_an_empty_page():
    assert parse_apps_page("") is None


def test_parse_apps_page_ignores_an_id_without_a_hash():
    assert parse_apps_page("<p>App api_id: <b>1234567</b></p>") is None


# --------------------------------------------------------------------------- #
# транспорт: фейковый opener
# --------------------------------------------------------------------------- #
class _Headers:
    def get_content_charset(self):
        return "utf-8"


class _Response:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")
        self.headers = _Headers()

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeOpener:
    """Отвечает по паре (метод, путь), как настоящий opener urllib."""

    def __init__(self, get_pages=None, post_pages=None):
        self.get_pages = dict(get_pages or {})
        self.post_pages = dict(post_pages or {})
        self.calls = []

    def open(self, request, **kwargs):
        url = getattr(request, "full_url", str(request))
        path = url.split("my.telegram.org")[-1] or "/"
        data = getattr(request, "data", None)
        self.calls.append(("POST" if data is not None else "GET", path, data))
        table = self.post_pages if data is not None else self.get_pages
        if path not in table:
            raise AssertionError(f"неожиданный запрос {request.full_url}")
        return _Response(table[path])


def make_auth(opener):
    auth = MyTelegramAuth(opener=opener)
    auth._ssl = None
    return auth


class StrictOpener:
    """Как настоящий OpenerDirector: open() принимает только timeout.

    Именно на этом падало авто-получение в APK: context — аргумент
    urlopen(), а не opener.open(). Тест не даёт вернуть эту ошибку.
    """

    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def open(self, request, timeout=None):
        self.calls.append(request.full_url)
        return _Response(self.payload)


def test_transport_never_passes_context_to_the_opener():
    opener = StrictOpener('{"random_hash": "abc123"}')
    auth = MyTelegramAuth(opener=opener)
    auth.send_code("+79991234567")
    assert auth.random_hash == "abc123"
    assert opener.calls == ["https://my.telegram.org/auth/send_password"]


class _LocalMyTelegram(http.server.BaseHTTPRequestHandler):
    """Мини-копия my.telegram.org на localhost: реальный urllib и cookie-jar."""

    def log_message(self, *args):
        return

    def _send(self, body: str, content_type: str = "text/html; charset=utf-8", cookie: str = ""):
        raw = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        if self.path.startswith("/apps"):
            if "session=ok" not in (self.headers.get("Cookie") or ""):
                self._send('<form action="/auth/send_password"></form>')
            else:
                self._send(APPS_PAGE)
        else:
            self._send("not found")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        data = urllib.parse.parse_qs(self.rfile.read(length).decode("utf-8"))
        if self.path.startswith("/auth/send_password"):
            assert data.get("phone") == ["+79991234567"]
            self._send('{"random_hash": "rh1"}', "application/json")
        elif self.path.startswith("/auth/login"):
            assert data.get("password") == ["12345"]
            self._send("true", "application/json", cookie="session=ok; Path=/")
        else:
            self._send("not found")


def test_full_flow_over_real_http_with_cookies(monkeypatch):
    """Интеграционный прогон send_code -> sign_in -> fetch_app без фейкового opener."""
    server = http.server.HTTPServer(("127.0.0.1", 0), _LocalMyTelegram)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        monkeypatch.setattr(api_autoreg, "SITE", base)
        # Cookie выставляем вручную после login: сервер выше отвечает `true`,
        # а fetch_app должен увидеть авторизованную страницу.
        auth = MyTelegramAuth()
        auth.send_code("+79991234567")
        assert auth.random_hash == "rh1"
        auth.sign_in("12345")
        app = auth.fetch_app()
        assert app == {"api_id": 1234567, "api_hash": "0123456789abcdef0123456789abcdef"}
        auth.close()
    finally:
        server.shutdown()
        server.server_close()


# --------------------------------------------------------------------------- #
# вход по коду
# --------------------------------------------------------------------------- #
def test_sign_in_accepts_a_literal_true_response():
    """`/auth/login` отвечает `true`, а не JSON-объектом — это не ошибка."""
    opener = FakeOpener(
        get_pages={"/apps": APPS_PAGE},
        post_pages={"/auth/login": "true"},
    )
    auth = make_auth(opener)
    auth.phone = "+79991234567"
    auth.random_hash = "deadbeef"

    auth.sign_in("12345")

    assert auth.authorized is True
    assert [c[0] for c in opener.calls] == ["POST", "GET"]


def test_sign_in_rejects_literal_false_before_verifying_session():
    opener = FakeOpener(get_pages={"/apps": APPS_PAGE}, post_pages={"/auth/login": "false"})
    auth = make_auth(opener)
    auth.phone = "+79991234567"
    auth.random_hash = "deadbeef"
    with pytest.raises(ApiAuthError):
        auth.sign_in("12345")
    assert auth.authorized is False
    assert [call[0] for call in opener.calls] == ["POST"]


def test_sign_in_does_not_mark_failed_verification_authorized():
    opener = FakeOpener(
        get_pages={"/apps": '<form action="/auth/send_password"></form>'},
        post_pages={"/auth/login": "true"},
    )
    auth = make_auth(opener)
    auth.phone = "+79991234567"
    auth.random_hash = "deadbeef"
    with pytest.raises(ApiAuthError):
        auth.sign_in("12345")
    assert auth.authorized is False


def test_create_app_sends_description_under_alternate_field_name():
    page = CREATE_FORM_PAGE.replace("app_desc", "app_description")
    opener = FakeOpener(get_pages={"/apps": page}, post_pages={"/apps": APPS_PAGE})
    make_auth(opener).create_app(description="Example description")
    body = next(call[2] for call in opener.calls if call[0] == "POST")
    assert urllib.parse.parse_qs(body.decode())["app_description"] == ["Example description"]


def test_send_code_stores_the_random_hash():
    opener = FakeOpener(post_pages={"/auth/send_password": '{"random_hash": "abc123"}'})
    auth = make_auth(opener)

    auth.send_code("+7 999 123-45-67")

    assert auth.phone == "+79991234567"
    assert auth.random_hash == "abc123"
    assert auth.authorized is False


def test_send_code_rejects_a_malformed_phone():
    auth = make_auth(FakeOpener())
    with pytest.raises(ApiAuthError):
        auth.send_code("89991234567")


def test_send_code_without_a_hash_is_an_error():
    opener = FakeOpener(post_pages={"/auth/send_password": "{}"})
    auth = make_auth(opener)
    with pytest.raises(ApiAuthError):
        auth.send_code("+79991234567")


def test_sign_in_requires_a_requested_code_first():
    auth = make_auth(FakeOpener())
    with pytest.raises(ApiAuthError):
        auth.sign_in("12345")


def test_sign_in_reports_the_server_error_in_human_form():
    opener = FakeOpener(
        get_pages={"/apps": APPS_PAGE},
        post_pages={"/auth/login": '{"error": "PHONE_CODE_INVALID"}'},
    )
    auth = make_auth(opener)
    auth.phone = "+79991234567"
    auth.random_hash = "deadbeef"

    with pytest.raises(ApiAuthError) as exc:
        auth.sign_in("00000")

    assert "неверный код" in str(exc.value)
    assert auth.authorized is False


def test_sign_in_fails_when_the_session_did_not_stick():
    """Страница снова просит код — значит вход не подтвердился."""
    opener = FakeOpener(
        get_pages={"/apps": '<form action="/auth/send_password"></form>'},
        post_pages={"/auth/login": "true"},
    )
    auth = make_auth(opener)
    auth.phone = "+79991234567"
    auth.random_hash = "deadbeef"

    with pytest.raises(ApiAuthError):
        auth.sign_in("12345")


def test_fetch_app_returns_existing_credentials():
    auth = make_auth(FakeOpener(get_pages={"/apps": APPS_PAGE}))
    assert auth.fetch_app()["api_id"] == 1234567


def test_create_app_reads_the_form_hash_and_returns_the_new_keys():
    opener = FakeOpener(
        get_pages={"/apps": CREATE_FORM_PAGE},
        post_pages={"/apps": APPS_PAGE},
    )
    auth = make_auth(opener)

    created = auth.create_app(title="Colemailer", shortname="colemailer")

    assert created["api_id"] == 1234567
    post = [c for c in opener.calls if c[0] == "POST"][0]
    assert b"hash=a1b2c3d4e5f6a7b8c9d0" in post[2]


def test_create_app_fails_clearly_without_a_form():
    auth = make_auth(FakeOpener(get_pages={"/apps": "<p>нет формы</p>"}))
    with pytest.raises(ApiAuthError):
        auth.create_app()


# --------------------------------------------------------------------------- #
# полный сценарий с мок-клиентом
# --------------------------------------------------------------------------- #
class FakeAuth:
    def __init__(self, app=None, created=None):
        self.app = app
        self.created = created
        self.calls = []
        self.closed = False

    def send_code(self, phone):
        self.calls.append(("send_code", phone))

    def sign_in(self, code):
        self.calls.append(("sign_in", code))

    def fetch_app(self):
        self.calls.append(("fetch_app", None))
        return self.app

    def create_app(self, title="Colemailer", shortname="colemailer"):
        self.calls.append(("create_app", title))
        return self.created

    def close(self):
        self.closed = True


def test_obtain_credentials_prefers_the_existing_app():
    client = FakeAuth(app={"api_id": 11, "api_hash": "aa"})

    result = obtain_credentials("+79991234567", lambda: "12345", client=client)

    assert result["source"] == "existing"
    assert result["api_id"] == 11
    assert [c[0] for c in client.calls] == ["send_code", "sign_in", "fetch_app"]
    assert client.closed is True


def test_obtain_credentials_creates_an_app_when_missing():
    client = FakeAuth(app=None, created={"api_id": 22, "api_hash": "bb"})

    result = obtain_credentials("+79991234567", lambda: "12345", client=client)

    assert result["source"] == "created"
    assert result["api_id"] == 22
    assert [c[0] for c in client.calls] == ["send_code", "sign_in", "fetch_app", "create_app"]
    assert client.closed is True


def test_obtain_credentials_closes_the_session_on_failure():
    client = FakeAuth(app={"api_id": 1, "api_hash": "a"})

    def broken_code():
        raise RuntimeError("пользователь закрыл диалог")

    with pytest.raises(RuntimeError):
        obtain_credentials("+79991234567", broken_code, client=client)

    assert client.closed is True


def test_not_authorized_is_an_api_auth_error():
    assert issubclass(NotAuthorized, ApiAuthError)


# --------------------------------------------------------------------------- #
# запись ключей в config.txt
# --------------------------------------------------------------------------- #
CONFIG_WITH_ACCOUNTS = """# основные настройки
log_errors_only = true
api_id = 111
api_hash = oldhash
poll_interval = 5

[account1]
api_id = 999
api_hash = acc1hash
phone = +70000000001

[account2]
api_id = 888
api_hash = acc2hash
phone = +70000000002
"""


def _split_sections(text):
    global_part, sections, current = [], {}, None
    for line in text.splitlines():
        if line.strip().startswith("[") and line.strip().endswith("]"):
            current = line.strip().strip("[]")
            sections[current] = []
            continue
        (sections[current] if current else global_part).append(line)
    return global_part, sections


def _key_value(lines):
    result = {}
    for line in lines:
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            result[key.strip()] = value.strip()
    return result


def test_write_credentials_puts_the_keys_into_the_first_account_section(tmp_path, monkeypatch):
    """В конфиге с секциями ключи живут в [account1], а не в глобальной шапке.

    Именно оттуда их читает `load_config` для запуска аккаунта, поэтому
    глобальные значения в таком файле ничего не решают.
    """
    config = tmp_path / "config.txt"
    config.write_text(CONFIG_WITH_ACCOUNTS, encoding="utf-8")
    monkeypatch.setattr(bot, "CONFIG_PATH", config)

    bot._write_credentials(123456, "deadbeefdeadbeefdeadbeefdeadbeef")

    global_part, sections = _split_sections(config.read_text(encoding="utf-8"))
    acc1 = _key_value(sections["account1"])
    assert acc1["api_id"] == "123456"
    assert acc1["api_hash"] == "deadbeefdeadbeefdeadbeefdeadbeef"
    assert acc1["phone"] == "+70000000001", "существующий телефон сохраняется"
    glob = _key_value(global_part)
    assert glob["log_errors_only"] == "true", "глобальные настройки не тронуты"
    assert glob["poll_interval"] == "5"


def test_write_credentials_does_not_touch_the_next_account(tmp_path, monkeypatch):
    config = tmp_path / "config.txt"
    config.write_text(CONFIG_WITH_ACCOUNTS, encoding="utf-8")
    monkeypatch.setattr(bot, "CONFIG_PATH", config)

    bot._write_credentials(123456, "deadbeefdeadbeefdeadbeefdeadbeef", phone="+79990001122")

    _global, sections = _split_sections(config.read_text(encoding="utf-8"))
    assert _key_value(sections["account2"]) == {
        "api_id": "888", "api_hash": "acc2hash", "phone": "+70000000002",
    }
    # Телефон первого аккаунта заменяется новым, комментарии и шапка целы.
    assert _key_value(sections["account1"])["phone"] == "+79990001122"
    assert "# основные настройки" in config.read_text(encoding="utf-8")


def test_write_credentials_adds_missing_keys_to_the_first_section(tmp_path, monkeypatch):
    config = tmp_path / "config.txt"
    config.write_text("[account1]\nphone = +70000000001\n\n[account2]\nphone = +70000000002\n",
                      encoding="utf-8")
    monkeypatch.setattr(bot, "CONFIG_PATH", config)

    bot._write_credentials(123456, "h" * 32, phone="+79990001122")

    _global, sections = _split_sections(config.read_text(encoding="utf-8"))
    acc1 = _key_value(sections["account1"])
    assert acc1["api_id"] == "123456"
    assert acc1["api_hash"] == "h" * 32
    assert acc1["phone"] == "+79990001122"
    assert _key_value(sections["account2"]) == {"phone": "+70000000002"}


def test_write_credentials_replaces_global_keys_in_a_flat_config(tmp_path, monkeypatch):
    """Без секций (одноаккаунтный конфиг) ключи лежат в шапке файла."""
    config = tmp_path / "config.txt"
    config.write_text("log_errors_only = false\napi_id = 111\napi_hash = old\n",
                      encoding="utf-8")
    monkeypatch.setattr(bot, "CONFIG_PATH", config)

    bot._write_credentials(123456, "deadbeefdeadbeefdeadbeefdeadbeef", phone="+79990001122")

    glob = _key_value(config.read_text(encoding="utf-8").splitlines())
    assert glob["api_id"] == "123456"
    assert glob["api_hash"] == "deadbeefdeadbeefdeadbeefdeadbeef"
    assert glob["phone"] == "+79990001122"
    assert glob["log_errors_only"] == "false"


def test_write_credentials_creates_the_file_from_the_default(tmp_path, monkeypatch):
    config = tmp_path / "config.txt"
    monkeypatch.setattr(bot, "CONFIG_PATH", config)

    bot._write_credentials(777, "f" * 32)

    assert config.exists()
    global_part, _sections = _split_sections(config.read_text(encoding="utf-8"))
    glob = _key_value(global_part)
    assert glob["api_id"] == "777"
    assert glob["api_hash"] == "f" * 32
