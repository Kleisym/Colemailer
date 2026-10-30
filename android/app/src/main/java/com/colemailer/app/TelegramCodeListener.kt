package com.colemailer.app

import android.app.Notification
import android.content.Context
import android.content.Intent
import android.provider.Settings
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import androidx.core.app.NotificationManagerCompat
import java.util.concurrent.TimeUnit

/**
 * Читает код входа из уведомления Telegram и сразу отдаёт его в AuthQueue.
 *
 * Это не «доступ к чужим уведомлениям»: пользователь один раз включает
 * «Доступ к уведомлениям» для Colemailer, а сервис реагирует только когда
 * приложение само ждёт код my.telegram.org и только на пакеты Telegram.
 */
class TelegramCodeListener : NotificationListenerService() {

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        val notification = sbn?.notification ?: return
        if (!sbn.packageName.lowercase().contains("telegram")) return
        if (!AuthQueue.hasPending(AuthQueue.Kind.CODE)) return
        val age = System.currentTimeMillis() - notification.`when`
        if (age > TimeUnit.MINUTES.toMillis(5)) return

        val extras = notification.extras ?: return
        val parts = listOf(
            extras.getCharSequence(Notification.EXTRA_TITLE),
            extras.getCharSequence(Notification.EXTRA_TEXT),
            extras.getCharSequence(Notification.EXTRA_BIG_TEXT),
            extras.getCharSequence(Notification.EXTRA_SUB_TEXT)
        ).filterNotNull().joinToString(" ")
        val code = extractCode(parts) ?: return
        AuthQueue.submit(AuthQueue.Kind.CODE, code)
    }

    private fun extractCode(text: String): String? {
        val patterns = listOf(
            Regex("(?i)(?:login\\s*code|confirmation\\s*code|код\\s*(?:входа|подтверждения)?)[^A-Za-zА-Яа-я0-9]{0,20}([A-Z0-9]{5,8})"),
            Regex("(?i)(?:code|код)[^A-Za-zА-Яа-я0-9]{0,10}([0-9]{5,7})")
        )
        for (pattern in patterns) {
            val match = pattern.find(text) ?: continue
            return match.groupValues[1]
        }
        return null
    }

    companion object {
        fun isEnabled(context: Context): Boolean = try {
            NotificationManagerCompat.getEnabledListenerPackages(context).contains(context.packageName)
        } catch (e: Exception) {
            false
        }

        fun requestIntent(): Intent = Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)
    }
}
