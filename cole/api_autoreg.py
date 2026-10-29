"""Автоматическое получение api_id и api_hash через my.telegram.org.

Зачем: обычному пользователю лень идти на сайт, вводить номер, ловить код,
заполнять форму приложения. Здесь тот же официальный сценарий выполняется
кодом: запрос кода, вход по коду из Telegram, чтение уже созданного приложения
или создание нового.

Сценарий полностью серверный, никаких своих серверов и посредников:
    1. POST /auth/send_password   -> Telegram присылает код в приложение
    2. POST /auth/login           -> вход по этому коду (cookie сессии)
    3. GET  /apps                 -> если приложение уже есть, забираем ключи
    4. POST /apps                 -> иначе создаём и забираем ключи
"""

from __future__ import annotations

import html as html_module
import http.cookiejar
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Callable, Dict, Optional

SITE = "https://my.telegram.org"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class ApiAuthError(RuntimeError):
    """Ошибка на стороне my.telegram.org."""


class NotAuthorized(ApiAuthError):
    """Сессия не авторизована: нужен код из Telegram."""


_ERRORS = {
    "PHONE_NUMBER_INVALID": "номер не принят: проверь формат +79991234567",
    "PHONE_NUMBER_BANNED": "номер заблокирован в Telegram",
    "PHONE_CODE_INVALID": "неверный код из Telegram",
    "PHONE_CODE_EXPIRED": "код истёк, запроси новый",
    "PASSWORD_HASH_INVALID": "неверный код или пароль",
    "FLOOD": "слишком много попыток, подожди 10-15 минут",
    "FLOOD_WAIT": "слишком много попыток, подожди 10-15 минут",
    "AUTH_RESTART": "сессия сброшена, начни заново",
}


def _human_error(raw: str) -> str:
    key = (raw or "").strip().upper()
    for code, text in _ERRORS.items():
        if key.startswith(code):
            return text
    return raw or "неизвестная ошибка"


def _strip_tags(page: str) -> str:
    page = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", page)
    page = re.sub(r"(?s)<[^>]+>", " ", page)
    page = html_module.unescape(page)
    return re.sub(r"\s+", " ", page).strip()


def parse_apps_page(page: str) -> Optional[Dict[str, object]]:
    """Достать api_id/api_hash со страницы /apps. None, если приложения нет."""
    text = _strip_tags(page)

    id_match = re.search(r"api[\s_-]?id\D{0,40}?(\d{4,12})", text, re.IGNORECASE)
    hash_match = re.search(r"api[\s_-]?hash\D{0,40}?([0-9a-f]{32})", text, re.IGNORECASE)
    if not id_match or not hash_match:
        return None
    return {
        "api_id": int(id_match.group(1)),
        "api_hash": hash_match.group(1).lower(),
    }


def _form_hash(page: str) -> Optional[str]:
    patterns = (
        r"""name=["']hash["'][^>]*value=["']([^"']+)["']""",
        r"""value=["']([^"']+)["'][^>]*name=["']hash["']""",
    )
    for pattern in patterns:
        m = re.search(pattern, page, re.IGNORECASE)
        if m:
            return html_module.unescape(m.group(1))
    return None


def _ssl_context() -> Optional[ssl.SSLContext]:
    """Свой CA-бандл: в Chaquopy/термуксе системных сертификатов может не быть."""
    cafile = Path(__file__).with_name("cacert.pem")
    try:
        if cafile.exists():
            return ssl.create_default_context(cafile=str(cafile))
    except Exception:
        pass
    try:
        import certifi  # type: ignore
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        pass
    try:
        return ssl.create_default_context()
    except Exception:
        return None


