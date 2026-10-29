package com.colemailer.app

import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat

/**
 * Единственная точка старта foreground-сервиса.
 *
 * С Android 12 `startForegroundService` из фона запрещён, и исключение
 * ForegroundServiceStartNotAllowedException раньше просто глоталось — сервис
 * больше никогда не поднимался. Теперь отказ означает «переложить попытку на
 * будильник и WorkManager».
 */
object ServiceStarter {

    fun start(context: Context, intent: Intent): Boolean = try {
        ContextCompat.startForegroundService(context, intent)
        true
    } catch (e: Exception) {
        WakeScheduler.scheduleRestart(context, 60_000L)
        false
    }
}
