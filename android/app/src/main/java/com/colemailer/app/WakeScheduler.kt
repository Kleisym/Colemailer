package com.colemailer.app

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.os.Build
import android.os.SystemClock

/**
 * Будильники сервиса.
 *
 * Раньше «пинок» раз в 10 минут шёл через setAndAllowWhileIdle — неточный
 * alarm, который не входит в список исключений Android 12 для фонового старта
 * FGS. Теперь будильник один и точный: либо на время ближайшей задачи из
 * Python, либо на отложенный рестарт. Страховка — WorkManager.
 */
object WakeScheduler {
    private const val REQ_RESTART = 4201
    private const val REQ_DUE = 4202

    fun canExact(context: Context): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return true
        val manager = context.getSystemService(Context.ALARM_SERVICE) as? AlarmManager ?: return false
        return runCatching { manager.canScheduleExactAlarms() }.getOrDefault(false)
    }

    /** Разбудить сервис к конкретной задаче рассылки (epoch ms). */
    fun scheduleAt(context: Context, atEpochMs: Long) {
        val manager = context.getSystemService(Context.ALARM_SERVICE) as? AlarmManager ?: return
        val at = atEpochMs.coerceAtLeast(System.currentTimeMillis() + 5_000L)
        val pending = pending(context, REQ_DUE, WakeReceiver.ACTION_DUE)
        try {
            if (canExact(context)) {
                manager.setExactAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pending)
            } else {
                manager.setAndAllowWhileIdle(AlarmManager.RTC_WAKEUP, at, pending)
                WorkScheduler.enqueueDue(context, at)
            }
        } catch (e: Exception) {
            WorkScheduler.enqueueDue(context, at)
        }
    }

    /** Рестарт после свайпа/убийства процесса. */
    fun scheduleRestart(context: Context, delayMs: Long) {
        val manager = context.getSystemService(Context.ALARM_SERVICE) as? AlarmManager ?: return
        val at = SystemClock.elapsedRealtime() + delayMs.coerceAtLeast(1_000L)
        val pending = pending(context, REQ_RESTART, WakeReceiver.ACTION_RESTART)
        try {
            if (canExact(context)) {
                manager.setExactAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, at, pending)
            } else {
                manager.setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, at, pending)
                WorkScheduler.enqueueRestart(context, delayMs)
            }
        } catch (e: Exception) {
            WorkScheduler.enqueueRestart(context, delayMs)
        }
    }

    fun cancelAll(context: Context) {
        val manager = context.getSystemService(Context.ALARM_SERVICE) as? AlarmManager ?: return
        runCatching {
            manager.cancel(pending(context, REQ_RESTART, WakeReceiver.ACTION_RESTART))
            manager.cancel(pending(context, REQ_DUE, WakeReceiver.ACTION_DUE))
        }
        WorkScheduler.cancelRestarts(context)
    }

    private fun pending(context: Context, requestCode: Int, action: String): PendingIntent {
        val intent = Intent(context, WakeReceiver::class.java).setAction(action)
        return PendingIntent.getBroadcast(
            context,
            requestCode,
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
    }
}
