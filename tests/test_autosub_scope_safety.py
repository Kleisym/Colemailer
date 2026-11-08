# -*- coding: utf-8 -*-
"""Регрессии области авто-подписки и безопасной обработки кнопок."""

import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

from telethon import errors
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import GetDialogFiltersRequest, UpdateDialogFilterRequest
from telethon.tl.functions.account import UpdateNotifySettingsRequest
from telethon.tl.types import InputPeerChannel, TextWithEntities, User

import bot
from tests.support import CHAT_ID, MY_ID, RecordingClient, group_event


class FolderClient(RecordingClient):
    def __init__(self, filters, bots=()):
        super().__init__()
        self.filters = filters
        self.bots = set(bots)

    async def __call__(self, request):
        self.requests.append(request)
        if isinstance(request, GetDialogFiltersRequest):
            return NS(filters=self.filters)
        return None

    async def get_entity(self, peer):
        name = str(peer).lstrip("@").split("?", 1)[0]
        if name in self.bots:
            return User(id=700777, username=name, bot=True, first_name="Crypto")
        return await super().get_entity(peer)


class AlreadyJoinedClient(FolderClient):
    async def __call__(self, request):
        if isinstance(request, JoinChannelRequest):
            self.requests.append(request)
            raise errors.UserAlreadyParticipantError(request)
        return await super().__call__(request)


def _folder(title="автосабнутое"):
    return NS(
        id=7,
        title=TextWithEntities(text=title, entities=[]),
        pinned_peers=[],
        include_peers=[],
        exclude_peers=[],
        groups=False,
        broadcasts=False,
        contacts=False,
        non_contacts=False,
        bots=False,
        exclude_muted=False,
        exclude_archived=False,
    )


def _event(text, *, mid=93001, chat_id=CHAT_ID, buttons=()):
    event = group_event(text=text, mid=mid, chat_id=chat_id, mentioned=False)
    event.message.reply_markup = NS(rows=[NS(buttons=list(buttons))]) if buttons else None
    event.message.click = AsyncMock()
    return event


def _enable_broadcast(tmp_db, chat_id=CHAT_ID):
    tmp_db.save_template("scope_test", "text", [], [])
    tmp_db.add_or_update_broadcast(
        chat_id=chat_id,
        template_name="scope_test",
        mode="interval",
        interval_seconds=900,
        account_id=MY_ID,
    )


def _handlers(client, config=None):
    cfg = {
        "auto_sub_enabled": True,
        "auto_sub_folder": "автосабнутое",
        "auto_read_spam_pings": True,
    }
    cfg.update(config or {})
    bot.register_events(client, NS(on_incoming_message=lambda _chat: None), MY_ID, acc_cfg=cfg)
    return client.handlers


def test_gatekeeper_is_ignored_outside_broadcast_chat(tmp_db):
    client = FolderClient([_folder()])
    handlers = _handlers(client)
    event = _event(
        "Kleisym, чтобы писать в чат, необходимо подписаться на канал: @required_channel",
        mid=93001,
        chat_id=-1004444,
        buttons=[NS(text="Подписаться 1", url="https://t.me/required_channel")],
    )

    asyncio.run(handlers["incoming_handler"](event))

    assert not any(isinstance(req, JoinChannelRequest) for req in client.requests)
    assert not any(isinstance(req, UpdateNotifySettingsRequest) for req in client.requests)
    assert not any(isinstance(req, UpdateDialogFilterRequest) for req in client.requests)
    event.message.click.assert_not_awaited()


def test_gatekeeper_still_runs_in_chat_with_active_broadcast(tmp_db):
    _enable_broadcast(tmp_db)
    client = FolderClient([_folder()])
    handlers = _handlers(client)
    event = _event(
        "Kleisym, чтобы писать в чат, необходимо подписаться на канал: @required_channel",
        mid=93002,
        buttons=[
            NS(text="Подписаться 1", url="https://t.me/required_channel"),
            NS(text="Проверить", url=None),
        ],
    )

    asyncio.run(handlers["incoming_handler"](event))

    assert any(isinstance(req, JoinChannelRequest) for req in client.requests)
    assert any(isinstance(req, UpdateNotifySettingsRequest) for req in client.requests)
    assert any(isinstance(req, UpdateDialogFilterRequest) for req in client.requests)
    assert event.message.click.await_args_list == [((0, 1), {})]


def test_bot_target_never_sends_start_or_auto_mutes(tmp_db):
    client = FolderClient([_folder()], bots={"CryptoBot"})

    result = asyncio.run(bot.join_and_silence_target(client, "@CryptoBot?start=invoice", "автосабнутое"))

    assert result is False
    assert client.sent_messages == []
    assert not any(isinstance(req, JoinChannelRequest) for req in client.requests)
    assert not any(isinstance(req, UpdateNotifySettingsRequest) for req in client.requests)
    assert not any(isinstance(req, UpdateDialogFilterRequest) for req in client.requests)


def test_already_joined_channel_still_gets_muted_and_filed(tmp_db):
    client = AlreadyJoinedClient([_folder()])

    result = asyncio.run(bot.join_and_silence_target(client, "@required_channel", "автосабнутое"))

    assert result is True
    assert any(isinstance(req, UpdateNotifySettingsRequest) for req in client.requests)
    assert any(isinstance(req, UpdateDialogFilterRequest) for req in client.requests)


def test_payment_crypto_button_is_not_clicked_or_followed(tmp_db):
    _enable_broadcast(tmp_db)
    client = FolderClient([_folder()], bots={"CryptoBot"})
    handlers = _handlers(client)
    event = _event(
        "Kleisym, чтобы писать в чат, необходимо подписаться на канал: @required_channel",
        mid=93003,
        buttons=[
            NS(text="Подписаться и оплатить", url="https://t.me/CryptoBot?start=invoice123"),
            NS(text="Оплатить TON", url="https://tonkeeper.com/transfer"),
            NS(text="Проверить", url=None),
        ],
    )

    asyncio.run(handlers["incoming_handler"](event))

    assert client.sent_messages == []
    assert event.message.click.await_args_list == [((0, 2), {})]
    joined = [req for req in client.requests if isinstance(req, JoinChannelRequest)]
    assert len(joined) == 1
    assert getattr(joined[0].channel, "username", None) == "required_channel"

