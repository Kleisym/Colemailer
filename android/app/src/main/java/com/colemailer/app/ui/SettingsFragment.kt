package com.colemailer.app.ui

import android.content.Intent
import android.net.Uri
import android.os.Bundle
import android.view.View
import android.widget.TextView
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import com.colemailer.app.BatteryOpt
import com.colemailer.app.OemAutostart
import com.colemailer.app.PythonBridge
import com.colemailer.app.R
import com.colemailer.app.RootShell
import com.google.android.material.button.MaterialButton
import com.google.android.material.switchmaterial.SwitchMaterial
import com.google.android.material.textfield.TextInputEditText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

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

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        switchAntispam = view.findViewById(R.id.switch_antispam)
        switchAutosub = view.findViewById(R.id.switch_autosub)
        switchQuietLogs = view.findViewById(R.id.switch_quiet_logs)
        etFolder = view.findViewById(R.id.et_folder)
        tvBgReport = view.findViewById(R.id.tv_bg_report)
        tvVersion = view.findViewById(R.id.tv_version)

        tvVersion.text = appVersion()

        view.findViewById<MaterialButton>(R.id.btn_save_settings).setOnClickListener { saveSettings() }
        view.findViewById<MaterialButton>(R.id.btn_fix_all).setOnClickListener {
            (activity as? MainActivity)?.permissionFlow?.requestAll()
        }
        view.findViewById<MaterialButton>(R.id.btn_root_grants).setOnClickListener { grantViaRoot() }
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
