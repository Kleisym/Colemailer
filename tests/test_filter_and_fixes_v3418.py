import asyncio
import importlib
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
BRIDGE_DIR = ROOT / "android" / "app" / "src" / "main" / "python"
if str(BRIDGE_DIR) not in sys.path:
    sys.path.insert(0, str(BRIDGE_DIR))

import bot
import bot_bridge


MAFIA_AD = (
    "MAFIA RESALE 🥊\n"
    "ПРАЙС деньги 💸\n"
    "_______________.\n\n"
    "МАКС 8$ НЕРЕГ МОМЕНТ ОПЛАТА 💸\n"
    "_______________.\n\n"
    "ВОРК ПО ФИЗ НОМЕРАМ по 28$ ☺️ выгодная тема для вас и для меня\n\n"
    "билайн 📞\n"
    "сб-моб 📞\n"
    "мегафон 📞\n"
    "мтс 📞\n"
    "т-мобайл 📞\n"
    "________________\n\n"
    "ПИСАТЬ @MAFIA_VOR_777\n\n"
    "НАС УЖЕ 1300+ 🥳\n\n"
    "МОЯ РЕПУТАЦИЯ В ТИМЕ +rep\n\n"
    "ТИМА У НЕГО В БИО ⚠️🚨\n\n"
    "@MAFIA_VOR_777\n"
    "Отправлено через @glasend"
)

MAFIA_AD_NO_WM = MAFIA_AD.rsplit("\nОтправлено через", 1)[0]


@pytest.mark.parametrize("text", [
    MAFIA_AD,
    MAFIA_AD_NO_WM,
    MAFIA_AD + "\n15:06",
    "BOPK по физ номерам по 28$\nбилайн\nмтс\nПисать @random_user",
    "в о р к по номерам от 25$\nПисать @random_user",
    "ВОРК 28$\nПрием смс / есим / физ\nПисать @random_user",
    "РЕПОСТЫ:\n10 минут — 1 Ⓥ\n30 минут — 1.5 Ⓥ\n1 час — 2.5 Ⓥ\n12 часов — 5 Ⓥ\n24 часа — 8 Ⓥ\nПисать @random_user",
    "Передано через @sendjarv",
    "Отправленно через @glasend",
])
def test_real_world_ads_cleared_without_seller_handle_crutch(text):
    assert bot.should_auto_read(text, NS(entities=[]), is_ping=False), bot.calculate_spam_score(text)
    assert bot.should_auto_read(text, NS(entities=[]), is_ping=True), bot.calculate_spam_score(text)


@pytest.mark.parametrize("text", [
    "Привет, спроси у @seller_shop когда он свободен",
    "Привет, у меня билайн и мтс плохо работают @friendname",
    "сделаешь скидку если возьму 3 поста?",
    "Расписание встречи:\n10 минут — 1 вопрос\n30 минут — 2 вопрос\n1 час — 3 вопрос\n@friendname",
    "Продал телефон за 1000₽, спасибо @buy_bot",
])
def test_ham_not_polluted_by_handle_or_carriers(text):
    assert not bot.should_auto_read(text, NS(entities=[]), is_ping=False), bot.calculate_spam_score(text)
    assert not bot.should_auto_read(text, NS(entities=[]), is_ping=True), bot.calculate_spam_score(text)


