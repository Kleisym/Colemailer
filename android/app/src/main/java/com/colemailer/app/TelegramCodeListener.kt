package com.colemailer.app

import android.app.Notification
import android.content.Context
import android.content.Intent
import android.os.Build
import android.provider.Settings
import android.service.notification.NotificationListenerService
import android.service.notification.StatusBarNotification
import androidx.core.app.NotificationManagerCompat
import androidx.core.app.NotificationCompat
import java.util.concurrent.TimeUnit

/**
 * Локальный фильтр опубликованных уведомлений и ввод кода my.telegram.org.
 * Отмена уведомления не гарантирует отмену уже начавшегося звука.
 */
class TelegramCodeListener : NotificationListenerService() {

    override fun onNotificationPosted(sbn: StatusBarNotification?) {
        val notification = sbn?.notification ?: return
        if (removeAdNotification(sbn, notification)) return
        if (!AdNotificationFilter.supportsPackage(sbn.packageName) &&
            !sbn.packageName.lowercase().contains("telegram")) return
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

    private fun removeAdNotification(sbn: StatusBarNotification, notification: Notification): Boolean {
        // Telegram reports private conversations as groups on Android < 9.
        // A missing preview or unsupported format must never hide a real message.
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.P || !Prefs.filterAdNotifications ||
            !AdNotificationFilter.supportsPackage(sbn.packageName)) return false
        return try {
            val style = NotificationCompat.MessagingStyle.extractMessagingStyleFromNotification(notification)
                ?: return false
            if (style.messages.size > 25) return false
            val texts = style.messages.map { it.text?.toString() }.toTypedArray()
            if (!AdNotificationFilter.shouldDismiss(
                    sbn.packageName, true,
                    notification.flags and Notification.FLAG_GROUP_SUMMARY != 0,
                    notification.flags and Notification.FLAG_ONGOING_EVENT != 0,
                    style.isGroupConversation, texts)) return false
            cancelNotification(sbn.key)
            true
        } catch (_: Exception) {
            false
        }
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
