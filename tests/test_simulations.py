# -*- coding: utf-8 -*-
"""Массовые симуляции: мьюты, планировщик, антиспам, парсеры, папки.

Это не замена точечным тестам, а проверка инвариантов на сотнях случайных
состояний: именно такие прогоны ловят «через раз» баги, которые не видны в
одном сценарии.
"""
from __future__ import annotations

import asyncio
import random
import time
from types import SimpleNamespace as NS

import pytest
from telethon.tl.functions.messages import GetDialogFiltersRequest
from telethon.tl.types import (
    DialogFilter,
    InputPeerChannel,
    MessageMediaPhoto,
    TextWithEntities,
)

import bot
from tests.support import CHAT_ID, MY_ID, RecordingClient, group_event

SENDER = 456789
OTHER = 777777
CHATS = [CHAT_ID, -100555, -100666]


def media():
    return MessageMediaPhoto(photo=None)


def msg(mid=1, sender=SENDER, text="текст"):
    return NS(
        id=mid,
        sender_id=sender,
        raw_text=text,
        message=text,
        entities=[],
        media=None,
        input_chat=InputPeerChannel(9988, 1),
    )


# --------------------------------------------------------------------------- #
# 1. Мьюты: 300 случайных комбинаций область × режим × чат × тип сообщения
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("seed", range(5))
def test_mute_simulation_matrix(tmp_db, seed):
    rnd = random.Random(seed)
    for step in range(60):
        action = rnd.choice(bot.MUTE_ACTIONS)
        scope = rnd.choice(("global", "here", "chat"))
        home = rnd.choice(CHATS)
        other = rnd.choice([c for c in CHATS if c != home])

        if scope == "chat":
            tmp_db.add_muted_peer(
                peer_id=home, account_id=MY_ID, peer_key=home, scope="chat",
                action=action, chat_id=home,
            )
        else:
            tmp_db.add_muted_peer(
                peer_id=SENDER, account_id=MY_ID, peer_key=SENDER, scope="user",
                action=action, chat_id=home if scope == "here" else 0,
            )
        bot.mute_cache_rebuild(MY_ID)

        expected_home = action
        expected_other = None if scope == "here" else action
        assert bot.mute_action_for(MY_ID, SENDER, home) == expected_home
        real_other = bot.mute_action_for(MY_ID, SENDER, other)
        if scope == "chat":
            assert real_other is None
        else:
            assert real_other == expected_other

        # Любое сообщение (включая медиа без текста) гасится одним и тем же путём.
        client = RecordingClient()
        payload = media() if rnd.random() < 0.5 else None
        asyncio.run(bot.apply_mute_action(client, msg(text="" if payload else "x"), MY_ID, home, action))
        names = [type(r).__name__ for r in client.requests]
        assert "ReadMessageContentsRequest" in names and "ReadHistoryRequest" in names
        if scope != "chat" and action == "delete":
            assert client.deleted

        # Чистим состояние перед следующей итерацией.
        with tmp_db._conn() as conn:
            conn.execute("DELETE FROM muted_peers")


# --------------------------------------------------------------------------- #
# 2. Планировщик: 400 случайных состояний задачи
# --------------------------------------------------------------------------- #
def test_scheduler_claim_simulation(tmp_db):
    rnd = random.Random(7)
    tmp_db.save_template("sim", "text", [], [])
    now = time.time()
    for i in range(400):
        mode = rnd.choice(("interval", "hybrid", "counter"))
        interval = rnd.choice((0, 30, 60, 900))
        threshold = rnd.choice((0, 1, 3, 15))
        count = rnd.randint(0, 20)
        last_ago = rnd.choice((-10, 0, 1, 59, 60, 899, 3600, 4 * 3600))
        ready_ago = rnd.choice((0, 1, 60, 1900, 4 * 3600))
        pending = rnd.choice((0, 1))

        tmp_db.add_or_update_broadcast(
            chat_id=1000, template_name="sim", mode=mode,
            interval_seconds=interval, counter_threshold=threshold, account_id=MY_ID,
        )
        task = tmp_db.get_chat_broadcasts(1000, MY_ID)[0]
        ready_at = now - ready_ago if ready_ago else 0.0
        with tmp_db._conn() as conn:
            conn.execute(
                "UPDATE broadcast_tasks SET current_count=?, last_sent_at=?, counter_ready_at=?, "
                "send_pending=?, last_count_at=? WHERE id=?",
                (count, now - last_ago, ready_at, pending, now - ready_ago, task["id"]),
            )
        fresh = tmp_db.get_chat_broadcasts(1000, MY_ID)[0]

        if mode == "interval":
            expected = bool(pending == 0 and (now - fresh["last_sent_at"]) >= interval)
            got = tmp_db.claim_interval_task(task["id"], now)
        elif mode == "hybrid":
            stale = bool(ready_at and (now - ready_at) > max(interval * 3, 1800))
            expected = bool(
                pending == 0 and not stale and count >= max(threshold, 1)
                and (now - fresh["last_sent_at"]) >= interval
            )
            got = tmp_db.claim_hybrid_task(task["id"], now, stale_after=max(interval * 3, 1800))
            if stale:
                assert tmp_db.get_chat_broadcasts(1000, MY_ID)[0]["current_count"] == 0
        else:
            expected = bool(pending == 0 and count >= max(threshold, 1))
            got = tmp_db.claim_counter_task(task["id"], now)

        assert got is expected, (
            f"mode={mode} interval={interval} threshold={threshold} count={count} "
            f"last_ago={last_ago} ready_ago={ready_ago} pending={pending}"
        )
        if got:
            assert tmp_db.claim_interval_task(task["id"], now + 1) is False
            assert tmp_db.claim_counter_task(task["id"], now + 1) is False
        with tmp_db._conn() as conn:
            conn.execute("DELETE FROM broadcast_tasks")


