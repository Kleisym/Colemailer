package com.colemailer.app.ui

import android.os.Bundle
import android.view.View
import android.widget.TextView
import android.widget.Toast
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import com.colemailer.app.Prefs
import com.colemailer.app.PythonBridge
import com.colemailer.app.R
import com.google.android.material.button.MaterialButton
import com.google.android.material.textfield.TextInputEditText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject

/**
 * Подключение: api_id/api_hash/телефон/2FA, ручное сохранение и авто-получение
 * ключей через my.telegram.org (код подтверждения приходит в Telegram).
 */
class ConnectFragment : Fragment(R.layout.fragment_connect) {

    private lateinit var etApiId: TextInputEditText
    private lateinit var etApiHash: TextInputEditText
    private lateinit var etPhone: TextInputEditText
    private lateinit var etPassword: TextInputEditText
    private lateinit var tvStatus: TextView
    private lateinit var btnAuto: MaterialButton
    private lateinit var btnSave: MaterialButton

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        etApiId = view.findViewById(R.id.et_api_id)
        etApiHash = view.findViewById(R.id.et_api_hash)
        etPhone = view.findViewById(R.id.et_phone)
        etPassword = view.findViewById(R.id.et_password)
        tvStatus = view.findViewById(R.id.tv_connect_status)
        btnAuto = view.findViewById(R.id.btn_auto_api)
        btnSave = view.findViewById(R.id.btn_save_keys)

        etApiId.setText(Prefs.apiId)
        etApiHash.setText(Prefs.apiHash)
        etPhone.setText(Prefs.phone)
        etPassword.setText(Prefs.password2fa)

        btnSave.setOnClickListener { saveKeys() }
        btnAuto.setOnClickListener { autoApi() }
    }

    private fun saveKeys() {
        val apiId = etApiId.text?.toString()?.trim().orEmpty()
        val apiHash = etApiHash.text?.toString()?.trim().orEmpty()
        val phone = etPhone.text?.toString()?.trim().orEmpty().replace(" ", "").replace("-", "")
        val password = etPassword.text?.toString()?.trim().orEmpty()

        if (apiId.isEmpty() || !Regex("^[0-9a-fA-F]{32}$").matches(apiHash)) {
            setStatus(getString(R.string.toast_bad_hash), false)
            toast(getString(R.string.toast_bad_hash))
            return
        }
        val cleanPhone = phone.replace(" ", "").replace("-", "")
        if (cleanPhone.isNotEmpty() && !Regex("^\\+\\d{7,15}$").matches(cleanPhone)) {
            setStatus(getString(R.string.toast_bad_phone), false)
            toast(getString(R.string.toast_bad_phone))
            return
        }

        Prefs.apiId = apiId
        Prefs.apiHash = apiHash
        Prefs.phone = phone
        Prefs.password2fa = password

        val context = requireContext().applicationContext
        setBusy(true, "")
        viewLifecycleOwner.lifecycleScope.launch {
            val result: JSONObject? = withContext(Dispatchers.IO) {
                PythonBridge.ensureStarted(context)
                PythonBridge.saveAccount(apiId, apiHash, phone, password)
            }
            val ok = result?.optBoolean("ok") ?: false
            if (ok) {
                setBusy(false, "")
                setStatus(getString(R.string.toast_saved), true)
            } else {
                val error = result?.optString("error").orEmpty().ifBlank { "config.txt" }
                setBusy(false, "")
                setStatus(getString(R.string.toast_error_fmt, error), false)
            }
        }
    }

    private fun autoApi() {
        val phone = etPhone.text?.toString()?.trim().orEmpty().replace(" ", "").replace("-", "")
        if (phone.isEmpty()) {
            toast(getString(R.string.toast_need_phone))
            return
        }
        if (!Regex("^\\+\\d{7,15}$").matches(phone)) {
            setStatus(getString(R.string.toast_bad_phone), false)
            toast(getString(R.string.toast_bad_phone))
            return
        }

        val context = requireContext().applicationContext
        setBusy(true, getString(R.string.toast_auto_api_started))

        PythonBridge.requestAutoApi(context, phone) { json ->
            val activity = activity
            if (activity == null) return@requestAutoApi
            activity.runOnUiThread {
                if (!isAdded) return@runOnUiThread
                setBusy(false, "")
                if (json.optBoolean("ok")) {
                    val apiId = json.optInt("api_id")
                    val apiHash = json.optString("api_hash")
                    val returnedPhone = json.optString("phone").ifBlank { phone }
                    etApiId.setText(apiId.toString())
                    etApiHash.setText(apiHash)
                    etPhone.setText(returnedPhone)
                    Prefs.apiId = apiId.toString()
                    Prefs.apiHash = apiHash
                    Prefs.phone = returnedPhone
                    setStatus(getString(R.string.toast_auto_api_ok, apiId.toString()), true)
                } else {
                    val error = json.optString("error").ifBlank { "my.telegram.org" }
                    setStatus(getString(R.string.toast_error_fmt, error), false)
                }
            }
        }
    }

    private fun setBusy(busy: Boolean, message: String) {
        btnAuto.isEnabled = !busy
        btnSave.isEnabled = !busy
        when {
            message.isNotEmpty() -> setStatus(message, null)
            busy -> setStatus("…", null)
        }
    }

    /** Зелёный — успех, красный — ошибка, серый — «в процессе»/подсказка. */
    private fun setStatus(message: String, ok: Boolean?) {
        if (!isAdded) return
        tvStatus.text = message
        val color = when (ok) {
            true -> R.color.mint
            false -> R.color.red
            null -> R.color.on_surface_muted
        }
        tvStatus.setTextColor(ContextCompat.getColor(requireContext(), color))
    }

    private fun toast(message: String) {
        Toast.makeText(requireContext(), message, Toast.LENGTH_LONG).show()
    }
}
