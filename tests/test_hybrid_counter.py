# -*- coding: utf-8 -*-
"""Гибридная рассылка: порог сообщений И пауза, без догоняющих отправок.

Hybrid — самый хрупкий режим: пост должен уйти, когда в чате набралось N
живых сообщений и при этом прошёл интервал. Ошибки здесь выглядят как «пост
прилетел через сутки после 14 старых сообщений» или «один пост ушёл дважды».
Тесты проверяют три вещи:

  * окно счётчика (`counter_ready_at`) протухает и сбрасывается, а не копится;
  * рестарт процесса (`reset_pending_sends`) обнуляет остаток счётчика;
  * claim атомарный: второй вызов не отправляет пост повторно.
"""
import time

from tests.support import hybrid_task_row

CHAT = 555
ACCOUNT = 1
THRESHOLD = 15
INTERVAL = 900
STALE_AFTER = max(INTERVAL * 3, 1800)


def feed(db, count, *, account=ACCOUNT):
    """Скормить чату `count` сообщений и вернуть все сработавшие задачи."""
    fired = []
    for _ in range(count):
        fired.extend(db.increment_and_check_counter(CHAT, account_id=account))
    return fired


def current_task(db):
    return db.get_active_interval_tasks(account_id=ACCOUNT)[0]


# --------------------------------------------------------------------------- #
# порог и пауза
# --------------------------------------------------------------------------- #
def test_fifteen_messages_inside_the_interval_do_not_send(tmp_db):
    hybrid_task_row(tmp_db, count=0, last_sent_ago=10, threshold=THRESHOLD,
                    interval=INTERVAL, ready_ago=None)

    assert feed(tmp_db, THRESHOLD) == []

    task = current_task(tmp_db)
    assert task["current_count"] == THRESHOLD
    assert task["counter_ready_at"] > 0, "окно счётчика должно быть помечено"


def test_message_after_the_interval_sends(tmp_db):
    hybrid_task_row(tmp_db, count=THRESHOLD - 1, last_sent_ago=INTERVAL + 100,
                    threshold=THRESHOLD, interval=INTERVAL, ready_ago=None)

    fired = feed(tmp_db, 1)

    assert len(fired) == 1
    assert fired[0]["template_name"] == "h"
    assert fired[0]["chat_id"] == CHAT


def test_nothing_is_sent_below_the_threshold_even_after_the_interval(tmp_db):
    hybrid_task_row(tmp_db, count=3, last_sent_ago=INTERVAL * 10,
                    threshold=THRESHOLD, interval=INTERVAL, ready_ago=None)
    assert feed(tmp_db, 5) == []
    assert current_task(tmp_db)["current_count"] == 8


# --------------------------------------------------------------------------- #
# протухшее окно
# --------------------------------------------------------------------------- #
def test_stale_window_is_reset_and_does_not_fire(tmp_db):
    """4 часа тишины: 15 сообщений были «когда-то», а не «перед постом»."""
    hybrid_task_row(tmp_db, count=THRESHOLD, last_sent_ago=4 * 3600,
                    threshold=THRESHOLD, interval=INTERVAL, ready_ago=4 * 3600)

    assert feed(tmp_db, 1) == []

    task = current_task(tmp_db)
    assert task["current_count"] <= 1, "старый счётчик должен обнулиться"
    assert task["counter_ready_at"] == 0


def test_claim_refuses_a_stale_window_and_clears_it(tmp_db):
    task = hybrid_task_row(tmp_db, count=THRESHOLD, last_sent_ago=INTERVAL + 100,
                           threshold=THRESHOLD, interval=INTERVAL,
                           ready_ago=4 * 3600)

    claimed = tmp_db.claim_hybrid_task(task["id"], time.time(), stale_after=STALE_AFTER)

    assert claimed is False
    row = current_task(tmp_db)
    assert row["current_count"] == 0
    assert row["counter_ready_at"] == 0
    assert row["send_pending"] == 0


def test_fresh_window_is_claimable(tmp_db):
    task = hybrid_task_row(tmp_db, count=THRESHOLD, last_sent_ago=INTERVAL + 100,
                           threshold=THRESHOLD, interval=INTERVAL, ready_ago=60)
    assert tmp_db.claim_hybrid_task(task["id"], time.time(), stale_after=STALE_AFTER) is True


# --------------------------------------------------------------------------- #
# рестарт
# --------------------------------------------------------------------------- #
def test_restart_resets_the_leftover_counter(tmp_db):
    """После рестарта остаток счётчика не добивает порог одним сообщением."""
    hybrid_task_row(tmp_db, count=THRESHOLD - 1, last_sent_ago=24 * 3600,
                    threshold=THRESHOLD, interval=INTERVAL, ready_ago=None)
    tmp_db.reset_pending_sends(account_id=ACCOUNT)

    assert feed(tmp_db, 1) == []
    assert current_task(tmp_db)["current_count"] == 1