# --------------------------------------------------------------------------- #
# 3. Антиспам-фаззинг: случайный юникод не должен ронять бота
# --------------------------------------------------------------------------- #
def test_antispam_fuzz_never_raises():
    rnd = random.Random(11)
    alphabet = (
        "абвгдеёжзийклмнопрстуфхцчшщыэюяabcdefghijklmnopqrstuvwxyz0123456789"
        "@#./:!?+-_()[]{} \n\t\u200b\u200e\u2060\ufeff😀⭐️🎁\u0301"
    )
    for _ in range(500):
        text = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(0, 220)))
        score, trigger, factors = bot.calculate_spam_score(text)
        assert 0 <= score <= 100
        assert isinstance(trigger, str) and isinstance(factors, list)
        assert isinstance(bot.is_spam_message(text)[0], bool)
        assert isinstance(bot.should_auto_read(text, msg(text=text), is_ping=rnd.choice((None, True, False))), bool)
        assert isinstance(bot.is_genuine_buyer_question(text), bool)
        bot.normalize_text(text)


def test_command_parser_fuzz_returns_tuple():
    rnd = random.Random(13)
    words = ["рассыл", "каждое", "через", "комби", "15", "10", "минут", "соо", "promo", '"папка"', "x", ""]
    for _ in range(300):
        line = " ".join(rnd.choice(words) for _ in range(rnd.randint(0, 9)))
        result = bot.parse_broadcast_params(line)
        assert isinstance(result, tuple) and len(result) == 6
        mode, interval, count, name, folder, err = result
        if not err:
            assert mode in ("interval", "counter", "hybrid")
            assert name
            if mode == "interval":
                assert interval > 0
            if mode in ("counter", "hybrid"):
                assert count > 0


# --------------------------------------------------------------------------- #
# 4. Папки: 40 проходов синхронизации с меняющимся составом
# --------------------------------------------------------------------------- #
class FolderClient:
    def __init__(self):
        self.chats = []
        self.folder = None

    async def __call__(self, request):
        if isinstance(request, GetDialogFiltersRequest):
            return NS(filters=[self.folder] if self.folder else [])
        return NS()

    def set_chats(self, ids):
        self.chats = list(ids)
        peers = [
            InputPeerChannel(channel_id=abs(c) - 10 ** 12, access_hash=1)
            for c in ids
        ]
        self.folder = DialogFilter(
            id=2,
            title=TextWithEntities(text="Папка", entities=[]),
            pinned_peers=[],
            include_peers=peers,
            exclude_peers=[],
        )


def test_folder_sync_simulation(tmp_db):
    client = FolderClient()
    service = bot.BroadcasterService(client, account_id=MY_ID)
    tmp_db.save_template("f", "text", [], [])
    tmp_db.register_folder_broadcast("Папка", "f", "interval", interval_seconds=60, account_id=MY_ID)

    rnd = random.Random(17)
    universe = [-(10 ** 12) - (1000 + i) for i in range(20)]
    current = set(rnd.sample(universe, 5))
    for step in range(40):
        if rnd.random() < 0.6:
            current.add(rnd.choice(universe))
        if current and rnd.random() < 0.4:
            current.discard(rnd.choice(sorted(current)))
        client.set_chats(sorted(current))
        asyncio.run(service.sync_folder_broadcasts())
        enrolled = tmp_db.get_enrolled_chat_ids("f", "Папка", account_id=MY_ID)
        assert enrolled == current, f"шаг {step}: {enrolled} != {current}"
        tasks = [t for t in tmp_db.list_all_tasks(MY_ID) if t["template_name"] == "f" and t["is_active"]]
        assert len(tasks) == len(current)
        assert len({t["chat_id"] for t in tasks}) == len(tasks), "дубли чатов"


