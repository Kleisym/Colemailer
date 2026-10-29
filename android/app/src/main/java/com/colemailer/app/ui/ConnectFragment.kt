package com.colemailer.app.ui

import android.os.Bundle
import android.text.Editable
import android.text.TextWatcher
import android.view.View
import android.widget.AdapterView
import android.widget.ArrayAdapter
import android.widget.Spinner
import android.widget.TextView
import android.widget.Toast
import androidx.core.content.ContextCompat
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import com.colemailer.app.Account
import com.colemailer.app.AccountStore
import com.colemailer.app.Prefs
import com.colemailer.app.PythonBridge
import com.colemailer.app.R
import com.google.android.material.button.MaterialButton
import com.google.android.material.textfield.TextInputEditText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.util.UUID

/**
 * Подключение: api_id/api_hash/телефон/2FA, ручное сохранение и авто-получение
 * ключей через my.telegram.org (код подтверждения приходит в Telegram).
 *
 * Аккаунтов может быть несколько: список сверху, переключение подставляет
 * ключи выбранного, сессии лежат отдельными файлами.
 */
class ConnectFragment : Fragment(R.layout.fragment_connect) {

    private lateinit var etApiId: TextInputEditText
    private lateinit var etApiHash: TextInputEditText
    private lateinit var etPhone: TextInputEditText
    private lateinit var etPassword: TextInputEditText
    private lateinit var tvStatus: TextView
    private lateinit var btnAuto: MaterialButton
    private lateinit var btnSave: MaterialButton
    private lateinit var spinner: Spinner

    private lateinit var accounts: MutableList<Account>
    private var currentId: String = ""
    private var filling = false

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        etApiId = view.findViewById(R.id.et_api_id)
        etApiHash = view.findViewById(R.id.et_api_hash)
        etPhone = view.findViewById(R.id.et_phone)
        etPassword = view.findViewById(R.id.et_password)
        tvStatus = view.findViewById(R.id.tv_connect_status)
        btnAuto = view.findViewById(R.id.btn_auto_api)
        btnSave = view.findViewById(R.id.btn_save_keys)
        spinner = view.findViewById(R.id.spinner_accounts)

        accounts = AccountStore.load(requireContext())
        refreshSpinner()
        val active = AccountStore.active(requireContext())
        if (active != null) {
            currentId = active.id
            spinner.setSelection(accounts.indexOfFirst { it.id == active.id }.coerceAtLeast(0))
            fill(active)
        } else {
            fillFromPrefs()
        }

        spinner.onItemSelectedListener = object : AdapterView.OnItemSelectedListener {
            override fun onItemSelected(parent: AdapterView<*>?, view: View?, position: Int, id: Long) {
                if (filling) return
                val selected = accounts.getOrNull(position) ?: return
                if (selected.id == currentId) return
                saveCurrent()
                currentId = selected.id
                AccountStore.select(requireContext(), selected)
                fill(selected)
            }

            override fun onNothingSelected(parent: AdapterView<*>?) = Unit
        }

