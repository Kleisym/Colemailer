package com.colemailer.app

import android.Manifest
import android.content.Intent
import android.os.Build
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity

/**
 * Мастер «чтобы работало в фоне».
 *
 * Шаги идут в жёстком порядке: уведомления (диалог ОС) -> exemption от
 * battery optimization (диалог ОС) -> экран автозапуска вендора ->
 * «Настройки приложения», если фон всё равно ограничен. Показывается не один
 * раз в жизни, а при каждом запуске, пока хоть один шаг не закрыт.
 */
class PermissionFlow(private val activity: AppCompatActivity) {

    private val notificationLauncher = activity.registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (!granted) {
            Toast.makeText(
                activity,
                R.string.toast_notifications_denied,
                Toast.LENGTH_LONG
            ).show()
        }
        openBatteryStep()
    }

    /** Первый запуск: сразу ведём по шагам, не дожидаясь нажатия «Старт». */
    fun startOnFirstLaunch() {
        if (Prefs.onboardingDone) return
        Prefs.onboardingDone = true
        requestNext()
    }

    /** Открыть первый нерешённый шаг. */
    fun requestNext() {
        if (!Notifications.granted(activity) && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            notificationLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            return
        }
        if (!BatteryOpt.isIgnoring(activity)) {
            openBatteryStep()
            return
        }
        if (!BatteryOpt.exactAlarmsAllowed(activity)) {
            // Без точного будильника время рассылки сдвигается на десятки
            // минут (остаётся только страховка WorkManager).
            openExactAlarms()
            return
        }
        if (!OemAutostart.assumeEnabled()) {
            openAutostart()
            return
        }
        if (!BatteryOpt.isBackgroundRestricted(activity) && BatteryOpt.isRunInBackgroundAllowed(activity)) {
            openAppDetails()
        }
    }

    fun openBatteryStep() {
        val intent = BatteryOpt.requestExemption(activity)
        if (!start(intent)) {
            start(BatteryOpt.batterySettings(activity))
        }
    }

    fun openAutostart() {
        val opened = OemAutostart.open(activity)
        if (!opened) {
            Toast.makeText(activity, R.string.toast_no_autostart_screen, Toast.LENGTH_LONG).show()
        }
    }

    fun openAppDetails() {
        start(BatteryOpt.appDetails(activity))
    }

    fun openExactAlarms() {
        start(BatteryOpt.requestExactAlarms(activity))
    }

    private fun start(intent: Intent): Boolean = try {
        activity.startActivity(intent)
        true
    } catch (e: Exception) {
        false
    }
}
