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


def _attr_value(page: str, field: str, value_re: str) -> Optional[str]:
    """Значение поля по id/name, в каком бы порядке ни шли атрибуты."""
    patterns = (
        rf"""(?:id|name)=["']{field}["'][^>]{{0,300}}?value=["']({value_re})["']""",
        rf"""value=["']({value_re})["'][^>]{{0,300}}?(?:id|name)=["']{field}["']""",
        rf"""(?:id|name|for)=["']{field}["'][^>]*>[\s\S]{{0,600}}?({value_re})""",
    )
    for pattern in patterns:
        m = re.search(pattern, page, re.IGNORECASE | re.DOTALL)
        if m:
            return html_module.unescape(m.group(1))
    return None


def parse_apps_page(page: str) -> Optional[Dict[str, object]]:
    """Достать api_id/api_hash со страницы /apps. None, если приложения нет.

    my.telegram.org держит значения то в тексте (`<span><strong>`), то в
    value="" инпута — поэтому сначала смотрим разметку по id/name, затем
    текст. Раньше парсер понимал только текст и на реальной странице с
    существующим приложением возвращал None: бот шёл создавать новое и
    получал «приложение не создалось».
    """
    raw_id = _attr_value(page, "app_id", r"\d{4,12}")
    raw_hash = _attr_value(page, "app_hash", r"[0-9a-fA-F]{32}")
    if raw_id and raw_hash:
        return {"api_id": int(raw_id), "api_hash": raw_hash.lower()}

    # Последний шанс: значения в JS/JSON или в нестандартной разметке.
    loose_id = re.search(r"app[_\"'\s:-]{0,20}id[^0-9]{0,80}(\d{4,12})", page, re.IGNORECASE)
    loose_hash = re.search(r"app[_\"'\s:-]{0,20}hash[^0-9a-f]{0,80}([0-9a-f]{32})", page, re.IGNORECASE)
    if loose_id and loose_hash:
        return {"api_id": int(loose_id.group(1)), "api_hash": loose_hash.group(1).lower()}

    text = _strip_tags(page)
    id_match = re.search(r"api[\s_-]?id\D{0,60}?(\d{4,12})", text, re.IGNORECASE)
    hash_match = re.search(r"api[\s_-]?hash\D{0,60}?([0-9a-f]{32})", text, re.IGNORECASE)
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

    def __init__(
        self,
        timeout: float = 30.0,
        opener: Optional[urllib.request.OpenerDirector] = None,
        cookie_path: Optional[str] = None,
    ):
        self.timeout = timeout
        self._cookie_path = Path(cookie_path) if cookie_path else None
        if self._cookie_path is not None:
            self._jar: http.cookiejar.CookieJar = http.cookiejar.LWPCookieJar(str(self._cookie_path))
            if self._cookie_path.exists():
                try:
                    self._jar.load(ignore_discard=True, ignore_expires=False)
                except Exception:
                    # Битый/старый файл не мешает новому входу.
                    pass
        else:
            self._jar = http.cookiejar.CookieJar()
        self._ssl = _ssl_context()
        if opener is not None:
            self._opener = opener
        else:
            handlers: list = [urllib.request.HTTPCookieProcessor(self._jar)]
            if self._ssl is not None:
                # context передаётся в HTTPSHandler при сборке opener:
                # OpenerDirector.open() такого аргумента не принимает
                # (именно на этом падало авто-получение в APK).
                handlers.append(urllib.request.HTTPSHandler(context=self._ssl))
            self._opener = urllib.request.build_opener(*handlers)
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
            with self._opener.open(request, timeout=self.timeout) as response:
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
    def has_session(self) -> bool:
        """Есть ли сохранённая cookie входа my.telegram.org."""
        try:
            return any(cookie.name == "stel_token" for cookie in self._jar)
        except Exception:
            return False

    def save_cookies(self) -> None:
        if self._cookie_path is None:
            return
        try:
            self._cookie_path.parent.mkdir(parents=True, exist_ok=True)
            if hasattr(self._jar, "save"):
                self._jar.save(ignore_discard=True, ignore_expires=False)
        except Exception:
            pass

    def clear_cookies(self) -> None:
        try:
            self._jar.clear()
        except Exception:
            pass
        if self._cookie_path is not None:
            try:
                self._cookie_path.unlink(missing_ok=True)
            except Exception:
                pass

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
                {
                    "phone": self.phone,
                    "random_hash": self.random_hash,
                    "password": code,
                    "remember": "1",
                },
            )
        )
        if payload.get("error"):
            raise ApiAuthError(_human_error(str(payload["error"])))
        self.authorized = True
        self.save_cookies()
        self._verify_session()
        self.save_cookies()

    def _verify_session(self) -> None:
        page = self._open(f"{SITE}/apps")
        low = page.lower()
        # После входа на /apps есть раздел API development tools и поля api_id.
        # Страница логина, наоборот, содержит форму /auth/send_password.
        if "api development tools" in low or "app api_id" in low:
            self.authorized = True
            return
        if 'action="/auth/send_password"' in low or 'action="/auth/login"' in low or "send_password" in low:
            raise ApiAuthError("вход не подтвердился, попробуй ещё раз")
        # Неизвестная разметка: не считаем вход провалившимся, дальше проверит
        # fetch_app()/create_app().
        self.authorized = True

    def fetch_app(self) -> Optional[Dict[str, object]]:
        """Уже созданное приложение аккаунта, если оно есть."""
        page = self._open(f"{SITE}/apps")
        self.save_cookies()
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
            self.save_cookies()
            return created
        again = self.fetch_app()
        if again:
            return again
        raise ApiAuthError("приложение не создалось, попробуй ещё раз или сделай вручную")

    def close(self) -> None:
        self.save_cookies()
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
