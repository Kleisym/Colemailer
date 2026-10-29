package com.colemailer.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * Будильники: «пора к задаче» и «подними сервис».
 *
 * Манифест держим exported=false: это внутренние броадкасты, чужому
 * приложению здесь делать нечего.
 */
class WakeReceiver : BroadcastReceiver() {

    companion object {
        const val ACTION_DUE = "com.colemailer.app.DUE"
        const val ACTION_RESTART = "com.colemailer.app.RESTART"
    }

    override fun onReceive(context: Context, intent: Intent) {
        if (!Prefs.serviceEnabled) return
        when (intent.action) {
            ACTION_DUE -> {
                if (BotService.isRunning() && PythonBridge.isAlive) {
                    PythonBridge.kick()
                } else if (BotService.isRunning()) {
                    PythonBridge.start(context)
                } else {
                    BotService.start(context, "alarm")
                }
            }

            ACTION_RESTART -> BotService.start(context, "alarm")
        }
    }
}
