package com.colemailer.app

import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

/**
 * Секреты (api_hash, пароль 2FA) шифруются ключом Android Keystore.
 *
 * Раньше они лежали открытым текстом в SharedPreferences: чтение при root,
 * ADB-дампе или из бэкапа отдавало аккаунт целиком.
 */
object SecretStore {
    private const val KEY_ALIAS = "colemailer_master"
    private const val TRANSFORMATION = "AES/GCM/NoPadding"
    private const val TAG_BITS = 128

    private fun key(): SecretKey {
        val keyStore = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        val entry = keyStore.getEntry(KEY_ALIAS, null)
        if (entry is KeyStore.SecretKeyEntry) {
            return entry.secretKey
        }
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        val spec = KeyGenParameterSpec.Builder(
            KEY_ALIAS,
            KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT
        )
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
            .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
            .setKeySize(256)
            .build()
        generator.init(spec)
        return generator.generateKey()
    }

    fun put(name: String, value: String) {
        try {
            if (value.isEmpty()) {
                remove(name)
                return
            }
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.ENCRYPT_MODE, key())
            val encrypted = cipher.doFinal(value.toByteArray(Charsets.UTF_8))
            val blob = Base64.encodeToString(cipher.iv, Base64.NO_WRAP) + ":" +
                Base64.encodeToString(encrypted, Base64.NO_WRAP)
            Prefs.securePrefs().edit().putString(name, blob).apply()
        } catch (e: Exception) {
            // Keystore сломан (бывает после сброса ключей): лучше потерять
            // секрет, чем уронить экран. Пользователь введёт данные заново.
            Prefs.securePrefs().edit().remove(name).apply()
        }
    }

    fun get(name: String, default: String? = null): String? {
        val blob = Prefs.securePrefs().getString(name, null) ?: return default
        return try {
            val parts = blob.split(":")
            if (parts.size != 2) return default
            val iv = Base64.decode(parts[0], Base64.NO_WRAP)
            val encrypted = Base64.decode(parts[1], Base64.NO_WRAP)
            val cipher = Cipher.getInstance(TRANSFORMATION)
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(TAG_BITS, iv))
            String(cipher.doFinal(encrypted), Charsets.UTF_8)
        } catch (e: Exception) {
            default
        }
    }

    fun remove(name: String) {
        Prefs.securePrefs().edit().remove(name).apply()
    }
}
