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
from html.parser import HTMLParser
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
        rf"""(?:id|name|for)=["']{field}["'][^>]*>(?:(?!<label)[\s\S]){{0,600}}?({value_re})""",
    )
    for pattern in patterns:
        m = re.search(pattern, page, re.IGNORECASE | re.DOTALL)
        if m:
            return html_module.unescape(m.group(1))
    return None


class _FormParser(HTMLParser):
    """Собирает формы и их поля. Нужен, чтобы взять hash именно формы
    создания приложения, а не первой попавшейся (например, формы удаления)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.forms: list[dict] = []
        self._current: Optional[dict] = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        values = dict(attrs)
        if tag == "form":
            self._current = {
                "action": values.get("action") or "",
                "id": values.get("id") or "",
                "fields": {},
            }
            self.forms.append(self._current)
            return
        if self._current is None:
            return
        if tag in ("input", "textarea", "select") and values.get("name"):
            if "disabled" in values:
                return
            if tag == "input" and (values.get("type") or "").lower() in ("radio", "checkbox") and "checked" not in values:
                return
            self._current["fields"][values["name"]] = values.get("value") or ""

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self._current = None


class _LinkParser(HTMLParser):
    """Ссылки страницы /apps: список приложений кликабельный, а ключи лежат
    уже на странице конкретного приложения."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, str]] = []
        self._href: Optional[str] = None
        self._text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._text = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._href is not None:
            self.links.append((self._href, " ".join(self._text).strip()))
            self._href = None
            self._text = []


def _app_links(page: str) -> list[str]:
    """Кандидаты на страницу приложения из списка /apps."""
    parser = _LinkParser()
    try:
        parser.feed(page)
    except Exception:
        return []
    result: list[str] = []
    for href, text in parser.links:
        low = href.lower()
        if not href or any(bad in low for bad in ("logout", "delete", "/auth/", "send_password")):
            continue
        if "app_id=" in low or re.search(r"/apps/\d+", low):
            result.append(href)
        elif "active app" in text.lower() or "created" in text.lower():
            result.append(href)
    # Иногда ссылка собирается JS/onclick — ищем app_id в тексте страницы.
    for match in re.findall(
        r'(?:href|onclick|data-url|data-href)\s*=\s*["\']([^"\']*app_id=[^"\']*)["\']',
        page,
        re.IGNORECASE,
    ):
        result.append(html_module.unescape(match))
    seen: set[str] = set()
    unique: list[str] = []
    for href in result:
        if href not in seen:
            seen.add(href)
            unique.append(href)
    return unique


def _create_form(page: str) -> Optional[dict]:
    parser = _FormParser()
    try:
        parser.feed(page)
    except Exception:
        return None
    for form in parser.forms:
        fields = form.get("fields") or {}
        if (form.get("id") == "app_create_form" and
                "app_title" in fields and "app_shortname" in fields):
            return form
    return None


def _valid_app(api_id: int, api_hash: str) -> bool:
    if not 1000 <= api_id <= 2**31 - 1:
        return False
    if not re.fullmatch(r"[0-9a-f]{32}", api_hash):
        return False
    return True


class _CredentialCards(HTMLParser):
    """Read values from the same small container as each credential label."""

    _void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = {"parent": None, "children": [], "values": [], "labels": set()}
        self.stack = [self.root]
        self.labels = {"id": [], "hash": []}
        self.ignored = 0
        self.modern = False
        self.has_card = False
        self.has_data_value = False

    def handle_starttag(self, tag, attrs):
        if self.ignored or tag in ("script", "style"):
            if tag in ("script", "style"):
                self.ignored += 1
            return
        parent = self.stack[-1]
        attributes = dict(attrs)
        classes = set((attributes.get("class") or "").split())
        if classes.intersection({"cred", "vv"}):
            self.modern = True
        self.has_card |= "card" in classes
        self.has_data_value |= any(key in ("data-copy", "data-value") for key, _ in attrs)
        node = {"parent": parent, "children": [], "values": [], "labels": set(), "tag": tag, "value_text": "vv" in classes or parent.get("value_text", False)}
        for key, value in attrs:
            if key in ("data-copy", "data-value") and value:
                node["values"].append(value)
        parent["children"].append(node)
        if tag not in self._void:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self._void and not self.ignored:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if self.ignored:
            if tag in ("script", "style"):
                self.ignored -= 1
            return
        if tag in self._void:
            return
        for idx in range(len(self.stack) - 1, 0, -1):
            if self.stack[idx]["tag"] == tag:
                del self.stack[idx:]
                break

    def handle_data(self, data):
        if self.ignored:
            return
        node = self.stack[-1]
        if node.get("value_text"):
            node["values"].append(data)
        for kind in ("id", "hash"):
            if re.search(r"\bapi[\s_-]*" + kind + r"\b", data, re.IGNORECASE):
                node["labels"].add(kind)
                self.labels[kind].append(node)

    @staticmethod
    def _contents(node):
        values = list(node["values"])
        labels = set(node["labels"])
        for child in node["children"]:
            child_values, child_labels = _CredentialCards._contents(child)
            values.extend(child_values)
            labels.update(child_labels)
        return values, labels

    def value(self, kind):
        pattern = r"\d{4,12}" if kind == "id" else r"[0-9a-fA-F]{32}"
        matches = set()
        for label in self.labels[kind]:
            node = label
            while node is not None and node is not self.root:
                values, labels = self._contents(node)
                if len(labels) > 1:
                    break
                candidates = {v.strip() for v in values if re.fullmatch(pattern, v.strip())}
                if candidates:
                    if len(candidates) != 1:
                        return None
                    matches.update(candidates)
                    break
                node = node["parent"]
        return next(iter(matches)) if len(matches) == 1 else None


