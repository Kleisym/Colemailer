"""Инлайн-кнопки для постов рассылки.

Кнопки хранятся в шаблоне как список рядов:

    [["Купить", "https://t.me/manager"], ["Прайс", "cb:price"]]

Пользователь задаёт раскладку строками: одна строка — один ряд, кнопки внутри
строки разделяются `||` (или пишутся подряд). Так можно ставить по одной
кнопке в ряд, по две, по три — как угодно.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

MAX_TEXT = 64
MAX_URL = 2048
MAX_CALLBACK = 64
MAX_PER_ROW = 8
MAX_ROWS = 100

_TOKEN_RE = re.compile(
    r"""
    \[\s*(?P<label>[^\[\]\n]{1,64}?)\s*\]
    \s*
    (?:
        \(\s*(?P<paren>[^\s()]+)\s*\)
      | (?:->|=>)\s*(?P<arrow>[^\s]+)
    )
    """,
    re.VERBOSE,
)

_BETWEEN_RE = re.compile(r"^[\s|]*$")


class ButtonError(ValueError):
    """Неверный синтаксис кнопок."""


def _classify(target: str) -> Tuple[str, str]:
    t = target.strip()
    low = t.lower()
    if low.startswith(("cb:", "callback:")):
        return "callback", t.split(":", 1)[1]
    if low.startswith("callback_data:"):
        return "callback", t.split(":", 1)[1]
    if low.startswith(("http://", "https://", "tg://", "mailto:", "tel:")):
        return "url", t
    raise ButtonError(f"непонятная ссылка кнопки: {target}")


def parse_row(line: str) -> Optional[List[Dict[str, str]]]:
    """Разобрать одну строку в ряд кнопок. None, если строка не про кнопки."""
    stripped = line.strip()
    if not stripped.startswith("["):
        return None
    matches = list(_TOKEN_RE.finditer(stripped))
    if not matches:
        return None
    pos = 0
    for m in matches:
        if not _BETWEEN_RE.match(stripped[pos:m.start()]):
            return None
        pos = m.end()
    if not _BETWEEN_RE.match(stripped[pos:]):
        return None

    row: List[Dict[str, str]] = []
    for m in matches:
        label = (m.group("label") or "").strip()
        target = m.group("paren") or m.group("arrow") or ""
        if not label:
            raise ButtonError("у кнопки пустая подпись")
        if len(label) > MAX_TEXT:
            raise ButtonError(f"подпись кнопки длиннее {MAX_TEXT} символов: {label[:30]}…")
        kind, value = _classify(target)
        if kind == "url":
            if len(value) > MAX_URL:
                raise ButtonError("ссылка кнопки слишком длинная")
        else:
            if not value:
                raise ButtonError("у callback-кнопки пустые данные")
            if len(value.encode("utf-8")) > MAX_CALLBACK:
                raise ButtonError(f"callback-данные длиннее {MAX_CALLBACK} байт")
        row.append({"text": label, "type": kind, "value": value})
    if len(row) > MAX_PER_ROW:
        raise ButtonError(f"в ряду больше {MAX_PER_ROW} кнопок")
    return row


def extract_buttons(payload: str) -> Tuple[str, List[List[Dict[str, str]]]]:
    """Отделить хвост с кнопками от текста поста.

    Кнопки идут в конце: каждая строка — ряд вида `[Текст](ссылка)`.
    Если в конце нет ни одной такой строки, текст возвращается как есть.
    """
    if not payload:
        return "", []
    lines = payload.splitlines()
    rows: List[List[Dict[str, str]]] = []
    cut = len(lines)
    for idx in range(len(lines) - 1, -1, -1):
        row = parse_row(lines[idx])
        if row is None:
            break
        rows.insert(0, row)
        cut = idx
    if not rows:
        return payload, []
    if len(rows) > MAX_ROWS:
        raise ButtonError(f"рядов с кнопками больше {MAX_ROWS}")
    text = "\n".join(lines[:cut]).rstrip()
    return text, rows


def to_json(rows: Optional[Iterable[Sequence[Dict[str, str]]]]) -> str:
    if not rows:
        return ""
    clean: List[List[Dict[str, str]]] = []
    for row in rows:
        clean_row = []
        for btn in row:
            label = str(btn.get("text", "")).strip()[:MAX_TEXT]
            kind = str(btn.get("type", "") or "").strip().lower()
            value = str(btn.get("value", "") or "").strip()
            # Терпим и «плоскую» форму кнопки, снятую с чужого сообщения.
            if not value:
                if btn.get("url"):
                    kind, value = "url", str(btn["url"]).strip()
                elif btn.get("data"):
                    kind, value = "callback", str(btn["data"]).strip()
            if not label or not value:
                continue
            clean_row.append({"text": label, "type": "callback" if kind == "callback" else "url", "value": value})
        if clean_row:
            clean.append(clean_row[:MAX_PER_ROW])
    return json.dumps(clean, ensure_ascii=False) if clean else ""


def from_json(raw: Optional[str]) -> List[List[Dict[str, str]]]:
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    rows: List[List[Dict[str, str]]] = []
    for row in data[:MAX_ROWS]:
        if not isinstance(row, list):
            continue
        clean_row = []
        for btn in row:
            if not isinstance(btn, dict):
                continue
            label = str(btn.get("text", "")).strip()
            value = str(btn.get("value", "")).strip()
            kind = str(btn.get("type", "url")).strip().lower()
            if label and value:
                clean_row.append({"text": label[:MAX_TEXT], "type": "callback" if kind == "callback" else "url", "value": value})
        if clean_row:
            rows.append(clean_row)
    return rows


def build_markup(rows: Optional[Iterable[Sequence[Dict[str, str]]]]) -> Any:
    """Собрать telethon.ReplyInlineMarkup. Пустой список -> None.

    Telethon 1.45 переехал на KeyboardInlineButton + InlineButtonTypeUrl, а в
    1.36 (минимальная версия из requirements) были KeyboardButtonUrl и
    KeyboardButtonCallback. Поддерживаем оба варианта, иначе кнопки ломают
    всю отправку на одной из версий.
    """
    clean = from_json(to_json(rows)) if rows else []
    if not clean:
        return None
    from telethon.tl import types

    built_rows = []
    if hasattr(types, "KeyboardInlineButtonRow"):
        from telethon.tl.types import (
            InlineButtonTypeCallback,
            InlineButtonTypeUrl,
            KeyboardInlineButton,
            KeyboardInlineButtonRow,
            ReplyInlineMarkup,
        )

        for row in clean:
            buttons = []
            for btn in row:
                if btn["type"] == "callback":
                    kind = InlineButtonTypeCallback(data=btn["value"].encode("utf-8"))
                else:
                    kind = InlineButtonTypeUrl(url=btn["value"])
                buttons.append(KeyboardInlineButton(text=btn["text"], type=kind))
            if buttons:
                built_rows.append(KeyboardInlineButtonRow(buttons=buttons))
        return ReplyInlineMarkup(rows=built_rows) if built_rows else None

    from telethon.tl.types import (  # type: ignore[attr-defined]
        KeyboardButtonCallback,
        KeyboardButtonRow,
        KeyboardButtonUrl,
        ReplyInlineMarkup,
    )

    for row in clean:
        buttons = []
        for btn in row:
            if btn["type"] == "callback":
                buttons.append(KeyboardButtonCallback(text=btn["text"], data=btn["value"].encode("utf-8")))
            else:
                buttons.append(KeyboardButtonUrl(text=btn["text"], url=btn["value"]))
        if buttons:
            built_rows.append(KeyboardButtonRow(buttons=buttons))
    return ReplyInlineMarkup(rows=built_rows) if built_rows else None


def describe(rows: Optional[Iterable[Sequence[Dict[str, str]]]]) -> str:
    clean = from_json(to_json(rows)) if rows else []
    if not clean:
        return "нет"
    parts = []
    for row in clean:
        parts.append(" | ".join(f"{b['text']} → {b['value']}" for b in row))
    return "\n".join(parts)
