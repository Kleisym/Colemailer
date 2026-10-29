package com.colemailer.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * Восстановление сервиса после перезагрузки/обновления приложения.
 *
 * Список действий здесь и в манифесте обязан совпадать: раньше код ловил
 * QUICKBOOT-события, которых не было в манифесте, и эти ветки были мёртвыми.
 */
class BootReceiver : BroadcastReceiver() {

    private val actions = setOf(
        Intent.ACTION_BOOT_COMPLETED,
        Intent.ACTION_MY_PACKAGE_REPLACED,
        Intent.ACTION_USER_UNLOCKED,
        "android.intent.action.QUICKBOOT_POWERON",
        "com.htc.intent.action.QUICKBOOT_POWERON",
        "com.samsung.intent.action.QUICKBOOT_POWERON"
    )

    override fun onReceive(context: Context, intent: Intent) {
        val action = intent.action ?: return
        if (action !in actions) return
        if (!Prefs.serviceEnabled) return
        if (!Prefs.hasCredentials()) return

        // Прямой старт specialUse-сервиса из BOOT_COMPLETED разрешён (в отличие
        // от dataSync на Android 15). Если всё же откажут — останется alarm.
        val started = ServiceStarter.start(
            context,
            Intent(context, BotService::class.java)
                .setAction(BotService.ACTION_START)
                .putExtra(BotService.EXTRA_SOURCE, "boot")
        )
        if (!started) {
            WakeScheduler.scheduleRestart(context, 30_000L)
        }
    }
}
