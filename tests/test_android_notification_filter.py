import shutil
import subprocess
from pathlib import Path

import pytest


def test_notification_filter_policy(tmp_path):
    javac, java = shutil.which('javac'), shutil.which('java')
    if not javac or not java:
        pytest.skip('JDK required')
    source = Path(__file__).resolve().parents[1] / 'android/app/src/main/java/com/colemailer/app/AdNotificationFilter.java'
    harness = tmp_path / 'FilterTest.java'
    harness.write_text(r'''package com.colemailer.app;
public class FilterTest {
    static int checks = 0;
    static void check(boolean condition) {
        checks++;
        if (!condition) throw new AssertionError("check " + checks);
    }
    static boolean dismiss(String... texts) {
        return AdNotificationFilter.shouldDismiss("org.telegram.messenger", true, false, false, true, texts);
    }
    public static void main(String[] args) {
        String catalogue = "ПРАЙС деньги\nМАКС 8$ НЕРЕГ МОМЕНТ ОПЛАТА\nВОРК ПО ФИЗ НОМЕРАМ по 28$\n"
            + "билайн\nмтс\nПИСАТЬ @seller_shop\nМОЯ РЕПУТАЦИЯ В ТИМЕ +rep\nОтправлено через @jaruvu";
        String seller = "ИЩУ ВЗЛОТЫ/ОП\n1 0 . 5 0\n@seller_shop\n"
            + "так же продаю привод кому интересно в лс\nпрайс + отзывы @review_shop\nПередано через @sendjarv";
        String[] ads = {catalogue, seller, "Продам аккаунты по 100₽, пишите @seller_shop"};
        for (String ad : ads) { check(AdNotificationFilter.isAd(ad)); check(dismiss(ad)); }
        String[] normal = {"Привет, ответь", "почем реклама?", "скинь прайс пожалуйста",
            "@seller_shop", "Пришли прайс @shopname", "Куплю у тебя рекламу, есть место?",
            "Привет, вот @friendname", "Login code: 12345", "", "Ваш код подтверждения 12345",
            "Продал телефон за 1000₽, спасибо @friendname", "Избранное: уведомления скрыты"};
        for (String text : normal) { check(!AdNotificationFilter.isAd(text)); check(!dismiss(text)); }
        check(dismiss(catalogue, seller));
        check(!dismiss(catalogue, "Привет, ответь"));
        check(!dismiss("Привет, ответь", catalogue));
        check(!dismiss(catalogue, null));
        check(!dismiss(new String[0]));
        check(!dismiss((String[]) null));
        check(!dismiss("a".repeat(8193) + catalogue));
        check(!AdNotificationFilter.shouldDismiss("fake.telegram.app", true, false, false, true, ads));
        check(!AdNotificationFilter.shouldDismiss("org.telegram.messenger", false, false, false, true, ads));
        check(!AdNotificationFilter.shouldDismiss("org.telegram.messenger", true, true, false, true, ads));
        check(!AdNotificationFilter.shouldDismiss("org.telegram.messenger", true, false, true, true, ads));
        check(!AdNotificationFilter.shouldDismiss("org.telegram.messenger", true, false, false, false, ads));
        check(AdNotificationFilter.shouldDismiss("org.telegram.messenger.web", true, false, false, true, ads));
        String[] many = new String[26]; java.util.Arrays.fill(many, catalogue); check(!dismiss(many));
        check(!AdNotificationFilter.isAd("отправлено через @sender"));
        System.out.println("notification policy checks=" + checks);
    }
}''', encoding='utf-8')
    classes = tmp_path / 'classes'
    classes.mkdir()
    subprocess.run([javac, '-encoding', 'UTF-8', '-d', str(classes), str(source), str(harness)],
                   check=True, capture_output=True, text=True)
    result = subprocess.run([java, '-cp', str(classes), 'com.colemailer.app.FilterTest'],
                            check=True, capture_output=True, text=True)
    assert 'notification policy checks=' in result.stdout
    print(result.stdout.strip())
