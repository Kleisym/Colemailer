package com.colemailer.app

import android.Manifest
import android.content.Intent
import android.os.Build
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AppCompatActivity
import androidx.lifecycle.lifecycleScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Мастер «чтобы работало в фоне».
 *
 * Шаги идут по цепочке и сами продолжаются после возврата из системного
 * экрана: уведомления -> exemption от battery optimization -> точные будильники
 * -> ограничение фона -> автозапуск вендора. Повторно один и тот же экран за
 * один проход не открывается (иначе после возврата был бы бесконечный цикл).
 * Если на устройстве есть root, всё это можно выдать одной кнопкой в
 * настройках — см. [RootShell].
 */
class PermissionFlow(private val activity: AppCompatActivity) {

    private var askedNotifications = false
    private var askedBattery = false
    private var askedExact = false
    private var askedDetails = false
    private var askedAutostart = false
    private var askedCodeAccess = false

    private val notificationLauncher = activity.registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { granted ->
        if (!granted) {
            Toast.makeText(activity, R.string.toast_notifications_denied, Toast.LENGTH_LONG).show()
        }
        requestNext()
    }

    private val batteryLauncher = activity.registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { requestNext() }

    private val exactLauncher = activity.registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { requestNext() }

    private val detailsLauncher = activity.registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { requestNext() }

    private val autostartLauncher = activity.registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) {
        // Экран вендора вернул управление — считаем, что пользователь его видел.
        OemAutostart.confirm()
        requestNext()
    }

    private val codeAccessLauncher = activity.registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) { requestNext() }

    /** Первый запуск: сразу ведём по шагам, не дожидаясь нажатия «Старт». */
    fun startOnFirstLaunch() {
        if (Prefs.onboardingDone) return
        Prefs.onboardingDone = true
        resetAsked()
        // На рутованных устройствах сначала пробуем выдать всё молча.
        activity.lifecycleScope.launch {
            val rooted = withContext(Dispatchers.IO) {
                if (RootShell.isAvailable()) {
                    RootShell.grantAll(activity.applicationContext)
                } else {
                    null
                }
            }
            if (rooted?.ok == true) {
                Toast.makeText(activity, R.string.toast_root_ok, Toast.LENGTH_LONG).show()
            } else {
                requestNext()
            }
        }
    }

    /** Кнопка «Исправить»: начинает проход заново. */
    fun requestAll() {
        resetAsked()
        requestNext()
    }

    /** Открыть первый нерешённый шаг. */
    fun requestNext() {
        if (!Notifications.granted(activity) && Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU && !askedNotifications) {
            askedNotifications = true
            notificationLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            return
        }
        if (!BatteryOpt.isIgnoring(activity) && !askedBattery) {
            askedBattery = true
            openBatteryStep()
            return
        }
        if (!BatteryOpt.exactAlarmsAllowed(activity) && !askedExact) {
            // Без точного будильника время рассылки сдвигается на десятки
            // минут (остаётся только страховка WorkManager).
            askedExact = true
            openExactAlarms()
            return
        }
        if ((BatteryOpt.isBackgroundRestricted(activity) || !BatteryOpt.isRunInBackgroundAllowed(activity)) && !askedDetails) {
            askedDetails = true
            openAppDetails()
            return
        }
        if (!TelegramCodeListener.isEnabled(activity) && !askedCodeAccess) {
            askedCodeAccess = true
            if (launchForResult(codeAccessLauncher, TelegramCodeListener.requestIntent())) return
        }
        if (!OemAutostart.assumeEnabled() && !askedAutostart) {
            askedAutostart = true
            openAutostart()
        }
    }

    fun openBatteryStep() {
        val intent = BatteryOpt.requestExemption(activity)
        if (!launchForResult(batteryLauncher, intent)) {
            start(BatteryOpt.batterySettings(activity))
        }
    }

    fun openAutostart() {
        val intent = OemAutostart.bestIntent(activity)?.apply {
            // Для startActivityForResult NEW_TASK не нужен и мешает вернуть результат.
            flags = flags and Intent.FLAG_ACTIVITY_NEW_TASK.inv()
        }
        if (intent == null || !launchForResult(autostartLauncher, intent)) {
            if (!OemAutostart.open(activity)) {
                Toast.makeText(activity, R.string.toast_no_autostart_screen, Toast.LENGTH_LONG).show()
            }
        }
    }

    fun openAppDetails() {
        if (!launchForResult(detailsLauncher, BatteryOpt.appDetails(activity))) {
            start(BatteryOpt.appDetails(activity))
        }
    }

    fun openExactAlarms() {
        if (!launchForResult(exactLauncher, BatteryOpt.requestExactAlarms(activity))) {
            start(BatteryOpt.requestExactAlarms(activity))
        }
    }

    private fun resetAsked() {
        askedNotifications = false
        askedBattery = false
        askedExact = false
        askedDetails = false
        askedAutostart = false
        askedCodeAccess = false
    }

    private fun launchForResult(
        launcher: androidx.activity.result.ActivityResultLauncher<Intent>,
        intent: Intent
    ): Boolean = try {
        launcher.launch(intent)
        true
    } catch (e: Exception) {
        false
    }

    private fun start(intent: Intent): Boolean = try {
        activity.startActivity(intent)
        true
    } catch (e: Exception) {
        false
    }
}
