package com.colemailer.app.ui

import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Bundle
import android.provider.Settings
import android.view.View
import android.widget.TextView
import android.widget.Toast
import androidx.activity.result.contract.ActivityResultContracts
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import com.colemailer.app.BatteryOpt
import com.colemailer.app.OemAutostart
import com.colemailer.app.Prefs
import com.colemailer.app.PythonBridge
import com.colemailer.app.R
import com.colemailer.app.RootShell
import com.colemailer.app.ShizukuShell
import com.colemailer.app.TelegramCodeListener
import com.colemailer.app.UpdateManager
import com.google.android.material.button.MaterialButton
import com.google.android.material.dialog.MaterialAlertDialogBuilder
import com.google.android.material.switchmaterial.SwitchMaterial
import com.google.android.material.textfield.TextInputEditText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import rikka.shizuku.Shizuku

/**
 * Настройки: антиспам/автосаб (ключи config.txt), чек-лист фона, версия.
 *
 * Настройки пишутся в те же ключи config.txt, которые читает bot.py, иначе
 * UI и бот разъезжаются.
 */
class SettingsFragment : Fragment(R.layout.fragment_settings) {

    private lateinit var switchAntispam: SwitchMaterial
    private lateinit var switchAutosub: SwitchMaterial
    private lateinit var switchQuietLogs: SwitchMaterial
    private lateinit var etFolder: TextInputEditText
    private lateinit var tvBgReport: TextView
    private lateinit var tvVersion: TextView
    private lateinit var switchAutoUpdate: SwitchMaterial
    private lateinit var tvUpdateStatus: TextView
    private var pendingInfo: UpdateManager.Info? = null
    private var pendingFile: java.io.File? = null
    private var askedInstallPermission = false

    private val installPermissionLauncher = registerForActivityResult(
        ActivityResultContracts.StartActivityForResult()
    ) {
        // Вернулись из «Разрешить установку из этого источника» — ставим уже
        // скачанный файл, не проверяя релиз и не качая его заново.
        installPending()
    }

    private val shizukuPermissionListener = Shizuku.OnRequestPermissionResultListener { requestCode, grantResult ->
        if (requestCode == ShizukuShell.REQUEST_CODE) {
            activity?.runOnUiThread {
                if (grantResult == PackageManager.PERMISSION_GRANTED) {
                    runShizukuGrant()
                } else {
                    Toast.makeText(requireContext(), R.string.toast_shizuku_missing, Toast.LENGTH_LONG).show()
                }
            }
        }
    }

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        switchAntispam = view.findViewById(R.id.switch_antispam)
        switchAutosub = view.findViewById(R.id.switch_autosub)
        switchQuietLogs = view.findViewById(R.id.switch_quiet_logs)
        etFolder = view.findViewById(R.id.et_folder)
        tvBgReport = view.findViewById(R.id.tv_bg_report)
        tvVersion = view.findViewById(R.id.tv_version)
        switchAutoUpdate = view.findViewById(R.id.switch_auto_update)
        tvUpdateStatus = view.findViewById(R.id.tv_update_status)

        tvVersion.text = appVersion()
        switchAutoUpdate.isChecked = Prefs.autoUpdate
        switchAutoUpdate.setOnCheckedChangeListener { _, checked -> Prefs.autoUpdate = checked }
        tvUpdateStatus.text = getString(R.string.update_current, appVersion())
        view.findViewById<MaterialButton>(R.id.btn_check_update).setOnClickListener { checkForUpdate() }

        view.findViewById<MaterialButton>(R.id.btn_save_settings).setOnClickListener { saveSettings() }
        view.findViewById<MaterialButton>(R.id.btn_fix_all).setOnClickListener {
            (activity as? MainActivity)?.permissionFlow?.requestAll()
        }
        view.findViewById<MaterialButton>(R.id.btn_root_grants).setOnClickListener { grantViaRoot() }
        view.findViewById<MaterialButton>(R.id.btn_shizuku_grants).setOnClickListener { grantViaShizuku() }
        view.findViewById<MaterialButton>(R.id.btn_code_access).setOnClickListener {
            runCatching { startActivity(TelegramCodeListener.requestIntent()) }
        }
        runCatching { Shizuku.addRequestPermissionResultListener(shizukuPermissionListener) }
        view.findViewById<MaterialButton>(R.id.btn_open_autostart).setOnClickListener {
            (activity as? MainActivity)?.permissionFlow?.openAutostart()
        }
        view.findViewById<MaterialButton>(R.id.btn_mark_autostart).setOnClickListener {
            OemAutostart.confirm()
            Toast.makeText(requireContext(), R.string.toast_autostart_marked, Toast.LENGTH_SHORT).show()
            refreshBackgroundReport()
        }
        view.findViewById<MaterialButton>(R.id.btn_app_details).setOnClickListener {
            (activity as? MainActivity)?.permissionFlow?.openAppDetails()
        }
        view.findViewById<MaterialButton>(R.id.btn_manual_api).setOnClickListener {
            openUrl("https://my.telegram.org")
        }

