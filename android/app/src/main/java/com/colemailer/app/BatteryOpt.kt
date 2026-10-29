package com.colemailer.app

import android.app.ActivityManager
import android.app.AlarmManager
import android.app.AppOpsManager
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.os.PowerManager
import android.os.Process
import android.provider.Settings

/**
 * Всё, что можно проверить (и почти ничего — выдать) про работу в фоне.
 *
 * Честная правда: автоматически выдаются только POST_NOTIFICATIONS (диалог ОС)
 * и exemption от battery optimization (диалог ОС). OEM-автозапуск не имеет API
 * вообще — можно лишь открыть нужный экран настройки.
 */
object BatteryOpt {

    data class Check(val title: String, val ok: Boolean, val fix: Intent?)

    fun isIgnoring(context: Context): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return true
        val manager = context.getSystemService(Context.POWER_SERVICE) as? PowerManager ?: return true
        return runCatching { manager.isIgnoringBatteryOptimizations(context.packageName) }
            .getOrDefault(false)
    }

    fun isBackgroundRestricted(context: Context): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.P) return false
        val manager = context.getSystemService(Context.ACTIVITY_SERVICE) as? ActivityManager
            ?: return false
        return runCatching { manager.isBackgroundRestricted }.getOrDefault(false)
    }

    /** appops RUN_IN_BACKGROUND: ловит MIUI/HyperOS «Ограничить активность». */
    fun isRunInBackgroundAllowed(context: Context): Boolean {
        val manager = context.getSystemService(Context.APP_OPS_SERVICE) as? AppOpsManager
            ?: return true
        // Константа AppOpsManager.OPSTR_RUN_IN_BACKGROUND скрыта в SDK,
        // поэтому используется её строковое значение.
        val op = "android:run_in_background"
        return try {
            val mode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
                manager.unsafeCheckOpNoThrow(
                    op,
                    Process.myUid(),
                    context.packageName
                )
            } else {
                @Suppress("DEPRECATION")
                manager.checkOpNoThrow(
                    op,
                    Process.myUid(),
                    context.packageName
                )
            }
            mode == AppOpsManager.MODE_ALLOWED || mode == AppOpsManager.MODE_DEFAULT
        } catch (e: Exception) {
            true
        }
    }

    fun requestExemption(context: Context): Intent =
        Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS)
            .setData(Uri.parse("package:" + context.packageName))

    fun appDetails(context: Context): Intent =
        Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
            .setData(Uri.parse("package:" + context.packageName))

    fun batterySettings(context: Context): Intent =
        Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)

    fun exactAlarmsAllowed(context: Context): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return true
        val manager = context.getSystemService(Context.ALARM_SERVICE) as? AlarmManager ?: return true
        return runCatching { manager.canScheduleExactAlarms() }.getOrDefault(false)
    }

    fun requestExactAlarms(context: Context): Intent {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.S) return appDetails(context)
        return Intent(Settings.ACTION_REQUEST_SCHEDULE_EXACT_ALARM)
            .setData(Uri.parse("package:" + context.packageName))
    }

    /** Чек-лист для экрана «Работа в фоне». Все четыре пункта проверяются кодом. */
    fun report(context: Context): List<Check> = listOf(
        Check(
            context.getString(R.string.check_notifications),
            Notifications.granted(context),
            Notifications.requestIntent(context)
        ),
        Check(
            context.getString(R.string.check_battery),
            isIgnoring(context),
            requestExemption(context)
        ),
        Check(
            context.getString(R.string.check_exact_alarms),
            exactAlarmsAllowed(context),
            requestExactAlarms(context)
        ),
        Check(
            context.getString(R.string.check_background),
            !isBackgroundRestricted(context) && isRunInBackgroundAllowed(context),
            appDetails(context)
        )
    )

    fun fixedCount(context: Context): Int = report(context).count { it.ok }
}
