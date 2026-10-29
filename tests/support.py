# -*- coding: utf-8 -*-
"""Общие помощники для тестов Colemailer.

Здесь нет самих тестов — только фабрики фейковых событий/клиентов и функции,
которые собирают обработчики так же, как это делает продакшен. Файл намеренно
лежит рядом с тестами, чтобы новые наборы не копировали моки по десять раз.
"""
from __future__ import annotations

from types import SimpleNamespace as NS
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

import bot
from telethon.tl.types import InputPeerChannel

# Счётчик аккаунта в тестах. Он же my_id: по нему classify_ping понимает,
# что сообщение адресовано нам.
MY_ID = 987654321
CHAT_ID = -1009988


class RecordingClient:
    """Минимальный клиент Telegram, который запоминает все вызовы.

    Telethon-клиент вызывается как `client(request)`, поэтому фейк реализует
    `__call__` и складывает запросы в `self.requests`. Методы отправки/удаления
    тоже записываются, чтобы тесты проверяли ровно то, что уходит в сеть.
    """

    def __init__(self, entities: Dict[str, Any] = None) -> None:
        self.requests: List[Any] = []
        self.sent_messages: List[Dict[str, Any]] = []
        self.deleted: List[Any] = []
        self.permissions: List[Any] = []
        self.forwarded: List[Any] = []
        self.handlers: Dict[str, Any] = {}
        # Разрешение @username -> id для команд вроде `.мутить @user`.
        self.entities: Dict[str, Any] = dict(entities or {})

    async def __call__(self, request: Any):
        self.requests.append(request)
        return None

    # --- регистрация обработчиков ------------------------------------------
    def on(self, builder):
        """Та же роль, что у `client.on` в Telethon: собрать корутины по имени."""
        def register(func):
            self.handlers[func.__name__] = func
            return func

        return register

    # --- отправка -----------------------------------------------------------
    async def send_message(self, peer, message=None, formatting_entities=None, **kw):
        self.sent_messages.append(
            {"peer": peer, "message": message, "entities": formatting_entities, "kwargs": kw}
        )
        return NS(id=1001)

    async def send_file(self, peer, file=None, caption=None, formatting_entities=None, **kw):
        self.sent_messages.append(
            {"peer": peer, "caption": caption, "entities": formatting_entities,
             "kwargs": kw, "file": file, "kind": "file"}
        )
        return NS(id=1002)

    async def delete_messages(self, chat_id, ids, **kw):
        self.deleted.append({"chat_id": chat_id, "ids": list(ids)})
        return []

    async def edit_permissions(self, chat_id, user_id, **kw):
        self.permissions.append({"chat_id": chat_id, "user_id": user_id, "kwargs": kw})
        return True

    async def get_input_entity(self, peer):
        return peer

    async def get_entity(self, peer):
        """Настоящий telethon-User: команды мьюта гоняют его через get_peer_id."""
        from telethon.tl.types import User

        if isinstance(peer, str):
            uid = self.entities.get(peer.lstrip("@"), 700001)
            return User(id=uid, username=peer.lstrip("@"), first_name="Peer", last_name="")
        if isinstance(peer, int):
            return User(id=peer, first_name="Peer", last_name="")
        return peer

    def request_names(self) -> List[str]:
        return [type(r).__name__ for r in self.requests]

    def request_classes(self) -> List[type]:
        return [type(r) for r in self.requests]


def make_handlers(client: Any = None, config: Optional[Dict[str, Any]] = None,
                  broadcaster: Any = None) -> Dict[str, Any]:
    """Зарегистрировать обработчики на фейковом клиенте и вернуть их по имени.

    `register_events` вешает функции через `@client.on(...)`, поэтому фейковый
    клиент повторяет только эту часть API. Каждый вызов создаёт новый клиент:
    повторная регистрация на том же объекте намеренно блокируется в bot.py.
    """
    cl = client if client is not None else RecordingClient()
    br = broadcaster if broadcaster is not None else NS(on_incoming_message=lambda chat: None)
    bot.register_events(cl, br, MY_ID, config or dict(auto_sub_enabled=False))
    return cl.handlers


def group_event(
    text: str = "",
    mid: int = 7001,
    sender_id: int = 456789,
    is_reply: bool = False,
    mentioned: bool = False,
    entities: Optional[List[Any]] = None,
    media: Any = None,
    chat_id: int = CHAT_ID,
    reply_to: Any = None,
    is_private: bool = False,
):
    """Фейковое событие NewMessage, максимально похожее на telethon-овское."""
    message = NS(
        id=mid,
        mentioned=mentioned,
        entities=entities or [],
        media=media,
        raw_text=text,
        message=text,
        sender_id=sender_id,
        input_chat=InputPeerChannel(9988, 1),
    )
    event = NS(
        chat_id=chat_id,
        id=mid,
        sender_id=sender_id,
        is_private=is_private,
        is_reply=is_reply,
        raw_text=text,
        message=message,
        input_chat=InputPeerChannel(9988, 1),
        out=False,
        get_reply_message=AsyncMock(return_value=reply_to),
    )
    return event


def command_event(raw: str, chat_id: int = CHAT_ID, mid: int = 9001) -> Any:
    """Событие команды владельца: есть respond/edit, как у настоящего message."""
    replies: List[str] = []

    async def respond(text, **kw):
        replies.append(text)
        return NS(id=9002, text=text, delete=AsyncMock())

    async def edit(text, **kw):
        replies.append(text)
        return NS(id=9003, text=text, delete=AsyncMock())

    async def get_chat():
        return NS(id=chat_id, title="Тестовый чат")

    event = NS(
        chat_id=chat_id,
        id=mid,
        sender_id=MY_ID,
        out=True,
        is_reply=False,
        is_private=True,
        raw_text=raw,
        message=NS(id=mid, raw_text=raw, message=raw, media=None),
        respond=respond,
        edit=edit,
        get_chat=get_chat,
        get_reply_message=AsyncMock(return_value=None),
        replies=replies,
    )
    return event


def hybrid_task_row(db: Any, *, count: int = 0, last_sent_ago: float = 10.0,
                    threshold: int = 15, interval: int = 900,
                    ready_ago: Optional[float] = None, template: str = "h") -> Dict[str, Any]:
    """Создать hybrid-задачу с точно заданным состоянием счётчика.

    `last_sent_ago` / `ready_ago` — сколько секунд назад произошло событие,
    так что тест не зависит от реальных часов и не спит.
    """
    import time

    db.save_template(template, "hybrid text", [], [])
    db.add_or_update_broadcast(chat_id=555, template_name=template, mode="hybrid",
                               interval_seconds=interval, counter_threshold=threshold,
                               account_id=1)
    task = db.get_active_interval_tasks(account_id=1)[0]
    ready_at = 0.0 if ready_ago is None else time.time() - ready_ago
    with db._conn() as conn:
        conn.execute(
            "UPDATE broadcast_tasks SET current_count = ?, last_sent_at = ?, "
            "counter_ready_at = ?, send_pending = 0 WHERE id = ?",
            (count, time.time() - last_sent_ago, ready_at, task["id"]),
        )
    return db.get_active_interval_tasks(account_id=1)[0]
