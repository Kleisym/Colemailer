# -*- coding: utf-8 -*-
"""Синхронизация папок: новые чаты подхватываются, пропавшие — паркуются.

Рассылка «по папке» живёт отдельно от списка чатов: пока бот работает, папку
могут поправить на телефоне. `sync_folder_broadcasts` — единственное место,
которое догоняет реальность, поэтому проверяются три свойства:

  * новый чат в папке попадает в рассылку;
  * уже известные чаты не пересоздаются и не сбивают таймер `last_sent_at`;
  * исчезнувшая папка перестаёт кормить рассылку — но только после 10
    промахов подряд, чтобы один сетевой сбой не остановил всё.
"""
import asyncio

from types import SimpleNamespace as NS

from telethon.tl.functions.messages import GetDialogFiltersRequest
from telethon.tl.types import InputPeerChat, InputPeerUser, TextWithEntities

import bot

ACCOUNT = 5
FOLDER = "Работа"
TEMPLATE = "promo"


class FolderClient:
    """Клиент, который умеет ровно то, что нужно синхронизации папок."""

    def __init__(self, folders=None, dialogs=None):
        # folders: {название: {groups: True, include_peers: [...], exclude_peers: [...]}}
        self.folders = folders or {}
        self.dialogs = list(dialogs or [])
        self.filter_calls = 0
        self.dialog_calls = 0

    async def __call__(self, request):
        assert isinstance(request, GetDialogFiltersRequest)
        self.filter_calls += 1
        filters = []
        for idx, (title, cfg) in enumerate(self.folders.items()):
            filters.append(NS(
                id=idx + 2,
                title=TextWithEntities(text=title, entities=[]),
                pinned_peers=list(cfg.get("pinned_peers", [])),
                include_peers=list(cfg.get("include_peers", [])),
                exclude_peers=list(cfg.get("exclude_peers", [])),
                groups=cfg.get("groups", False),
                broadcasts=cfg.get("broadcasts", False),
                contacts=False, non_contacts=False, bots=False,
                exclude_muted=False, exclude_archived=False,
            ))
        return NS(filters=filters)

    async def iter_dialogs(self, limit=5000):
        self.dialog_calls += 1
        for dialog in self.dialogs:
            yield dialog


def dialog(cid, *, group=False, channel=False, broadcast=False, user=False, archived=False):
    return NS(
        id=cid,
        is_group=group,
        is_channel=channel,
        is_user=user,
        archived=archived,
        entity=NS(broadcast=broadcast, bot=False, contact=None),
        dialog=NS(notify_settings=None),
    )


def service_for(client, db, account=ACCOUNT):
    return bot.BroadcasterService(client, account_id=account)


def enroll_folder(db, *, folder=FOLDER, template=TEMPLATE, account=ACCOUNT, interval=30):
    db.save_template(template, "hi", [], [])
    db.register_folder_broadcast(folder_name=folder, template_name=template,
                                 mode="interval", interval_seconds=interval,
                                 account_id=account)


def active_chats(db, account=ACCOUNT):
    return {t["chat_id"] for t in db.get_active_interval_tasks(account_id=account)}


# --------------------------------------------------------------------------- #
# подхват новых чатов
# --------------------------------------------------------------------------- #
def test_new_group_from_dialogs_is_enrolled(tmp_db):
    """Папка-фильтр «группы»: чаты берутся из iter_dialogs, а не из списка."""
    enroll_folder(tmp_db)
    client = FolderClient(
        {FOLDER: {"groups": True}},
        dialogs=[dialog(111, group=True), dialog(222, channel=True, broadcast=True)],
    )
    service = service_for(client, tmp_db)

    assert asyncio.run(service.sync_folder_broadcasts()) == 1
    assert active_chats(tmp_db) == {111}
    assert client.dialog_calls == 1


def test_new_chat_added_later_is_picked_up_on_the_next_sync(tmp_db):
    enroll_folder(tmp_db)
    client = FolderClient(
        {FOLDER: {"groups": True}},
        dialogs=[dialog(111, group=True)],
    )
    service = service_for(client, tmp_db)
    assert asyncio.run(service.sync_folder_broadcasts()) == 1

    client.dialogs.append(dialog(444, group=True))
    assert asyncio.run(service.sync_folder_broadcasts()) == 1
    assert active_chats(tmp_db) == {111, 444}


def test_explicit_folder_peers_are_enrolled_without_dialogs(tmp_db):
    enroll_folder(tmp_db)
    client = FolderClient({FOLDER: {"include_peers": [InputPeerUser(10, 0), InputPeerChat(20)]}})
    service = service_for(client, tmp_db)

    assert asyncio.run(service.sync_folder_broadcasts()) == 2
    assert active_chats(tmp_db) == {10, -20}
    assert client.dialog_calls == 0, "без флагов папки список диалогов не нужен"


