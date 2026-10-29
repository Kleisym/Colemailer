package com.colemailer.app

import android.content.Context
import com.chaquo.python.PyObject
import com.chaquo.python.Python
import com.chaquo.python.android.AndroidPlatform
import org.json.JSONObject
import java.util.concurrent.Executors

/**
 * Обёртка над Python-мостом (bot_bridge.py).
 *
 * * Python стартует здесь, а не в Application: простой запуск экрана не должен
 *   тянуть интерпретатор.
 * * Всё блокирующее (start_bot, auto_api) идёт в своих потоках.
 * * «Дёргалки» (kick/stop) уходят в один фоновый поток: вызов из main thread
 *   мог бы упереться в GIL, пока Python занят HTTP-запросом.
 */
object PythonBridge {

    private val mainLock = Any()
    private val io = Executors.newSingleThreadExecutor { runnable ->
        Thread(runnable, "colemailer-bridge-io").apply { isDaemon = true }
    }
    private val callback = BotCallback()

    @Volatile
    private var thread: Thread? = null

    @Volatile
    private var module: PyObject? = null

    val isAlive: Boolean
        get() = thread?.isAlive == true

    /** Запустить бота (один раз; повторный вызов при живом потоке игнорируется). */
    fun start(context: Context) {
        val appContext = context.applicationContext
        synchronized(mainLock) {
            if (isAlive) return
            thread = Thread({
                try {
                    val bridge = bridgeModule(appContext)
                    bridge.callAttr("install_callback", callback)
                    bridge.callAttr(
                        "start_bot",
                        Prefs.apiId,
                        Prefs.apiHash,
                        Prefs.phone,
                        Prefs.password2fa,
                        appContext.filesDir.absolutePath,
                        callback
                    )
                } catch (t: Throwable) {
                    val message = t.message ?: t.javaClass.simpleName
                    StatusStore.set("Ошибка Python: $message", false, Level.ERROR)
                    LogStore.append("ERROR Ошибка Python: $message")
                } finally {
                    module = null
                }
            }, "colemailer-python").apply {
                isDaemon = true
                start()
            }
        }
    }

    /** Попросить Python немедленно проверить связь (смена сети, будильник, UI). */
    fun kick() {
        if (!isAlive) return
        io.execute {
            val bridge = module ?: return@execute
            runCatching { bridge.callAttr("kick") }
        }
    }

    /**
     * Поднять интерпретатор и загрузить модуль, не запуская бота.
     *
     * Нужно экранам «Подключение»/«Настройки»/«Рассылки»: они пишут и читают
     * config.txt через мост, даже если сервис ещё ни разу не стартовал.
     * Блокирующая — вызывать из Dispatchers.IO.
     */
    fun ensureStarted(context: Context) {
        runCatching { bridgeModule(context.applicationContext) }
    }

    fun stop() {
        io.execute {
            val bridge = module ?: return@execute
            runCatching { bridge.callAttr("stop_bot") }
        }
    }

    // --- чтение данных для UI (блокирующие: вызывать из Dispatchers.IO) ----

    fun state(): JSONObject? = callJson("get_state_json")

    fun tasks(): JSONObject? = callJson("get_tasks_json")

    fun settings(): JSONObject? = callJson("get_settings_json")

    fun logsSince(seq: Long): JSONObject? {
        return try {
            val bridge = module ?: return null
            JSONObject(bridge.callAttr("get_logs_since", seq).toString())
        } catch (t: Throwable) {
            null
        }
    }

    fun saveSettings(json: String): JSONObject? = callJson("save_settings_json", json)

    fun saveAccount(
        apiId: String,
        apiHash: String,
        phone: String,
        password2fa: String
    ): JSONObject? = callJson("save_account_json", apiId, apiHash, phone, password2fa)

    fun version(): String? {
        val bridge = module ?: return null
        return runCatching { bridge.callAttr("version").toString() }.getOrNull()
    }

    /**
     * Авто-получение api_id/api_hash через my.telegram.org.
     * Блокирующая операция в отдельном потоке; [onResult] придёт НЕ в main.
     */
    fun requestAutoApi(context: Context, phone: String, onResult: (JSONObject) -> Unit) {
        val appContext = context.applicationContext
        Thread({
            val result = try {
                val bridge = bridgeModule(appContext)
                bridge.callAttr("install_callback", callback)
                JSONObject(
                    bridge.callAttr("auto_api", phone, appContext.filesDir.absolutePath).toString()
                )
            } catch (t: Throwable) {
                JSONObject().apply {
                    put("ok", false)
                    put("error", t.message ?: t.javaClass.simpleName)
                }
            }
            onResult(result)
        }, "colemailer-auto-api").apply {
            isDaemon = true
            start()
        }
    }

    private fun bridgeModule(context: Context): PyObject {
        synchronized(mainLock) {
            if (!Python.isStarted()) {
                Python.start(AndroidPlatform(context))
            }
            val loaded = Python.getInstance().getModule("bot_bridge")
            module = loaded
            return loaded
        }
    }

    private fun callJson(method: String, vararg args: Any): JSONObject? {
        val bridge = module ?: return null
        return try {
            val raw = bridge.callAttr(method, *args)?.toString() ?: return null
            if (raw.isBlank() || raw == "None") null else JSONObject(raw)
        } catch (t: Throwable) {
            null
        }
    }
}