        loadSettings()
        refreshBackgroundReport()
    }

    override fun onResume() {
        super.onResume()
        refreshBackgroundReport()
    }

    private fun loadSettings() {
        val context = requireContext().applicationContext
        viewLifecycleOwner.lifecycleScope.launch {
            val json: JSONObject? = withContext(Dispatchers.IO) {
                PythonBridge.ensureStarted(context)
                PythonBridge.settings()
            }
            if (json == null) {
                // Python ещё не поднимался: показываем значения из Prefs.
                switchAntispam.isChecked = true
                switchAutosub.isChecked = true
                switchQuietLogs.isChecked = true
                etFolder.setText(DEFAULT_FOLDER)
                return@launch
            }
            switchAntispam.isChecked = json.optBoolean("antispam", true)
            switchAutosub.isChecked = json.optBoolean("auto_sub", true)
            switchQuietLogs.isChecked = json.optBoolean("quiet_logs", true)
            etFolder.setText(json.optString("folder").ifBlank { DEFAULT_FOLDER })
        }
    }

    private fun saveSettings() {
        val payload = JSONObject().apply {
            put("antispam", switchAntispam.isChecked)
            put("auto_sub", switchAutosub.isChecked)
            put("quiet_logs", switchQuietLogs.isChecked)
            put("folder", etFolder.text?.toString()?.trim().orEmpty().ifBlank { DEFAULT_FOLDER })
        }
        val context = requireContext().applicationContext
        viewLifecycleOwner.lifecycleScope.launch {
            val result: JSONObject? = withContext(Dispatchers.IO) {
                PythonBridge.ensureStarted(context)
                PythonBridge.saveSettings(payload.toString())
            }
            val message = if (result?.optBoolean("ok") == true) {
                getString(R.string.toast_saved)
            } else {
                getString(R.string.toast_error_fmt, result?.optString("error").orEmpty().ifBlank { "config.txt" })
            }
            Toast.makeText(requireContext(), message, Toast.LENGTH_SHORT).show()
        }
    }

    private fun refreshBackgroundReport() {
        val context = requireContext()
        val report = BatteryOpt.report(context)
        val text = buildString {
            report.forEach { check ->
                append(if (check.ok) "✅ " else "❌ ")
                append(check.title)
                append('\n')
            }
            append('\n')
            append(OemAutostart.manualSteps())
        }
        tvBgReport.text = text.trim()
    }

    private fun checkForUpdate() {
        // Если файл уже скачан и ждёт разрешения — не проверяем релиз заново.
        if (pendingFile != null) {
            installPending()
            return
        }
        val context = requireContext().applicationContext
        tvUpdateStatus.text = getString(R.string.update_downloading)
        viewLifecycleOwner.lifecycleScope.launch {
            val info = withContext(Dispatchers.IO) { UpdateManager.fetchLatest() }
            if (info == null) {
                tvUpdateStatus.text = getString(R.string.update_check_failed)
                return@launch
            }
            val current = UpdateManager.currentVersion(requireContext())
            if (!UpdateManager.isNewer(info.version, current)) {
                tvUpdateStatus.text = getString(R.string.update_latest)
                return@launch
            }
            pendingInfo = info
            val cached = UpdateManager.cachedFile(context, info)
            tvUpdateStatus.text = getString(R.string.update_available, info.version)
            if (cached != null) {
                pendingFile = cached
                installPending()
                return@launch
            }
            MaterialAlertDialogBuilder(requireContext())
                .setTitle(getString(R.string.update_dialog_title, info.version))
                .setMessage(R.string.update_dialog_text)
                .setPositiveButton(R.string.update_dialog_download) { _, _ -> downloadAndInstall(info) }
                .setNegativeButton(R.string.update_dialog_later, null)
                .show()
        }
    }

    private fun downloadAndInstall(info: UpdateManager.Info) {
        val context = requireContext().applicationContext
        pendingInfo = info
        tvUpdateStatus.text = getString(R.string.update_downloading)
        viewLifecycleOwner.lifecycleScope.launch {
            val file = withContext(Dispatchers.IO) { UpdateManager.download(context, info) }
            if (file == null) {
                pendingInfo = null
                tvUpdateStatus.text = getString(R.string.update_download_failed)
                return@launch
            }
            pendingFile = file
            installPending()
        }
    }

    private fun installPending() {
        if (!isAdded) return
        val info = pendingInfo ?: return
        val context = requireContext().applicationContext
        val file = pendingFile ?: UpdateManager.cachedFile(context, info) ?: return
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
            !requireContext().packageManager.canRequestPackageInstalls()
        ) {
            if (!askedInstallPermission) {
                askedInstallPermission = true
                runCatching {
                    installPermissionLauncher.launch(
                        Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES)
                            .setData(Uri.parse("package:" + context.packageName))
                    )
                }
                tvUpdateStatus.text = getString(R.string.update_need_install_permission)
            } else {
                tvUpdateStatus.text = getString(R.string.update_need_install_permission)
            }
            return
        }
        viewLifecycleOwner.lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) { UpdateManager.install(context, file) }
            tvUpdateStatus.text = when (result) {
                "root" -> getString(R.string.update_installed_root)
                "prompt" -> getString(R.string.update_installer_opened)
                "permission" -> getString(R.string.update_need_install_permission)
                else -> getString(R.string.toast_error_fmt, result)
            }
            if (result == "root" || result == "prompt") {
                pendingInfo = null
                pendingFile = null
                askedInstallPermission = false
            }
        }
    }

    override fun onDestroyView() {
        runCatching { Shizuku.removeRequestPermissionResultListener(shizukuPermissionListener) }
        super.onDestroyView()
    }

    /**
     * Shizuku дает shell/ADB-права без root. Пользователь один раз запускает
     * Shizuku, приложение запрашивает доступ и выполняет те же pm grant/appops.
     */
    private fun grantViaShizuku() {
        if (!ShizukuShell.isBinderAlive()) {
            Toast.makeText(requireContext(), R.string.toast_shizuku_missing, Toast.LENGTH_LONG).show()
            runCatching {
                startActivity(
                    Intent(Intent.ACTION_VIEW, Uri.parse("https://shizuku.rikka.app/download/"))
                )
            }
            return
        }
        if (!ShizukuShell.hasPermission()) {
            if (!ShizukuShell.requestPermission()) {
                Toast.makeText(requireContext(), R.string.toast_shizuku_missing, Toast.LENGTH_LONG).show()
            }
            return
        }
        runShizukuGrant()
    }

    private fun runShizukuGrant() {
        val context = requireContext().applicationContext
        val button = view?.findViewById<MaterialButton>(R.id.btn_shizuku_grants) ?: return
        button.isEnabled = false
        Toast.makeText(requireContext(), R.string.toast_shizuku_checking, Toast.LENGTH_SHORT).show()
        viewLifecycleOwner.lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) { ShizukuShell.grantAll(context) }
            button.isEnabled = true
            refreshBackgroundReport()
            if (result.ok) {
                Toast.makeText(requireContext(), R.string.toast_shizuku_ok, Toast.LENGTH_LONG).show()
            } else {
                Toast.makeText(requireContext(), R.string.toast_shizuku_failed, Toast.LENGTH_LONG).show()
                tvBgReport.append("\n\nshizuku:\n")
                tvBgReport.append(result.log.takeLast(1200))
            }
        }
    }

    /**
     * Root-режим: если su есть, выдаём разрешения и appops командами.
     * Без root просто запускаем обычный мастер системных диалогов.
     */
    private fun grantViaRoot() {
        val context = requireContext().applicationContext
        val button = view?.findViewById<MaterialButton>(R.id.btn_root_grants) ?: return
        button.isEnabled = false
        Toast.makeText(requireContext(), R.string.toast_root_checking, Toast.LENGTH_SHORT).show()

        viewLifecycleOwner.lifecycleScope.launch {
            val result = withContext(Dispatchers.IO) {
                if (!RootShell.isAvailable()) {
                    null
                } else {
                    RootShell.grantAll(context)
                }
            }
            button.isEnabled = true
            if (result == null) {
                Toast.makeText(requireContext(), R.string.toast_root_unavailable, Toast.LENGTH_LONG).show()
                (activity as? MainActivity)?.permissionFlow?.requestAll()
                return@launch
            }
            refreshBackgroundReport()
            if (result.ok) {
                Toast.makeText(requireContext(), R.string.toast_root_ok, Toast.LENGTH_LONG).show()
            } else {
                Toast.makeText(requireContext(), R.string.toast_root_failed, Toast.LENGTH_LONG).show()
                tvBgReport.append("\n\nroot:\n")
                tvBgReport.append(result.log.takeLast(1200))
            }
        }
    }

    private fun appVersion(): String {
        val context = requireContext()
        return try {
            val info = context.packageManager.getPackageInfo(context.packageName, 0)
            info.versionName ?: "—"
        } catch (e: Exception) {
            "—"
        }
    }

    private fun openUrl(url: String) {
        try {
            startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)))
        } catch (e: Exception) {
            Toast.makeText(requireContext(), R.string.toast_link_failed, Toast.LENGTH_SHORT).show()
        }
    }

    companion object {
        private const val DEFAULT_FOLDER = "автосабнутое"
    }
}
