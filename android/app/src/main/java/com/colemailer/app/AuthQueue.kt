package com.colemailer.app

import android.content.Context
import android.content.Intent
import android.os.Handler
import android.os.Looper
import com.colemailer.app.ui.AuthActivity
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit

/**
 * Очередь запросов «введите код / пароль 2FA».
 *
 * Раньше ожидание висело на listener'е Activity, который обнулялся в onPause:
 * если код пришёл при погашенном экране, диалог не появлялся и логин падал.
 * Теперь запрос живёт в сервисе (этот объект), а UI лишь показывает его и
 * возвращает ответ. Activity можно закрыть — запрос останется.
 */
object AuthQueue {
    enum class Kind { CODE, PASSWORD }

    class Request internal constructor(
        val kind: Kind,
        val title: String,
        val hint: String
    ) {
        internal val latch = CountDownLatch(1)

        @Volatile
        internal var value: String = ""

        @Volatile
        internal var answered: Boolean = false
    }

    private val queue = ArrayDeque<Request>()
    private val lock = Any()

    /**
     * Показать запрос и подождать ответ. Вызывается из Python-потока
     * (BotCallback.requestCode), поэтому блокировать UI не может.
     */
    fun request(kind: Kind, title: String, hint: String, timeoutMs: Long = TIMEOUT_MS): String {
        val request = Request(kind, title, hint)
        synchronized(lock) { queue.addLast(request) }

        val context = App.context
        StatusStore.setPhase(phaseOf(kind), title, running = true)
        Notifications.authRequest(context, kind, title, hint)
        openAuthScreen(context, kind, title, hint)

        val received = try {
            request.latch.await(timeoutMs, TimeUnit.MILLISECONDS)
        } catch (e: InterruptedException) {
            Thread.currentThread().interrupt()
            false
        }

        synchronized(lock) { queue.remove(request) }
        Notifications.cancelAuth(context)

        return if (received && request.answered) {
            request.value
        } else {
            StatusStore.set(
                context.getString(R.string.state_input_cancelled),
                false,
                Level.WARN
            )
            ""
        }
    }

    /**
     * Показать экран ввода поверх текущего. Из фона Android может запретить
     * запуск Activity — тогда остаётся уведомление, но в открытом приложении
     * диалог появляется сразу, а не «через три минуты таймаута».
     */
    private fun openAuthScreen(context: Context, kind: Kind, title: String, hint: String) {
        val mode = if (kind == Kind.CODE) AuthActivity.MODE_CODE else AuthActivity.MODE_PASSWORD
        val intent = Intent(context, AuthActivity::class.java)
            .putExtra(AuthActivity.EXTRA_MODE, mode)
            .putExtra(AuthActivity.EXTRA_TITLE, title)
            .putExtra(AuthActivity.EXTRA_HINT, hint)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP or Intent.FLAG_ACTIVITY_SINGLE_TOP)
        Handler(Looper.getMainLooper()).post {
            runCatching { context.startActivity(intent) }
        }
    }

    /** Ответ из [com.colemailer.app.ui.AuthActivity]. true — запрос был. */
    fun submit(kind: Kind, value: String): Boolean {
        val request = synchronized(lock) { queue.firstOrNull { it.kind == kind } } ?: return false
        request.value = value.trim()
        request.answered = true
        request.latch.countDown()
        return true
    }

    fun cancel(kind: Kind) {
        val request = synchronized(lock) { queue.firstOrNull { it.kind == kind } } ?: return
        request.answered = false
        request.latch.countDown()
    }

    fun cancelAll() {
        val pending = synchronized(lock) {
            val copy = queue.toList()
            queue.clear()
            copy
        }
        pending.forEach {
            it.answered = false
            it.latch.countDown()
        }
    }

    fun pendingKind(): Kind? = synchronized(lock) { queue.firstOrNull()?.kind }

    fun hasPending(): Boolean = pendingKind() != null

    private fun phaseOf(kind: Kind): Phase =
        if (kind == Kind.CODE) Phase.CODE_REQUIRED else Phase.PASSWORD_REQUIRED

    // Ввод кода/пароля — это не «5 минут молчания»: дольше двух минут
    // пользователь всё равно не вернётся, а бот простаивает.
    private const val TIMEOUT_MS = 180_000L
}
