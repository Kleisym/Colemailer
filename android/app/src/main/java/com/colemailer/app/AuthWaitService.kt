package com.colemailer.app

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.ServiceCompat

/**
 * Короткоживущий foreground-сервис на время ввода кода/пароля.
 *
 * Без него Android мог убить процесс, пока пользователь ушёл в Telegram за
 * кодом: ожидание в Python-потоке пропадало, и авто-получение api_id
 * срывалось. Теперь процесс держится, а в шторке висит уведомление, по
 * которому можно вернуться к вводу.
 */
class AuthWaitService : Service() {

    companion object {
        private const val ACTION_START = "com.colemailer.app.AUTH_WAIT_START"

        fun start(context: Context) {
            runCatching {
                val intent = Intent(context, AuthWaitService::class.java).setAction(ACTION_START)
                if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                    context.startForegroundService(intent)
                } else {
                    context.startService(intent)
                }
            }
        }

        fun stop(context: Context) {
            runCatching { context.stopService(Intent(context, AuthWaitService::class.java)) }
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        Notifications.ensureChannels(this)
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val notification = Notifications.authWait(this)
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_DATA_SYNC
        } else {
            0
        }
        return try {
            ServiceCompat.startForeground(this, Notifications.ID_AUTH_WAIT, notification, type)
            START_NOT_STICKY
        } catch (e: Exception) {
            stopSelf()
            START_NOT_STICKY
        }
    }
}