class MyTelegramAuth:
    """HTTP-клиент my.telegram.org с cookie-сессией."""

    def __init__(self, timeout: float = 30.0, opener: Optional[urllib.request.OpenerDirector] = None):
        self.timeout = timeout
        self._jar = http.cookiejar.CookieJar()
        self._opener = opener or urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self._jar)
        )
        self._ssl = _ssl_context()
        self.phone: str = ""
        self.random_hash: str = ""
        self.authorized: bool = False

    # ---------------------------------------------------------------- transport
    def _open(self, url: str, data: Optional[Dict[str, str]] = None) -> str:
        body = urllib.parse.urlencode(data).encode("utf-8") if data is not None else None
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "application/json, text/html;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru,en;q=0.8",
            "Origin": SITE,
            "Referer": f"{SITE}/",
        }
        if body is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded; charset=UTF-8"
            headers["X-Requested-With"] = "XMLHttpRequest"
        request = urllib.request.Request(url, data=body, headers=headers)
        try:
            kwargs = {"timeout": self.timeout}
            if self._ssl is not None:
                kwargs["context"] = self._ssl
            with self._opener.open(request, **kwargs) as response:
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                return raw.decode(charset, errors="replace")
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            raise ApiAuthError(f"HTTP {exc.code}: {_human_error(raw[:200])}") from exc
        except urllib.error.URLError as exc:
            raise ApiAuthError(
                f"нет связи с my.telegram.org ({exc.reason}). Нужен рабочий интернет или VPN."
            ) from exc

    @staticmethod
    def _json(payload: str) -> Dict[str, object]:
        try:
            data = json.loads(payload)
        except Exception as exc:
            raise ApiAuthError("сайт вернул неожиданный ответ, попробуй позже") from exc
        if isinstance(data, bool):
            # /auth/login отвечает литералом true, когда вход прошёл.
            return {"ok": data}
        if isinstance(data, str):
            return {"ok": data}
        if not isinstance(data, dict):
            raise ApiAuthError("сайт вернул неожиданный ответ, попробуй позже")
        if data.get("error"):
            raise ApiAuthError(_human_error(str(data["error"])))
        return data

    # ------------------------------------------------------------------- steps
    def send_code(self, phone: str) -> None:
        """Запросить код подтверждения. Код приходит в Telegram от сервиса."""
        phone = (phone or "").strip().replace(" ", "").replace("-", "")
        if not re.match(r"^\+\d{7,15}$", phone):
            raise ApiAuthError("номер должен быть в формате +79991234567")
        payload = self._json(self._open(f"{SITE}/auth/send_password", {"phone": phone}))
        token = payload.get("random_hash")
        if not token:
            raise ApiAuthError("Telegram не выдал код: проверь номер и попробуй ещё раз")
        self.phone = phone
        self.random_hash = str(token)
        self.authorized = False

    def sign_in(self, code: str) -> None:
        """Войти по коду, который пришёл в Telegram."""
        if not self.random_hash:
            raise ApiAuthError("сначала запроси код")
        code = (code or "").strip()
        if not code:
            raise ApiAuthError("пустой код")
        payload = self._json(
            self._open(
                f"{SITE}/auth/login",
                {"phone": self.phone, "random_hash": self.random_hash, "password": code},
            )
        )
        if payload.get("error"):
            raise ApiAuthError(_human_error(str(payload["error"])))
        self.authorized = True
        self._verify_session()

    def _verify_session(self) -> None:
        page = self._open(f"{SITE}/apps")
        if "send_password" in page or "auth/login" in page:
            raise ApiAuthError("вход не подтвердился, попробуй ещё раз")
        self.authorized = True

    def fetch_app(self) -> Optional[Dict[str, object]]:
        """Уже созданное приложение аккаунта, если оно есть."""
        page = self._open(f"{SITE}/apps")
        return parse_apps_page(page)

    def create_app(
        self,
        title: str = "Colemailer",
        shortname: str = "colemailer",
        platform: str = "other",
        url: str = "",
        description: str = "",
    ) -> Dict[str, object]:
        """Создать приложение и вернуть api_id/api_hash."""
        page = self._open(f"{SITE}/apps")
        existing = parse_apps_page(page)
        if existing:
            return existing
        form_hash = _form_hash(page)
        if not form_hash:
            raise ApiAuthError("не нашёл форму создания приложения, зайди на my.telegram.org вручную")

        clean_short = re.sub(r"[^a-zA-Z0-9_]", "", shortname or "colemailer")[:32] or "colemailer"
        payload = self._open(
            f"{SITE}/apps",
            {
                "hash": form_hash,
                "app_title": (title or "Colemailer")[:64],
                "app_shortname": clean_short,
                "app_url": url or "",
                "app_platform": platform or "other",
                "app_desc": description or "",
            },
        )
        created = parse_apps_page(payload)
        if created:
            return created
        again = self.fetch_app()
        if again:
            return again
        raise ApiAuthError("приложение не создалось, попробуй ещё раз или сделай вручную")

    def close(self) -> None:
        self._jar.clear()
        self.authorized = False
        self.random_hash = ""


def obtain_credentials(
    phone: str,
    ask_code: Callable[[], str],
    title: str = "Colemailer",
    shortname: str = "colemailer",
    client: Optional[MyTelegramAuth] = None,
) -> Dict[str, object]:
    """Полный сценарий: код -> вход -> существующее или новое приложение."""
    auth = client or MyTelegramAuth()
    try:
        auth.send_code(phone)
        code = ask_code()
        auth.sign_in(code)
        app = auth.fetch_app()
        if app:
            app["source"] = "existing"
            return app
        created = auth.create_app(title=title, shortname=shortname)
        created["source"] = "created"
        return created
    finally:
        auth.close()
