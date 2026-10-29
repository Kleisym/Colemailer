package com.colemailer.app

import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.os.Build
import android.os.IBinder
import androidx.core.app.ServiceCompat
import java.util.concurrent.atomic.AtomicBoolean

/**
 * Foreground-сервис с юзерботом.
 *
 * Главное отличие от прежней версии: нет постоянного PARTIAL_WAKE_LOCK и
 * WifiLock HIGH_PERF, нет notify() каждые 60 секунд и нет «пинка» раз в
 * 10 минут. Тип сервиса — specialUse: dataSync на Android 15 живёт 6 ч/сутки
 * и не может стартовать из BOOT_COMPLETED.
 */
class BotService : Service() {

    companion object {
        const val ACTION_START = "com.colemailer.app.START"
        const val ACTION_STOP = "com.colemailer.app.STOP"
        const val EXTRA_SOURCE = "source"

        @Volatile
        private var instance: BotService? = null

        fun isRunning(): Boolean = instance != null

        fun start(context: Context, source: String) {
            val intent = Intent(context, BotService::class.java)
                .setAction(ACTION_START)
                .putExtra(EXTRA_SOURCE, source)
            ServiceStarter.start(context, intent)
        }

        fun stop(context: Context) {
            runCatching {
                context.startService(
                    Intent(context, BotService::class.java).setAction(ACTION_STOP)
                )
            }
        }
    }

    private val stopping = AtomicBoolean(false)

    override fun onCreate() {
        super.onCreate()
        instance = this
        Notifications.ensureChannels(this)
        NetMonitor.register(this) { online -> onNetworkChanged(online) }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val action = intent?.action

        if (action == ACTION_STOP) {
            shutdown()
            return START_NOT_STICKY
        }

        // startForeground обязателен в любом пути: сервис поднят через
        // startForegroundService, и молчаливый return = ANR системы.
        if (!enterForeground()) return START_NOT_STICKY

        if (action == ACTION_START) {
            Prefs.serviceEnabled = true
        }

        if (!Prefs.serviceEnabled) {
            // «Стоп» нажимали раньше: sticky-рестарт не должен воскрешать бота.
            ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
            stopSelf()
            return START_NOT_STICKY
        }

        if (!Prefs.hasCredentials()) {
            // Без ключей сервис жил бы вхолостую и ел батарею (баг старой
            // версии): останавливаемся и оставляем понятную ошибку в статусе.
            shutdown()
            StatusStore.set(getString(R.string.toast_need_keys), false, Level.ERROR)
            return START_NOT_STICKY
        }

        StatusStore.setPhase(Phase.STARTING, getString(R.string.state_starting), running = true)
        Notifications.update(this, StatusStore.current())

        if (PythonBridge.isAlive) {
            NetMonitor.withCpuWake(this) { PythonBridge.kick() }
        } else {
            PythonBridge.start(this)
        }

        return START_STICKY
    }

    /**
     * specialUse на Android 14+, «тип из манифеста» на более старых версиях.
     * dataSync осознанно не используется.
     */
    private fun enterForeground(): Boolean {
        val notification = Notifications.foreground(this, StatusStore.current())
        val type = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.UPSIDE_DOWN_CAKE) {
            ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE
        } else {
            0
        }
        return try {
            ServiceCompat.startForeground(this, Notifications.ID_FOREGROUND, notification, type)
            true
        } catch (e: Exception) {
            StatusStore.set(
                "Android не разрешил фоновый запуск. Откройте приложение и нажмите «Старт».",
                false,
                Level.ERROR
            )
            WakeScheduler.scheduleRestart(this, 60_000L)
            ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
            stopSelf()
            false
        }
    }

    /** Смена сети: единственный повод разбудить TCP-соединение сразу. */
    private fun onNetworkChanged(online: Boolean) {
        if (!Prefs.serviceEnabled) return
        if (!online) {
            StatusStore.setPhase(Phase.DEGRADED, "Нет сети, ждём подключения", running = true)
            return
        }
        if (PythonBridge.isAlive) {
            NetMonitor.withCpuWake(this) { PythonBridge.kick() }
        }
    }

    override fun onTaskRemoved(rootIntent: Intent?) {
        // Свайп из «недавних»: процесс умрёт сразу после возврата. Точный
        // будильник — единственный путь рестарта, разрешённый с Android 12.
        if (Prefs.serviceEnabled) {
            WakeScheduler.scheduleRestart(this, 2_000L)
        }
        super.onTaskRemoved(rootIntent)
    }

    override fun onDestroy() {
        instance = null
        NetMonitor.unregister(this)
        if (!stopping.get()) {
            // Убило система/прошивка: честно показываем «перезапускаюсь»,
            // а поднимает нас START_STICKY, будильник или сторож WorkManager.
            if (Prefs.serviceEnabled) {
                StatusStore.set("Перезапуск…", true, Level.WARN)
            } else {
                StatusStore.markStopped()
            }
        }
        super.onDestroy()
    }

    /** Полный стоп: выключаем флаг, будильники, Python и уведомление. */
    private fun shutdown() {
        if (!stopping.compareAndSet(false, true)) return
        Prefs.serviceEnabled = false
        WakeScheduler.cancelAll(this)
        PythonBridge.stop()
        AuthQueue.cancelAll()
        StatusStore.markStopped()
        ServiceCompat.stopForeground(this, ServiceCompat.STOP_FOREGROUND_REMOVE)
        stopSelf()
    }

    override fun onBind(intent: Intent?): IBinder? = null
}