        view.findViewById<MaterialButton>(R.id.btn_add_account).setOnClickListener { addAccount() }
        view.findViewById<MaterialButton>(R.id.btn_delete_account).setOnClickListener { deleteAccount() }
        btnSave.setOnClickListener { saveKeys() }
        btnAuto.setOnClickListener { autoApi() }
        setupWatchers()
    }

    /**
     * Сохраняем поля сразу при вводе, а не только по onPause. Иначе при
     * переключении вкладок/уходе из приложения последние символы (номер,
     * api_hash) терялись, если onPause не успевал сработать.
     */
    private fun setupWatchers() {
        val watcher = object : TextWatcher {
            override fun beforeTextChanged(s: CharSequence?, start: Int, count: Int, after: Int) = Unit
            override fun onTextChanged(s: CharSequence?, start: Int, before: Int, count: Int) = Unit
            override fun afterTextChanged(s: Editable?) {
                if (!filling) saveCurrent()
            }
        }
        etApiId.addTextChangedListener(watcher)
        etApiHash.addTextChangedListener(watcher)
        etPhone.addTextChangedListener(watcher)
        etPassword.addTextChangedListener(watcher)
    }

    override fun onPause() {
        saveCurrent()
        super.onPause()
    }

    override fun onStop() {
        saveCurrent()
        super.onStop()
    }

    private fun refreshSpinner() {
        val adapter = ArrayAdapter(
            requireContext(),
            android.R.layout.simple_spinner_item,
            accounts.map { it.name }
        )
        adapter.setDropDownViewResource(android.R.layout.simple_spinner_dropdown_item)
        spinner.adapter = adapter
    }

    private fun fill(account: Account) {
        filling = true
        etApiId.setText(account.apiId)
        etApiHash.setText(account.apiHash)
        etPhone.setText(account.phone)
        etPassword.setText(account.password)
        filling = false
        AccountStore.select(requireContext(), account)
        tvStatus.text = getString(R.string.account_selected, account.name)
        tvStatus.setTextColor(ContextCompat.getColor(requireContext(), R.color.on_surface_muted))
    }

    private fun fillFromPrefs() {
        filling = true
        etApiId.setText(Prefs.apiId)
        etApiHash.setText(Prefs.apiHash)
        etPhone.setText(Prefs.phone)
        etPassword.setText(Prefs.password2fa)
        filling = false
    }

    /** Сохранить поля формы в текущий (или новый) аккаунт. */
    private fun saveCurrent() {
        if (!isAdded) return
        val apiId = etApiId.text?.toString()?.trim().orEmpty()
        val apiHash = etApiHash.text?.toString()?.trim().orEmpty()
        val phone = etPhone.text?.toString()?.trim().orEmpty()
        val password = etPassword.text?.toString()?.trim().orEmpty()
        // Сначала Prefs: даже если файл аккаунтов почему-то не запишется,
        // номер и ключи не пропадут при переключении вкладки.
        Prefs.apiId = apiId
        Prefs.apiHash = apiHash
        Prefs.phone = phone
        Prefs.password2fa = password
        val index = accounts.indexOfFirst { it.id == currentId }
        if (index >= 0) {
            accounts[index] = accounts[index].copy(
                apiId = apiId, apiHash = apiHash, phone = phone, password = password
            )
        } else if (apiId.isNotBlank() || phone.isNotBlank()) {
            val account = Account(
                id = UUID.randomUUID().toString(),
                name = getString(R.string.account_new_name, accounts.size + 1),
                apiId = apiId, apiHash = apiHash, phone = phone, password = password
            )
            accounts.add(account)
            currentId = account.id
        } else {
            return
        }
        AccountStore.save(requireContext(), accounts)
        accounts.firstOrNull { it.id == currentId }?.let { AccountStore.select(requireContext(), it) }
    }

    private fun addAccount() {
        saveCurrent()
        val account = Account(
            id = UUID.randomUUID().toString(),
            name = getString(R.string.account_new_name, accounts.size + 1),
            apiId = etApiId.text?.toString()?.trim().orEmpty(),
            apiHash = etApiHash.text?.toString()?.trim().orEmpty(),
            phone = etPhone.text?.toString()?.trim().orEmpty(),
            password = etPassword.text?.toString()?.trim().orEmpty()
        )
        accounts.add(account)
        currentId = account.id
        AccountStore.save(requireContext(), accounts)
        AccountStore.select(requireContext(), account)
        refreshSpinner()
        filling = true
        spinner.setSelection(accounts.lastIndex)
        filling = false
        fill(account)
        toast(getString(R.string.account_added))
    }

    private fun deleteAccount() {
        if (accounts.size <= 1) {
            toast(getString(R.string.account_last))
            return
        }
        val index = accounts.indexOfFirst { it.id == currentId }
        if (index >= 0) accounts.removeAt(index)
        currentId = accounts.firstOrNull()?.id.orEmpty()
        AccountStore.save(requireContext(), accounts)
        refreshSpinner()
        filling = true
        spinner.setSelection(0)
        filling = false
        accounts.firstOrNull()?.let {
            AccountStore.select(requireContext(), it)
            fill(it)
        } ?: fillFromPrefs()
        toast(getString(R.string.account_deleted))
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
        saveCurrent()

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
                    saveCurrent()
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