def test_excluded_peers_are_not_enrolled(tmp_db):
    enroll_folder(tmp_db)
    client = FolderClient(
        {FOLDER: {"groups": True, "exclude_peers": [InputPeerUser(111, 0)]}},
        dialogs=[dialog(111, group=True), dialog(222, group=True)],
    )
    service = service_for(client, tmp_db)

    asyncio.run(service.sync_folder_broadcasts())
    assert active_chats(tmp_db) == {222}


# --------------------------------------------------------------------------- #
# идемпотентность
# --------------------------------------------------------------------------- #
def test_second_sync_does_not_duplicate_and_keeps_the_timer(tmp_db):
    enroll_folder(tmp_db)
    client = FolderClient({FOLDER: {"groups": True}}, dialogs=[dialog(111, group=True)])
    service = service_for(client, tmp_db)
    asyncio.run(service.sync_folder_broadcasts())

    task = tmp_db.get_active_interval_tasks(account_id=ACCOUNT)[0]
    with tmp_db._conn() as conn:
        conn.execute("UPDATE broadcast_tasks SET last_sent_at = ? WHERE id = ?",
                     (123456.0, task["id"]))

    assert asyncio.run(service.sync_folder_broadcasts()) == 0

    rows = tmp_db.get_active_interval_tasks(account_id=ACCOUNT)
    assert len(rows) == 1, "чат не должен задвоиться"
    assert rows[0]["last_sent_at"] == 123456.0, "таймер рассылки не сбрасывается синком"


def test_chat_removed_from_the_folder_is_parked(tmp_db):
    enroll_folder(tmp_db)
    client = FolderClient(
        {FOLDER: {"groups": True}},
        dialogs=[dialog(111, group=True), dialog(222, group=True)],
    )
    service = service_for(client, tmp_db)
    asyncio.run(service.sync_folder_broadcasts())

    client.dialogs = [dialog(111, group=True)]
    asyncio.run(service.sync_folder_broadcasts())

    assert active_chats(tmp_db) == {111}


def test_manually_stopped_chat_is_not_revived_by_a_sync(tmp_db):
    """`.стоп` в чате папки уважается: синк не включает задачу обратно."""
    enroll_folder(tmp_db)
    client = FolderClient({FOLDER: {"groups": True}}, dialogs=[dialog(111, group=True)])
    service = service_for(client, tmp_db)
    asyncio.run(service.sync_folder_broadcasts())

    tmp_db.stop_tasks(account_id=ACCOUNT, chat_ids=[111], manual=True)
    asyncio.run(service.sync_folder_broadcasts())

    assert active_chats(tmp_db) == set()


# --------------------------------------------------------------------------- #
# исчезнувшая папка: терпение на 10 промахов
# --------------------------------------------------------------------------- #
def test_missing_folder_is_tolerated_for_nine_syncs(tmp_db):
    enroll_folder(tmp_db)
    client = FolderClient({FOLDER: {"groups": True}}, dialogs=[dialog(111, group=True)])
    service = service_for(client, tmp_db)
    asyncio.run(service.sync_folder_broadcasts())

    client.folders.clear()  # папку переименовали на телефоне
    for _ in range(9):
        asyncio.run(service.sync_folder_broadcasts())
    assert active_chats(tmp_db) == {111}, "9 промахов — ещё ждём"


def test_missing_folder_parks_its_chats_on_the_tenth_sync(tmp_db):
    enroll_folder(tmp_db)
    client = FolderClient({FOLDER: {"groups": True}}, dialogs=[dialog(111, group=True)])
    service = service_for(client, tmp_db)
    asyncio.run(service.sync_folder_broadcasts())

    client.folders.clear()
    for _ in range(10):
        asyncio.run(service.sync_folder_broadcasts())
    assert active_chats(tmp_db) == set()


def test_folder_that_comes_back_resets_the_miss_counter(tmp_db):
    enroll_folder(tmp_db)
    client = FolderClient({FOLDER: {"groups": True}}, dialogs=[dialog(111, group=True)])
    service = service_for(client, tmp_db)
    asyncio.run(service.sync_folder_broadcasts())

    client.folders.clear()
    for _ in range(5):
        asyncio.run(service.sync_folder_broadcasts())
    client.folders[FOLDER] = {"groups": True}
    asyncio.run(service.sync_folder_broadcasts())

    client.folders.clear()
    for _ in range(9):
        asyncio.run(service.sync_folder_broadcasts())
    assert active_chats(tmp_db) == {111}, "счётчик промахов должен был обнулиться"