def test_java_filter_handles_screenshot_without_watermark_and_obfuscation(tmp_path):
    javac, java = shutil.which("javac"), shutil.which("java")
    if not javac or not java:
        pytest.skip("JDK required")
    source = ROOT / "android/app/src/main/java/com/colemailer/app/AdNotificationFilter.java"
    harness = tmp_path / "V3418FilterTest.java"
    harness.write_text(
        r"""package com.colemailer.app;
public class V3418FilterTest {
    static void check(boolean cond, String msg) {
        if (!cond) throw new AssertionError(msg);
    }
    public static void main(String[] args) {
        String mafiaFull = "MAFIA RESALE \uD83E\uDD4A\nПРАЙС деньги\nМАКС 8$ НЕРЕГ МОМЕНТ ОПЛАТА\n"
            + "ВОРК ПО ФИЗ НОМЕРАМ по 28$\nбилайн\nсб-моб\nмегафон\nмтс\nт-мобайл\n"
            + "ПИСАТЬ @MAFIA_VOR_777\nМОЯ РЕПУТАЦИЯ В ТИМЕ +rep\nТИМА У НЕГО В БИО\nОтправлено через @glasend\n15:06";
        String mafiaNoWm = "ВОРК ПО ФИЗ НОМЕРАМ по 28$\nбилайн\nмтс\nПИСАТЬ @MAFIA_VOR_777";
        String mafiaHomoglyph = "BOPK по физ номерам по 28$\nбилайн\nмтс\nПИСАТЬ @MAFIA_VOR_777";
        String mafiaSpaced = "в о р к по физ номерам 28$\nПисать @MAFIA_VOR_777";
        check(AdNotificationFilter.isAd(mafiaFull), "mafiaFull");
        check(AdNotificationFilter.isAd(mafiaNoWm), "mafiaNoWm");
        check(AdNotificationFilter.isAd(mafiaHomoglyph), "mafiaHomoglyph");
        check(AdNotificationFilter.isAd(mafiaSpaced), "mafiaSpaced");
        check(!AdNotificationFilter.isAd("Привет, у меня билайн и мтс плохо работают @friendname"), "carriers_ham");
        check(!AdNotificationFilter.isAd("Привет, спроси у @seller_shop когда он свободен"), "handle_ham");
        check(AdNotificationFilter.supportsPackage("org.telegram.messenger.beta"), "beta");
        check(AdNotificationFilter.supportsPackage("org.telegram.plus"), "plus");
        check(AdNotificationFilter.supportsPackage("org.thunderdog.challegram"), "tgx");
        check(AdNotificationFilter.supportsPackage("com.radolyn.ayugram"), "ayugram");
        check(AdNotificationFilter.supportsPackage("com.exteragram.messenger"), "exteragram");
        check(!AdNotificationFilter.supportsPackage("fake.telegram.app"), "fake");
    }
}""",
        encoding="utf-8",
    )
    classes = tmp_path / "classes"
    classes.mkdir()
    subprocess.run([javac, "-encoding", "UTF-8", "-d", str(classes), str(source), str(harness)], check=True, capture_output=True, text=True)
    subprocess.run([java, "-cp", str(classes), "com.colemailer.app.V3418FilterTest"], check=True, capture_output=True, text=True)


def test_muted_peers_unique_index_is_four_column(tmp_path):
    db = bot.Database(tmp_path / "test.db")
    with sqlite3.connect(db.db_path) as conn:
        cols = [r[2] for r in conn.execute("PRAGMA index_info('idx_muted_peers_unique')").fetchall()]
    assert cols == ["account_id", "peer_key", "scope", "chat_id"]
    db.add_muted_peer(555, account_id=1, scope="user", chat_id=0)
    db.add_muted_peer(555, account_id=1, scope="user", chat_id=-100123)
    assert len(db.list_muted_peers(account_id=1)) == 2


def test_claim_retry_sets_send_pending_to_block_concurrent_counter_send(tmp_path):
    db = bot.Database(tmp_path / "retry.db")
    db.add_or_update_broadcast(chat_id=1001, template_name="tpl", mode="counter", counter_threshold=1, account_id=7)
    tasks = db.list_all_tasks(account_id=7)
    tid = tasks[0]["id"]
    now = time.time()
    db.schedule_retry(tasks[0], delay=-1.0, failed=True)
    # Manually backdate retry_at so it's due now
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("UPDATE broadcast_tasks SET retry_at = ? WHERE id = ?", (now - 1, tid))
    assert db.claim_retry(tid, now) is True
    with sqlite3.connect(db.db_path) as conn:
        pending = conn.execute("SELECT send_pending FROM broadcast_tasks WHERE id = ?", (tid,)).fetchone()[0]
    assert pending == 1
    assert db.increment_and_check_counter(1001, account_id=7) == []


