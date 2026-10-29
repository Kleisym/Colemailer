package com.colemailer.app

import android.content.Context
import android.content.SharedPreferences

/**
 * Единственный владелец обычных SharedPreferences.
 *
 * Секретов здесь нет: api_hash и пароль 2FA лежат в [SecretStore] (Android
 * Keystore). Обычные ключи читает и Kotlin, и Python-мост через config.txt.
 */
object Prefs {
    private const val NAME = "colemailer_prefs"
    private const val SECURE_NAME = "colemailer_secure"

    private lateinit var sp: SharedPreferences
    private lateinit var secure: SharedPreferences

    fun init(context: Context) {
        sp = context.getSharedPreferences(NAME, Context.MODE_PRIVATE)
        secure = context.getSharedPreferences(SECURE_NAME, Context.MODE_PRIVATE)
    }

    internal fun securePrefs(): SharedPreferences = secure

    var serviceEnabled: Boolean
        get() = sp.getBoolean("service_enabled", false)
        set(value) = sp.edit().putBoolean("service_enabled", value).apply()

    var phone: String
        get() = sp.getString("phone", "") ?: ""
        set(value) = sp.edit().putString("phone", value).apply()

    /** Имя аккаунта из последнего успешного входа (@username или имя). */
    var user: String
        get() = sp.getString("user", "") ?: ""
        set(value) = sp.edit().putString("user", value).apply()

    /** Когда сервис последний раз реально подключился — для uptime. */
    var sessionStartedAt: Long
        get() = sp.getLong("session_started_at", 0L)
        set(value) = sp.edit().putLong("session_started_at", value).apply()

    /** Сохранённый статус: живёт дольше процесса, чтобы UI не врал. */
    var lastStatus: String
        get() = sp.getString("last_status", "") ?: ""
        set(value) = sp.edit().putString("last_status", value).apply()

    /** Отметка «автозапуск в OEM-настройках включён»: прочитать его нельзя. */
    var oemAutostartConfirmed: Boolean
        get() = sp.getBoolean("oem_autostart_confirmed", false)
        set(value) = sp.edit().putBoolean("oem_autostart_confirmed", value).apply()

    var onboardingDone: Boolean
        get() = sp.getBoolean("onboarding_done", false)
        set(value) = sp.edit().putBoolean("onboarding_done", value).apply()

    /** Автообновление: проверка релизов GitHub, на root — тихая установка. */
    var autoUpdate: Boolean
        get() = sp.getBoolean("auto_update", true)
        set(value) = sp.edit().putBoolean("auto_update", value).apply()

    var lastUpdateCheck: Long
        get() = sp.getLong("last_update_check", 0L)
        set(value) = sp.edit().putLong("last_update_check", value).apply()

    // --- секреты (Android Keystore) ---------------------------------------
    var apiId: String
        get() = SecretStore.get("api_id", "") ?: ""
        set(value) = SecretStore.put("api_id", value)

    var apiHash: String
        get() = SecretStore.get("api_hash", "") ?: ""
        set(value) = SecretStore.put("api_hash", value)

    var password2fa: String
        get() = SecretStore.get("password_2fa", "") ?: ""
        set(value) = SecretStore.put("password_2fa", value)

    fun hasCredentials(): Boolean = apiId.isNotBlank() && apiHash.isNotBlank()

    fun clearAccount() {
        apiId = ""
        apiHash = ""
        password2fa = ""
        phone = ""
        user = ""
    }
}
