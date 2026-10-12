package com.spambuster.app

import android.Manifest
import android.app.ActivityManager
import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.os.PowerManager
import android.provider.Settings
import android.text.InputType
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.appcompat.app.AlertDialog
import androidx.appcompat.app.AppCompatActivity
import androidx.core.content.ContextCompat
import com.spambuster.app.databinding.ActivityMainBinding

class MainActivity : AppCompatActivity(), BotBridgeCoordinator.UiListener {

    companion object {
        private const val KEY_AUTOSTART_HINT_SHOWN = "autostart_hint_shown"
    }

    private lateinit var binding: ActivityMainBinding
    private lateinit var prefs: SharedPreferences

    private var codeDialog: AlertDialog? = null
    private var passwordDialog: AlertDialog? = null

    private val notificationPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.RequestPermission()
    ) { isGranted ->
        if (!isGranted) {
            Toast.makeText(this, "Уведомления нужны для фоновой работы 24/7", Toast.LENGTH_LONG).show()
        }
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        binding = ActivityMainBinding.inflate(layoutInflater)
        setContentView(binding.root)

        prefs = getSharedPreferences(SpambusterService.PREFS_NAME, Context.MODE_PRIVATE)

        loadSavedData()
        requestNotificationPermission()
        setupListeners()
        updateStatusUi()
    }

    override fun onResume() {
        super.onResume()
        BotBridgeCoordinator.uiListener = this
        updateStatusUi()

        if (BotBridgeCoordinator.isWaitingForCode) {
            showCodeInputDialog()
        }
        if (BotBridgeCoordinator.isWaitingForPassword) {
            showPasswordInputDialog()
        }
    }

    override fun onPause() {
        super.onPause()
        if (BotBridgeCoordinator.uiListener === this) {
            BotBridgeCoordinator.uiListener = null
        }
    }

    private fun loadSavedData() {
        binding.etApiId.setText(prefs.getString("api_id", ""))
        binding.etApiHash.setText(prefs.getString("api_hash", ""))
        binding.etPhone.setText(prefs.getString("phone", ""))
        binding.etPassword2FA.setText(prefs.getString("password_2fa", ""))
    }

    private fun saveData() {
        prefs.edit()
            .putString("api_id", binding.etApiId.text?.toString()?.trim() ?: "")
            .putString("api_hash", binding.etApiHash.text?.toString()?.trim() ?: "")
            .putString("phone", binding.etPhone.text?.toString()?.trim() ?: "")
            .putString("password_2fa", binding.etPassword2FA.text?.toString()?.trim() ?: "")
            .apply()
    }

    private fun requestNotificationPermission() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            if (ContextCompat.checkSelfPermission(this, Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED) {
                notificationPermissionLauncher.launch(Manifest.permission.POST_NOTIFICATIONS)
            }
        }
    }

    private fun setupListeners() {
        binding.btnStart.setOnClickListener {
            val apiId = binding.etApiId.text?.toString()?.trim() ?: ""
            val apiHash = binding.etApiHash.text?.toString()?.trim() ?: ""
            val phone = binding.etPhone.text?.toString()?.trim() ?: ""

            if (apiId.isEmpty() || apiHash.isEmpty()) {
                Toast.makeText(this, "Пожалуйста, введите API ID и API Hash", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            if (phone.isEmpty()) {
                Toast.makeText(this, "Пожалуйста, введите номер телефона", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }

            saveData()

            val serviceIntent = Intent(this, SpambusterService::class.java)
            ContextCompat.startForegroundService(this, serviceIntent)

            prefs.edit().putBoolean(SpambusterService.KEY_SERVICE_ENABLED, true).apply()
            BotBridgeCoordinator.lastStatus = "Запуск юзербота..."
            BotBridgeCoordinator.isBotRunning = true
            updateStatusUi()
            Toast.makeText(this, "🚀 Запуск Spambuster...", Toast.LENGTH_SHORT).show()
            ensureBackgroundAllowed()
        }

        binding.btnStop.setOnClickListener {
            val stopIntent = Intent(this, SpambusterService::class.java).apply {
                action = SpambusterService.ACTION_STOP
            }
            startService(stopIntent)

            prefs.edit().putBoolean(SpambusterService.KEY_SERVICE_ENABLED, false).apply()
            BotBridgeCoordinator.lastStatus = "Остановлен"
            BotBridgeCoordinator.isBotRunning = false
            updateStatusUi()
            Toast.makeText(this, "⏹ Фоновая работа остановлена", Toast.LENGTH_SHORT).show()
        }

        binding.btnBattery.setOnClickListener {
            requestIgnoreBatteryOptimization()
        }

        binding.btnAutostart.setOnClickListener {
            showBackgroundHelp()
        }
    }

    private fun isIgnoringBatteryOptimizations(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) return true
        val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
        return pm.isIgnoringBatteryOptimizations(packageName)
    }

    private fun isBackgroundRestricted(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.P) return false
        val am = getSystemService(Context.ACTIVITY_SERVICE) as ActivityManager
        return am.isBackgroundRestricted
    }

    /**
     * Without these two permissions Android (and especially MIUI/HyperOS,
     * EMUI, ColorOS, OneUI) freezes the bot as soon as the app leaves the
     * screen - exactly the "works only while the app is open" symptom.
     */
    private fun ensureBackgroundAllowed() {
        when {
            !isIgnoringBatteryOptimizations() -> requestIgnoreBatteryOptimization()
            isBackgroundRestricted() -> showBackgroundRestrictedDialog()
            !prefs.getBoolean(KEY_AUTOSTART_HINT_SHOWN, false) -> {
                prefs.edit().putBoolean(KEY_AUTOSTART_HINT_SHOWN, true).apply()
                showBackgroundHelp()
            }
        }
    }

    private fun showBackgroundRestrictedDialog() {
        if (isFinishing || isDestroyed) return
        AlertDialog.Builder(this)
            .setTitle("Фоновая работа запрещена")
            .setMessage("Для Spambuster включено ограничение фоновой работы. Откройте «Батарея» и выберите «Без ограничений», иначе бот работает только пока приложение открыто.")
            .setPositiveButton("Открыть настройки") { _, _ -> openAppDetails() }
            .setNegativeButton("Позже", null)
            .show()
    }

    private fun showBackgroundHelp() {
        if (isFinishing || isDestroyed) return
        val battery = if (isIgnoringBatteryOptimizations()) "✅" else "❌"
        val restricted = if (isBackgroundRestricted()) "❌" else "✅"
        val message = """
            Чтобы бот работал при закрытом приложении и выключенном экране:

            $battery Оптимизация батареи отключена
            $restricted Фоновая работа не ограничена

            • Xiaomi/Redmi/POCO: Автозапуск — вкл, Контроль активности — «Нет ограничений», в недавних закрепите приложение замком.
            • Huawei/Honor: Запуск приложений — вручную, включить все 3 переключателя.
            • Samsung: Батарея — «Без ограничений», убрать из «Спящих приложений».
            • Oppo/Realme/OnePlus/Vivo: Автозапуск — вкл, разрешить фоновую активность.
            • Не смахивайте приложение из недавних и не используйте «очистку памяти».
        """.trimIndent()
        AlertDialog.Builder(this)
            .setTitle("Работа в фоне 24/7")
            .setMessage(message)
            .setPositiveButton("Автозапуск") { _, _ -> openAutostartSettings() }
            .setNeutralButton("Батарея") { _, _ ->
                if (!isIgnoringBatteryOptimizations()) requestIgnoreBatteryOptimization() else openAppDetails()
            }
            .setNegativeButton("Закрыть", null)
            .show()
    }

    private fun openAutostartSettings() {
        val candidates = listOf(
            ComponentName("com.miui.securitycenter", "com.miui.permcenter.autostart.AutoStartManagementActivity"),
            ComponentName("com.miui.powerkeeper", "com.miui.powerkeeper.ui.HiddenAppsConfigActivity"),
            ComponentName("com.huawei.systemmanager", "com.huawei.systemmanager.startupmgr.ui.StartupNormalAppListActivity"),
            ComponentName("com.huawei.systemmanager", "com.huawei.systemmanager.optimize.process.ProtectActivity"),
            ComponentName("com.hihonor.systemmanager", "com.hihonor.systemmanager.startupmgr.ui.StartupNormalAppListActivity"),
            ComponentName("com.coloros.safecenter", "com.coloros.safecenter.permission.startup.StartupAppListActivity"),
            ComponentName("com.coloros.safecenter", "com.coloros.safecenter.startupapp.StartupAppListActivity"),
            ComponentName("com.oplus.safecenter", "com.oplus.safecenter.permission.startup.StartupAppListActivity"),
            ComponentName("com.oppo.safe", "com.oppo.safe.permission.startup.StartupAppListActivity"),
            ComponentName("com.vivo.permissionmanager", "com.vivo.permissionmanager.activity.BgStartUpManagerActivity"),
            ComponentName("com.iqoo.secure", "com.iqoo.secure.ui.phoneoptimize.AddWhiteListActivity"),
            ComponentName("com.samsung.android.lool", "com.samsung.android.sm.battery.ui.BatteryActivity"),
            ComponentName("com.samsung.android.sm", "com.samsung.android.sm.ui.battery.BatteryActivity"),
            ComponentName("com.asus.mobilemanager", "com.asus.mobilemanager.entry.FunctionActivity"),
            ComponentName("com.letv.android.letvsafe", "com.letv.android.letvsafe.AutobootManageActivity")
        )
        for (component in candidates) {
            val intent = Intent().apply {
                this.component = component
                addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            }
            try {
                // resolveActivity() is blind to other packages on Android 11+
                // without <queries>, so just try each screen.
                startActivity(intent)
                return
            } catch (e: Exception) {
                // try the next vendor screen
            }
        }
        Toast.makeText(this, "Откройте «Автозапуск» / «Батарея» для Spambuster вручную", Toast.LENGTH_LONG).show()
        openAppDetails()
    }

    private fun openAppDetails() {
        try {
            startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
                data = Uri.parse("package:$packageName")
            })
        } catch (e: Exception) {
            Toast.makeText(this, "Не удалось открыть настройки", Toast.LENGTH_SHORT).show()
        }
    }

    private fun requestIgnoreBatteryOptimization() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            val powerManager = getSystemService(Context.POWER_SERVICE) as PowerManager
            val packageName = packageName
            if (!powerManager.isIgnoringBatteryOptimizations(packageName)) {
                val intent = Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS).apply {
                    data = Uri.parse("package:$packageName")
                }
                try {
                    startActivity(intent)
                } catch (e: Exception) {
                    val fallbackIntent = Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)
                    startActivity(fallbackIntent)
                }
            } else {
                Toast.makeText(this, "Оптимизация батареи уже отключена для Spambuster", Toast.LENGTH_SHORT).show()
            }
        }
    }

    private fun updateStatusUi() {
        val isRunning = BotBridgeCoordinator.isBotRunning
        val statusText = BotBridgeCoordinator.lastStatus

        binding.tvStatus.text = "Статус: $statusText"
        if (isRunning) {
            binding.tvStatus.setTextColor(ContextCompat.getColor(this, R.color.accent_green))
            binding.viewStatusDot.setBackgroundResource(R.drawable.status_dot_green)
        } else {
            binding.tvStatus.setTextColor(ContextCompat.getColor(this, R.color.white))
            binding.viewStatusDot.setBackgroundResource(R.drawable.status_dot_red)
        }
    }

    private fun showCodeInputDialog() {
        if (isFinishing || isDestroyed) return
        if (codeDialog?.isShowing == true) return

        val input = EditText(this).apply {
            hint = "12345"
            inputType = InputType.TYPE_CLASS_NUMBER
            setSingleLine(true)
        }

        val container = FrameLayout(this).apply {
            val pad = (20 * resources.displayMetrics.density).toInt()
            setPadding(pad, pad / 2, pad, pad / 2)
            addView(input)
        }

        codeDialog = AlertDialog.Builder(this)
            .setTitle("Код подтверждения Telegram")
            .setMessage("Введите код, отправленный в официальный Telegram чат:")
            .setView(container)
            .setCancelable(false)
            .setPositiveButton("Подтвердить") { _, _ ->
                val code = input.text.toString().trim()
                BotBridgeCoordinator.submitCode(code)
            }
            .setNegativeButton("Отмена") { _, _ ->
                BotBridgeCoordinator.cancelWait()
            }
            .create()

        codeDialog?.show()
    }

    private fun showPasswordInputDialog() {
        if (isFinishing || isDestroyed) return
        if (passwordDialog?.isShowing == true) return

        val input = EditText(this).apply {
            hint = "Пароль 2FA"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
            setSingleLine(true)
        }

        val container = FrameLayout(this).apply {
            val pad = (20 * resources.displayMetrics.density).toInt()
            setPadding(pad, pad / 2, pad, pad / 2)
            addView(input)
        }

        passwordDialog = AlertDialog.Builder(this)
            .setTitle("Двухфакторная защита (2FA)")
            .setMessage("На аккаунте включен 2FA. Введите облачный пароль:")
            .setView(container)
            .setCancelable(false)
            .setPositiveButton("Войти") { _, _ ->
                val pwd = input.text.toString().trim()
                BotBridgeCoordinator.submitPassword(pwd)
            }
            .setNegativeButton("Отмена") { _, _ ->
                BotBridgeCoordinator.cancelWait()
            }
            .create()

        passwordDialog?.show()
    }

    // BotBridgeCoordinator.UiListener Callbacks
    override fun onCodeRequested() {
        runOnUiThread {
            showCodeInputDialog()
        }
    }

    override fun onPasswordRequested() {
        runOnUiThread {
            showPasswordInputDialog()
        }
    }

    override fun onStatusChanged(status: String, isRunning: Boolean) {
        runOnUiThread {
            updateStatusUi()
        }
    }

    override fun onLoggedIn(username: String, userId: Long) {
        runOnUiThread {
            Toast.makeText(this, "✅ Успешный вход в аккаунт $username (ID: $userId)", Toast.LENGTH_LONG).show()
            updateStatusUi()
        }
    }

    override fun onError(error: String) {
        runOnUiThread {
            Toast.makeText(this, "❌ Ошибка: $error", Toast.LENGTH_LONG).show()
            updateStatusUi()
        }
    }
}