def test_rotation_preview_does_not_advance_index(tmp_path):
    db = bot.Database(tmp_path / "rot.db")
    db.save_template("t1", "one", [], [])
    db.save_template("t2", "two", [], [])
    db.set_named_rotation("rotA", ["t1", "t2"], account_id=9)
    assert db.get_next_rotation_template(account_id=9, rotation_name="rotA", advance=False) == "t1"
    assert db.get_next_rotation_template(account_id=9, rotation_name="rotA", advance=False) == "t1"
    assert db.get_next_rotation_template(account_id=9, rotation_name="rotA", advance=True) == "t1"
    assert db.get_next_rotation_template(account_id=9, rotation_name="rotA", advance=False) == "t2"
    # Per-chat progress with chat_id set also respects advance=False
    assert db.get_next_rotation_template(chat_id=1234, account_id=9, rotation_name="rotA", advance=False) == "t1"
    assert db.get_next_rotation_template(chat_id=1234, account_id=9, rotation_name="rotA", advance=False) == "t1"
    assert db.get_next_rotation_template(chat_id=1234, account_id=9, rotation_name="rotA", advance=True) == "t1"
    assert db.get_next_rotation_template(chat_id=1234, account_id=9, rotation_name="rotA", advance=False) == "t2"


def test_parse_broadcast_params_strips_quotes_consistently():
    mode, iv, cnt, tpl, folder, err = bot.parse_broadcast_params(".рассылка каждое 1ч 'Шаблон1' \"Моя папка\"")
    assert err == ""
    assert mode == "interval"
    assert iv == 3600
    assert tpl == "Шаблон1"
    assert folder == "Моя папка"

    mode, iv, cnt, tpl, folder, err = bot.parse_broadcast_params(".рассылка через 10 <Шаблон2>")
    assert err == ""
    assert mode == "counter"
    assert cnt == 10
    assert tpl == "Шаблон2"


def test_bridge_session_isolation_due_calculation_and_tasks_json(tmp_path, monkeypatch):
    # Legacy session migrates only once to the first account; second account gets isolated session.
    (tmp_path / "colemailer_session.session").write_bytes(b"sqlite-legacy")
    s1 = bot_bridge._session_name(str(tmp_path), "acct-one", "+79990001111")
    s2 = bot_bridge._session_name(str(tmp_path), "acct-two", "+79990002222")
    assert s1 != s2
    assert (tmp_path / f"{s1}.session").exists()
    assert not (tmp_path / "colemailer_session.session").exists()
    assert not (tmp_path / f"{s2}.session").exists()

    # Save global paths touched by init_app_storage via monkeypatch so later tests remain isolated.
    for attr in ("BASE_DIR", "STORAGE_DIR", "MEDIA_DIR", "DB_PATH", "CONFIG_PATH", "CONFIG", "db"):
        monkeypatch.setattr(bot, attr, getattr(bot, attr, None))
    monkeypatch.setattr(bot_bridge, "_storage_ready", False)
    monkeypatch.setattr(bot_bridge, "_broadcaster", None)

    bot.db = None
    app_dir = tmp_path / "app_data"
    app_dir.mkdir()
    raw_empty = json.loads(bot_bridge.get_tasks_json(str(app_dir)))
    assert raw_empty["ready"] is True

    db = bot.db
    db.save_template("promo", "hello world", [], [])
    now = time.time()
    db.add_or_update_broadcast(chat_id=101, template_name="promo", mode="interval", interval_seconds=600, account_id=11)
    db.add_or_update_broadcast(chat_id=102, template_name="promo", mode="counter", counter_threshold=5, account_id=11)
    with sqlite3.connect(db.db_path) as conn:
        conn.execute("UPDATE broadcast_tasks SET last_sent_at = ?, current_count = 3 WHERE chat_id IN (101, 102)", (now,))

    broadcaster = NS(account_id=11)
    bot_bridge._broadcaster = broadcaster
    due_ms = bot_bridge._compute_next_due(broadcaster)
    assert due_ms is not None
    assert abs(due_ms - int((now + 600) * 1000)) < 5000

    payload = json.loads(bot_bridge.get_tasks_json(str(app_dir)))
    assert payload["ready"] is True
    assert len(payload["templates"]) == 1
    by_chat = {t["chat_id"]: t for t in payload["tasks"]}
    assert set(by_chat) == {101, 102}
    assert by_chat[101]["next_at"] > now
    assert by_chat[102]["count"] == 3
    assert by_chat[102]["threshold"] == 5

    cfg = bot_bridge._account_cfg("@tester")
    assert "auto_sub_only_broadcast_chats" in cfg
