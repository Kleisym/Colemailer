package com.colemailer.app

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import com.colemailer.app.ui.AuthActivity
import com.colemailer.app.ui.MainActivity

/**
 * Все уведомления приложения.
 *
 * Канал создаётся один раз и до первого startForeground: иначе на Android 8+
 * сервис падает с «channel does not exist». Уведомление обновляется только при
 * смене состояния — никаких notify() раз в минуту.
 */
object Notifications {
    const val CHANNEL_SERVICE = "colemailer_service"
    const val CHANNEL_ALERTS = "colemailer_alerts"

    const val ID_FOREGROUND = 1001
    const val ID_AUTH = 1002
    const val ID_UPDATE = 1003
    const val ID_AUTH_WAIT = 1004

    fun ensureChannels(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_SERVICE,
                context.getString(R.string.channel_service_name),
                NotificationManager.IMPORTANCE_LOW
            ).apply {
                description = context.getString(R.string.channel_service_desc)
                setShowBadge(false)
            }
        )
        manager.createNotificationChannel(
            NotificationChannel(
                CHANNEL_ALERTS,
                context.getString(R.string.channel_alerts_name),
                NotificationManager.IMPORTANCE_HIGH
            ).apply {
                description = context.getString(R.string.channel_alerts_desc)
            }
        )
    }

    fun granted(context: Context): Boolean =
        Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
            NotificationManagerCompat.from(context).areNotificationsEnabled()

    fun requestIntent(context: Context): Intent =
        Intent(android.provider.Settings.ACTION_APP_NOTIFICATION_SETTINGS)
            .putExtra(android.provider.Settings.EXTRA_APP_PACKAGE, context.packageName)

    fun foreground(context: Context, state: ServiceState): Notification {
        val builder = NotificationCompat.Builder(context, CHANNEL_SERVICE)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(context.getString(R.string.notif_service_title))
            .setContentText(state.text)
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setShowWhen(false)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setContentIntent(openApp(context))
            .addAction(0, context.getString(R.string.notif_stop), stopService(context))
        // Android 12+: без этого уведомление может появиться с задержкой до 10 с.
        builder.setForegroundServiceBehavior(NotificationCompat.FOREGROUND_SERVICE_IMMEDIATE)
        return builder.build()
    }

    /** Показать уведомление, обновив уже выложенное (без новых звуков). */
    fun update(context: Context, state: ServiceState) {
        if (!granted(context)) return
        runCatching {
            NotificationManagerCompat.from(context)
                .notify(ID_FOREGROUND, foreground(context, state))
        }
    }

    /** Доступно обновление: тап открывает приложение (Настройки → Обновление). */
    fun updateAvailable(context: Context, version: String) {
        if (!granted(context)) return
        val notification = NotificationCompat.Builder(context, CHANNEL_ALERTS)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(context.getString(R.string.update_available, version))
            .setContentText(context.getString(R.string.update_notification_text))
            .setPriority(NotificationCompat.PRIORITY_DEFAULT)
            .setAutoCancel(true)
            .setContentIntent(openApp(context))
            .build()
        runCatching {
            NotificationManagerCompat.from(context).notify(ID_UPDATE, notification)
        }
    }

    /** Запрос кода Telegram или пароля 2FA: тап открывает [AuthActivity]. */
    fun authRequest(context: Context, kind: AuthQueue.Kind, title: String, hint: String) {
        if (!granted(context)) return
        val mode = if (kind == AuthQueue.Kind.CODE) AuthActivity.MODE_CODE else AuthActivity.MODE_PASSWORD
        val open = PendingIntent.getActivity(
            context,
            10 + kind.ordinal,
            Intent(context, AuthActivity::class.java)
                .putExtra(AuthActivity.EXTRA_MODE, mode)
                .putExtra(AuthActivity.EXTRA_TITLE, title)
                .putExtra(AuthActivity.EXTRA_HINT, hint)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP),
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val notification = NotificationCompat.Builder(context, CHANNEL_ALERTS)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(title)
            .setContentText(hint)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setAutoCancel(true)
            .setContentIntent(open)
            .build()
        runCatching {
            NotificationManagerCompat.from(context).notify(ID_AUTH, notification)
        }
    }

    fun cancelAuth(context: Context) {
        runCatching { NotificationManagerCompat.from(context).cancel(ID_AUTH) }
    }

    /** Постоянное уведомление на время ожидания кода: процесс не умирает. */
    fun authWait(context: Context): Notification {
        val intent = Intent(context, AuthActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        val pending = PendingIntent.getActivity(
            context,
            20,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        return NotificationCompat.Builder(context, CHANNEL_SERVICE)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(context.getString(R.string.auth_wait_title))
            .setContentText(context.getString(R.string.auth_wait_text))
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setShowWhen(false)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .setContentIntent(pending)
            .build()
    }

    private fun openApp(context: Context): PendingIntent {
        val intent = Intent(context, MainActivity::class.java)
            .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
        return PendingIntent.getActivity(
            context,
            0,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
    }

    private fun stopService(context: Context): PendingIntent {
        val intent = Intent(context, BotService::class.java).setAction(BotService.ACTION_STOP)
        return PendingIntent.getService(
            context,
            1,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
    }
}
