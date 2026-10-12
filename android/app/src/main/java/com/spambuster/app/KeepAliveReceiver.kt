package com.spambuster.app

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import androidx.core.content.ContextCompat

/**
 * Fired by the Doze-proof keep-alive alarm (see SpambusterService.scheduleKeepAlive).
 * Pokes the service: it re-checks the Telegram connection, restarts the bot if
 * the system killed it and schedules the next alarm.
 */
class KeepAliveReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val prefs = context.getSharedPreferences(SpambusterService.PREFS_NAME, Context.MODE_PRIVATE)
        if (!prefs.getBoolean(SpambusterService.KEY_SERVICE_ENABLED, false)) return

        val serviceIntent = Intent(context, SpambusterService::class.java).apply {
            action = SpambusterService.ACTION_KEEPALIVE
        }
        try {
            ContextCompat.startForegroundService(context, serviceIntent)
        } catch (e: Exception) {
            // Android 12+ may refuse a background FGS start when the app is not
            // exempt from battery optimisation. Try again a bit later.
            SpambusterService.scheduleKeepAlive(context, 60_000L)
        }
    }
}
