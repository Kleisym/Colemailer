package com.colemailer.app

/**
 * Колбэк для Chaquopy: Python зовёт эти методы по имени.
 *
 * Требования Chaquopy: класс public, методы public, без лямбд/anonymous object.
 * Объект живёт дольше Activity, поэтому ничего не хранит, кроме ссылки на
 * глобальные StatusStore/LogStore/очередь ввода.
 */
class BotCallback {

    fun requestCode(): String {
        val context = App.contextOrNull()
        val title = context?.getString(R.string.auth_title_code) ?: "Код из Telegram"
        val hint = context?.getString(R.string.auth_hint_code) ?: "Код подтверждения"
        return AuthQueue.request(AuthQueue.Kind.CODE, title, hint)
    }

    fun requestPassword(): String {
        val context = App.contextOrNull()
        val title = context?.getString(R.string.auth_title_password) ?: "Пароль 2FA"
        val hint = context?.getString(R.string.auth_hint_password) ?: "Облачный пароль"
        return AuthQueue.request(AuthQueue.Kind.PASSWORD, title, hint)
    }

    fun onStatusChange(status: String, running: Boolean) {
        StatusStore.set(status, running)
        App.contextOrNull()?.let { Notifications.update(it, StatusStore.current()) }
    }

    fun onLoggedIn(username: String, userId: Long) {
        Prefs.user = username
        StatusStore.markRunning("Работает ($username)")
        App.contextOrNull()?.let { Notifications.update(it, StatusStore.current()) }
    }

    fun onError(error: String) {
        StatusStore.set("Ошибка: $error", false, Level.ERROR)
        App.contextOrNull()?.let { Notifications.update(it, StatusStore.current()) }
    }

    /** Python сообщил точное время ближайшей задачи — ставим alarm. */
    fun onNextDue(epochMs: Long) {
        if (epochMs <= 0) return
        val context = App.contextOrNull() ?: return
        WakeScheduler.scheduleAt(context, epochMs)
    }

    fun onLog(line: String) {
        LogStore.append(line)
    }
}