def test_restart_rearms_overdue_interval_tasks(tmp_db):
    """Просроченная interval-задача после простоя ждёт интервал, а не стреляет сразу."""
    tmp_db.save_template("i", "text", [], [])
    tmp_db.add_or_update_broadcast(chat_id=CHAT, template_name="i", mode="interval",
                                   interval_seconds=INTERVAL, account_id=ACCOUNT)
    task = current_task(tmp_db)
    with tmp_db._conn() as conn:
        conn.execute("UPDATE broadcast_tasks SET last_sent_at = ? WHERE id = ?",
                     (time.time() - 24 * 3600, task["id"]))

    tmp_db.reset_pending_sends(account_id=ACCOUNT)

    row = current_task(tmp_db)
    assert time.time() - row["last_sent_at"] < INTERVAL, "таймер должен быть перевооружён"
    assert tmp_db.claim_interval_task(task["id"], time.time()) is False


# --------------------------------------------------------------------------- #
# атомарный claim
# --------------------------------------------------------------------------- #
def test_second_claim_does_not_send_twice(tmp_db):
    task = hybrid_task_row(tmp_db, count=THRESHOLD, last_sent_ago=INTERVAL + 100,
                           threshold=THRESHOLD, interval=INTERVAL, ready_ago=60)
    now = time.time()

    assert tmp_db.claim_hybrid_task(task["id"], now, stale_after=STALE_AFTER) is True
    assert tmp_db.claim_hybrid_task(task["id"], now, stale_after=STALE_AFTER) is False

    row = current_task(tmp_db)
    assert row["send_pending"] == 1


def test_pending_send_blocks_new_ready_reports(tmp_db):
    """Пока идёт отправка, новые сообщения не отдают задачу второй раз."""
    task = hybrid_task_row(tmp_db, count=THRESHOLD, last_sent_ago=INTERVAL + 100,
                           threshold=THRESHOLD, interval=INTERVAL, ready_ago=60)
    tmp_db.claim_hybrid_task(task["id"], time.time(), stale_after=STALE_AFTER)

    assert feed(tmp_db, 3) == []
    assert current_task(tmp_db)["send_pending"] == 1


def test_successful_send_resets_counter_and_window(tmp_db):
    task = hybrid_task_row(tmp_db, count=THRESHOLD, last_sent_ago=INTERVAL + 100,
                           threshold=THRESHOLD, interval=INTERVAL, ready_ago=60)
    tmp_db.mark_task_sent(task["id"])

    row = current_task(tmp_db)
    assert row["current_count"] == 0
    assert row["counter_ready_at"] == 0
    assert row["send_pending"] == 0


# --------------------------------------------------------------------------- #
# ретраи
# --------------------------------------------------------------------------- #
def test_hybrid_retry_keeps_the_decision_without_inflating_the_counter(tmp_db):
    """schedule_retry не «подделывает» счётчик.

    Решение отправить уже принято, поэтому окно остаётся свежим и повтор
    сработает без новых сообщений. Но счётчик не растёт сверх порога и задача
    не отправляется раньше задержки.
    """
    task = hybrid_task_row(tmp_db, count=THRESHOLD, last_sent_ago=INTERVAL + 100,
                           threshold=THRESHOLD, interval=INTERVAL, ready_ago=60)
    tmp_db.claim_hybrid_task(task["id"], time.time(), stale_after=STALE_AFTER)

    tmp_db.schedule_retry(task, delay=60, failed=True)

    row = current_task(tmp_db)
    assert row["send_pending"] == 0
    assert row["current_count"] == THRESHOLD, "счётчик не должен вырасти"
    assert row["fail_count"] == 1
    # До задержки пауза ещё не прошла.
    assert tmp_db.claim_hybrid_task(row["id"], time.time(), stale_after=STALE_AFTER) is False
    # После задержки повтор проходит без единого нового сообщения.
    assert tmp_db.claim_hybrid_task(row["id"], time.time() + 61,
                                    stale_after=STALE_AFTER) is True


def test_repeated_retries_do_not_grow_the_counter(tmp_db):
    task = hybrid_task_row(tmp_db, count=THRESHOLD, last_sent_ago=INTERVAL + 100,
                           threshold=THRESHOLD, interval=INTERVAL, ready_ago=60)
    tmp_db.claim_hybrid_task(task["id"], time.time(), stale_after=STALE_AFTER)

    for _ in range(3):
        tmp_db.schedule_retry(task, delay=30, failed=True)

    row = current_task(tmp_db)
    assert row["current_count"] == THRESHOLD
    assert row["fail_count"] == 3


def test_counter_mode_retry_does_not_fake_the_counter(tmp_db):
    """У обычного counter-режима ретрай вообще не трогает счётчик."""
    tmp_db.save_template("c", "text", [], [])
    tmp_db.add_or_update_broadcast(chat_id=CHAT, template_name="c", mode="counter",
                                   counter_threshold=5, account_id=ACCOUNT)
    task = tmp_db.get_chat_broadcasts(CHAT, account_id=ACCOUNT)[0]
    with tmp_db._conn() as conn:
        conn.execute("UPDATE broadcast_tasks SET current_count = 4 WHERE id = ?", (task["id"],))
    task = tmp_db.get_chat_broadcasts(CHAT, account_id=ACCOUNT)[0]

    tmp_db.schedule_retry(task, delay=30, failed=True)

    row = tmp_db.get_chat_broadcasts(CHAT, account_id=ACCOUNT)[0]
    assert row["current_count"] == 4, "ретрай не должен добивать счётчик"
    assert row["retry_at"] > 0
    assert row["send_pending"] == 0