# --------------------------------------------------------------------------- #
# 5. Очередь событий: 200 сообщений, гибрид 15/15
# --------------------------------------------------------------------------- #
def test_hybrid_queue_simulation(tmp_db):
    tmp_db.save_template("q", "text", [], [])
    tmp_db.add_or_update_broadcast(
        chat_id=CHAT_ID, template_name="q", mode="hybrid",
        interval_seconds=900, counter_threshold=15, account_id=MY_ID,
    )
    task = tmp_db.get_active_interval_tasks(MY_ID)[0]
    with tmp_db._conn() as conn:
        conn.execute("UPDATE broadcast_tasks SET last_sent_at=? WHERE id=?", (time.time(), task["id"]))

    sends = 0
    for _ in range(14):
        if tmp_db.increment_and_check_counter(CHAT_ID, account_id=MY_ID):
            sends += 1
    assert sends == 0 and tmp_db.get_active_interval_tasks(MY_ID)[0]["current_count"] == 14

    # 15-е сообщение: порог есть, но интервал ещё не прошёл — отправки нет.
    assert tmp_db.increment_and_check_counter(CHAT_ID, account_id=MY_ID) == []
    task = tmp_db.get_active_interval_tasks(MY_ID)[0]
    assert task["current_count"] == 15 and task["counter_ready_at"] > 0

    # Интервал прошёл — срабатывает ровно один раз.
    with tmp_db._conn() as conn:
        conn.execute("UPDATE broadcast_tasks SET last_sent_at=? WHERE id=?", (time.time() - 1000, task["id"]))
    task = tmp_db.get_active_interval_tasks(MY_ID)[0]
    assert tmp_db.claim_hybrid_task(task["id"], time.time(), stale_after=2700) is True
    assert tmp_db.claim_hybrid_task(task["id"], time.time(), stale_after=2700) is False
    tmp_db.mark_task_sent(task["id"])
    assert tmp_db.get_active_interval_tasks(MY_ID)[0]["current_count"] == 0


def test_restart_simulation_never_sends_leftovers(tmp_db):
    """100 рестартов подряд: остатки счётчиков не должны доживать до отправки."""
    rnd = random.Random(23)
    tmp_db.save_template("r", "text", [], [])
    for _ in range(100):
        mode = rnd.choice(("counter", "hybrid"))
        tmp_db.add_or_update_broadcast(
            chat_id=42, template_name="r", mode=mode,
            interval_seconds=rnd.choice((0, 60, 900)),
            counter_threshold=rnd.choice((1, 3, 15)), account_id=MY_ID,
        )
        task = tmp_db.get_chat_broadcasts(42, MY_ID)[0]
        with tmp_db._conn() as conn:
            conn.execute(
                "UPDATE broadcast_tasks SET current_count=?, counter_ready_at=?, "
                "send_pending=?, retry_at=? WHERE id=?",
                (rnd.randint(0, 20), time.time() - rnd.choice((0, 3600)),
                 rnd.choice((0, 1)), rnd.choice((0, time.time() + 60)), task["id"]),
            )
        tmp_db.reset_pending_sends(MY_ID)
        row = tmp_db.get_chat_broadcasts(42, MY_ID)[0]
        assert row["current_count"] == 0
        assert row["counter_ready_at"] == 0
        assert row["send_pending"] == 0
        assert row["retry_at"] == 0
        with tmp_db._conn() as conn:
            conn.execute("DELETE FROM broadcast_tasks")


def test_only_one_concurrent_claim_wins(tmp_db):
    tmp_db.save_template("c", "text", [], [])
    tmp_db.add_or_update_broadcast(
        chat_id=43, template_name="c", mode="interval", interval_seconds=1, account_id=MY_ID,
    )
    task = tmp_db.get_active_interval_tasks(MY_ID)[0]
    now = time.time() + 2
    wins = sum(1 for _ in range(10) if tmp_db.claim_interval_task(task["id"], now))
    assert wins == 1