def _parse_credential_cards(page: str) -> tuple[bool, Optional[Dict[str, object]]]:
    parser = _CredentialCards()
    try:
        parser.feed(page)
        if not (parser.modern or (parser.has_card and parser.has_data_value)):
            return False, None
        raw_id = parser.value("id")
        raw_hash = parser.value("hash")
        if raw_id and raw_hash and _valid_app(int(raw_id), raw_hash.lower()):
            return True, {"api_id": int(raw_id), "api_hash": raw_hash.lower()}
    except (ValueError, RecursionError):
        return True, None
    return True, None


def parse_apps_page(page: str) -> Optional[Dict[str, object]]:
    """Достать api_id/api_hash со страницы /apps. None, если приложения нет.

    my.telegram.org держит значения то в тексте (`<span><strong>`), то в
    value="" инпута — поэтому сначала смотрим разметку по id/name, затем
    текст и JS/JSON. Пробелы и NBSP внутри значений нормализуются.
    """
    handled, found = _parse_credential_cards(page)
    if handled:
        return found

    compact = re.sub(r"[\s\u00a0\u200b-]", "", page)
    raw_id = _attr_value(compact, "app_id", r"\d{4,12}")
    raw_hash = _attr_value(compact, "app_hash", r"[0-9a-fA-F]{32}")
    if raw_id and raw_hash:
        api_id = int(raw_id)
        api_hash = raw_hash.lower()
        if _valid_app(api_id, api_hash):
            return {"api_id": api_id, "api_hash": api_hash}

    # JS/JSON: app_id/apiId/appId, app_hash/apiHash/appHash.
    id_keys = r"(?:api[_-]?id|app[_-]?id|apiId|appId)"
    hash_keys = r"(?:api[_-]?hash|app[_-]?hash|apiHash|appHash)"
    js_id = re.search(
        rf'["\']?{id_keys}["\']?\s*[:=]\s*["\']?(\d{{4,12}})', compact, re.IGNORECASE
    )
    js_hash = re.search(
        rf'["\']?{hash_keys}["\']?\s*[:=]\s*["\']?([0-9a-fA-F]{{32}})', compact, re.IGNORECASE
    )
    if js_id and js_hash:
        api_id = int(js_id.group(1))
        api_hash = js_hash.group(1).lower()
        if _valid_app(api_id, api_hash):
            return {"api_id": api_id, "api_hash": api_hash}

    text = re.sub(r"[\s\u00a0\u200b-]", "", _strip_tags(page))
    id_match = re.search(r"api[_-]?id(?:(?!api[_-]?hash)[^0-9]){0,80}?(\d{4,12})", text, re.IGNORECASE)
    hash_match = re.search(r"api[_-]?hash[^0-9a-f]{0,80}?([0-9a-f]{32})", text, re.IGNORECASE)
    if not id_match or not hash_match:
        return None
    api_id = int(id_match.group(1))
    api_hash = hash_match.group(1).lower()
    if not _valid_app(api_id, api_hash):
        return None
    return {"api_id": api_id, "api_hash": api_hash}


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


def _same_origin(url: str) -> bool:
    expected = urllib.parse.urlsplit(SITE)
    actual = urllib.parse.urlsplit(url)
    return (actual.scheme == expected.scheme and actual.netloc == expected.netloc
            and actual.username is None and actual.password is None)


