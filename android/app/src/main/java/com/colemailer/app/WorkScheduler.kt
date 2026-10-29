package com.colemailer.app

import android.content.Context
import android.content.Intent
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.Worker
import androidx.work.WorkerParameters
import java.util.concurrent.TimeUnit

/**
 * WorkManager как страховка на случай, когда точный alarm запрещён или
 * прошивка его выбросила: одна отложенная работа на рестарт/задачу и один
 * периодический «сторож» раз в 30 минут.
 */
object WorkScheduler {
    private const val WORK_RESTART = "colemailer-restart"
    private const val WORK_DUE = "colemailer-due"
    private const val WORK_GUARD = "colemailer-guard"

    fun enqueueRestart(context: Context, delayMs: Long) {
        val request = OneTimeWorkRequestBuilder<RestartWorker>()
            .setInitialDelay(delayMs.coerceAtLeast(0L), TimeUnit.MILLISECONDS)
            .build()
        runCatching {
            WorkManager.getInstance(context)
                .enqueueUniqueWork(WORK_RESTART, ExistingWorkPolicy.REPLACE, request)
        }
    }

    fun enqueueDue(context: Context, atEpochMs: Long) {
        val delay = (atEpochMs - System.currentTimeMillis()).coerceAtLeast(0L)
        val request = OneTimeWorkRequestBuilder<DueWorker>()
            .setInitialDelay(delay, TimeUnit.MILLISECONDS)
            .build()
        runCatching {
            WorkManager.getInstance(context)
                .enqueueUniqueWork(WORK_DUE, ExistingWorkPolicy.REPLACE, request)
        }
    }

    /** Периодический сторож: поднять сервис, если он должен работать. */
    fun ensureGuard(context: Context) {
        val request = PeriodicWorkRequestBuilder<GuardWorker>(30, TimeUnit.MINUTES).build()
        runCatching {
            WorkManager.getInstance(context)
                .enqueueUniquePeriodicWork(WORK_GUARD, ExistingPeriodicWorkPolicy.KEEP, request)
        }
    }

    fun cancelRestarts(context: Context) {
        runCatching {
            WorkManager.getInstance(context).cancelUniqueWork(WORK_RESTART)
            WorkManager.getInstance(context).cancelUniqueWork(WORK_DUE)
        }
    }
}

/** Отложенный рестарт сервиса (аналог точного alarm). */
class RestartWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        startIfEnabled()
        return Result.success()
    }
}

/** Проснуться к времени ближайшей задачи: разбудить бота или поднять сервис. */
class DueWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        if (!Prefs.serviceEnabled) return Result.success()
        if (BotService.isRunning()) {
            PythonBridge.kick()
        } else {
            startIfEnabled()
        }
        return Result.success()
    }
}

/** Раз в 30 минут: сервис должен быть жив, если пользователь его не выключал. */
class GuardWorker(context: Context, params: WorkerParameters) : Worker(context, params) {
    override fun doWork(): Result {
        if (!Prefs.serviceEnabled) return Result.success()
        if (!BotService.isRunning()) {
            startIfEnabled()
        } else if (!PythonBridge.isAlive) {
            // Сервис есть, а Python-поток умер: перезапускаем его.
            PythonBridge.start(applicationContext)
        }
        return Result.success()
    }
}

private fun startIfEnabled() {
    if (!Prefs.serviceEnabled) return
    val context = App.context
    val intent = Intent(context, BotService::class.java)
        .setAction(BotService.ACTION_START)
        .putExtra(BotService.EXTRA_SOURCE, "worker")
    ServiceStarter.start(context, intent)
}
