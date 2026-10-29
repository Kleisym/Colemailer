package com.colemailer.app

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.util.UUID

/**
 * Сохранённые аккаунты. Файл лежит в приватном каталоге приложения и
 * недоступен другим приложениям; входы хранятся в отдельных .session-файлах.
 *
 * Аккаунтов может быть сколько угодно: в списке выбирается активный, его
 * ключи подставляются в форму и уходят в BotService. Переключение не требует
 * повторного входа — сессия каждого аккаунта уже лежит на диске.
 */
data class Account(
    val id: String,
    val name: String,
    val apiId: String,
    val apiHash: String,
    val phone: String,
    val password: String
) {
    fun toJson(): JSONObject = JSONObject().apply {
        put("id", id)
        put("name", name)
        put("api_id", apiId)
        put("api_hash", apiHash)
        put("phone", phone)
        put("password", password)
    }

    companion object {
        fun fromJson(json: JSONObject): Account = Account(
            id = json.optString("id").ifBlank { UUID.randomUUID().toString() },
            name = json.optString("name").ifBlank { "Аккаунт" },
            apiId = json.optString("api_id"),
            apiHash = json.optString("api_hash"),
            phone = json.optString("phone"),
            password = json.optString("password")
        )
    }
}

object AccountStore {

    private const val FILE_NAME = "accounts.json"

    private fun file(context: Context): File = File(context.filesDir, FILE_NAME)

    fun load(context: Context): MutableList<Account> {
        val result = mutableListOf<Account>()
        val f = file(context)
        if (!f.exists()) return ensure(context, result)
        try {
            val array = JSONArray(f.readText(Charsets.UTF_8))
            for (i in 0 until array.length()) {
                array.optJSONObject(i)?.let { result.add(Account.fromJson(it)) }
            }
        } catch (e: Exception) {
            // Битый файл не должен блокировать запуск: начинаем с одного
            // аккаунта из Prefs (если он там есть).
        }
        return ensure(context, result)
    }

    private fun ensure(context: Context, list: MutableList<Account>): MutableList<Account> {
        if (list.isEmpty()) {
            // Первый запуск: аккаунт №1 создаётся сразу, даже с пустыми
            // полями. Иначе форма выглядит как «аккаунта нет», а введённые
            // данные некуда сохранять.
            val account = Account(
                id = UUID.randomUUID().toString(),
                name = "Аккаунт 1",
                apiId = Prefs.apiId,
                apiHash = Prefs.apiHash,
                phone = Prefs.phone,
                password = Prefs.password2fa
            )
            list.add(account)
            Prefs.activeAccountId = account.id
            save(context, list)
        }
        return list
    }

    fun save(context: Context, accounts: List<Account>) {
        try {
            val array = JSONArray()
            accounts.forEach { array.put(it.toJson()) }
            file(context).writeText(array.toString(), Charsets.UTF_8)
        } catch (e: Exception) {
            // Приватный файл: если запись не удалась, работаем с тем, что в Prefs.
        }
    }

    fun active(context: Context): Account? {
        val accounts = load(context)
        if (accounts.isEmpty()) return null
        return accounts.firstOrNull { it.id == Prefs.activeAccountId } ?: accounts.first()
    }

    fun select(context: Context, account: Account) {
        Prefs.activeAccountId = account.id
        Prefs.apiId = account.apiId
        Prefs.apiHash = account.apiHash
        Prefs.phone = account.phone
        Prefs.password2fa = account.password
    }
}