class _SameOriginRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not _same_origin(newurl):
            raise ApiAuthError("переход на посторонний сайт отклонён")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


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
            handlers: list = [urllib.request.HTTPCookieProcessor(self._jar), _SameOriginRedirect()]
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
    def _open(self, url: str, data: Optional[Dict[str, str]] = None, ajax: bool = True) -> str:
        if not _same_origin(url):
            raise ApiAuthError("запрос на посторонний сайт отклонён")
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
            if ajax:
                headers["X-Requested-With"] = "XMLHttpRequest"
            headers["Referer"] = f"{SITE}/apps" if url.rstrip("/").endswith("/apps") else f"{SITE}/"
        request = urllib.request.Request(url, data=body, headers=headers)
        try:
            with self._opener.open(request, timeout=self.timeout) as response:
                raw = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                return raw.decode(charset, errors="replace")
        except urllib.error.HTTPError as exc:
            stage = {
                "/auth/send_password": "запрос кода",
                "/auth/login": "вход по коду",
                "/apps": "чтение приложения",
                "/apps/create": "создание приложения",
            }.get(urllib.parse.urlsplit(url).path, "запрос")
            details = []
            try:
                payload = json.loads(exc.read(16384).decode("utf-8", errors="replace"))
                if isinstance(payload, dict):
                    # Only fixed codes/field names can enter logs. Server text may
                    # contain account information or authentication secrets.
                    codes = set(_ERRORS) | {"APP_TITLE_INVALID", "APP_SHORTNAME_INVALID", "APP_SHORTNAME_OCCUPIED"}
                    for key in ("error", "text"):
                        value = payload.get(key)
                        if isinstance(value, str) and value in codes:
                            details.append(value)
                            break
                    field = payload.get("field")
                    if field in ("app_title", "app_shortname", "app_url", "app_platform", "app_desc", "app_description"):
                        details.append("поле " + field)
            except (ValueError, TypeError, OSError):
                pass
            suffix = ": " + ", ".join(details) if details else ""
            raise ApiAuthError(f"HTTP {exc.code} от my.telegram.org ({stage}){suffix}") from exc
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
        """Есть ли сохранённая неистёкшая cookie входа my.telegram.org."""
        try:
            return any(cookie.name == "stel_token" and not cookie.is_expired() for cookie in self._jar)
        except Exception:
            return False

    def save_cookies(self) -> None:
        if self._cookie_path is None:
            return
        try:
            if not list(self._jar):
                return
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
        self.authorized = False
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
        if payload.get("ok") is False:
            raise ApiAuthError("вход не подтвердился, проверь код и попробуй ещё раз")
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

    def _follow_app_links(self, page: str) -> Optional[Dict[str, object]]:
        """Пройти по ссылкам списка приложений и разобрать карточку."""
        for href in _app_links(page):
            candidate = urllib.parse.urljoin(SITE, href)
            if not _same_origin(candidate):
                continue
            parsed = urllib.parse.urlsplit(candidate)
            query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
            if parsed.path == "/apps":
                if set(query) != {"app_id"} or len(query["app_id"]) != 1 or not query["app_id"][0].isdigit():
                    continue
            elif not re.fullmatch(r"/apps/\d+", parsed.path) or parsed.query:
                continue
            try:
                detail = self._open(candidate)
            except Exception:
                continue
            found = parse_apps_page(detail)
            if found:
                self.save_cookies()
                return found

        return None

    def fetch_app(self) -> Optional[Dict[str, object]]:
        """Уже созданное приложение аккаунта, если оно есть."""
        page = self._open(f"{SITE}/apps")
        self.save_cookies()
        found = parse_apps_page(page)
        if found:
            return found
        return self._follow_app_links(page)

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
        if not existing:
            existing = self._follow_app_links(page)
        if existing:
            return existing
        form = _create_form(page)
        if not form:
            raise ApiAuthError(
                "не нашёл форму создания приложения, зайди на my.telegram.org вручную"
            )

        clean_short = re.sub(r"[^a-zA-Z0-9_]", "", shortname or "colemailer")[:32] or "colemailer"
        values = {
            "app_title": (title or "Colemailer")[:64],
            "app_shortname": clean_short,
            "app_url": url or "",
            "app_platform": platform or "other",
            "app_desc": description or "",
            "app_description": description or "",
        }
        # Отправляем ровно поля этой формы: у Telegram встречается и
        # app_desc, и app_description. hash берётся из формы создания, а не
        # из первой попавшейся (например, формы удаления).
        data = dict(form.get("fields") or {})
        for name in list(data.keys()):
            if name in values:
                data[name] = values[name]
        if not data.get("hash"):
            raise ApiAuthError("не нашёл hash формы создания приложения")

        # The Telegram site's app_create_form is submitted by JavaScript.
        form_action = str(form.get("action") or "")
        if form_action and not _same_origin(urllib.parse.urljoin(SITE, form_action)):
            raise ApiAuthError("форма создания ведёт на посторонний сайт")
        payload = self._open(f"{SITE}/apps/create", data, ajax=False)
        created = parse_apps_page(payload)
        if created:
            self.save_cookies()
            return created
        again = self.fetch_app()
        if again:
            return again
        raise ApiAuthError("не удалось получить ключи после запроса создания; проверь приложение на my.telegram.org")

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
