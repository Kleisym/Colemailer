package com.colemailer.app

import android.content.Context
import java.util.concurrent.TimeUnit

/**
 * Необязательный root-режим.
 *
 * Если на устройстве есть su, приложение может выдать себе то, что обычный
 * пользователь делает руками в настройках: разрешение на уведомления,
 * освобождение от battery optimization, точные будильники, фоновую активность.
 * На телефоне без root эти команды просто не выполнятся — приложение продолжает
 * работать через обычные системные диалоги.
 */
object RootShell {

    data class Result(val available: Boolean, val ok: Boolean, val log: String)

    private data class CmdResult(val exit: Int, val output: String)

    fun isAvailable(): Boolean {
        val result = exec("id") ?: return false
        return result.exit == 0 && result.output.contains("uid=0")
    }

    /**
     * Выдать всё, что можно выдать через su. Возвращает человеческий лог:
     * какие команды прошли, какие нет (на разных прошивках набор appops разный).
     */
    fun grantAll(context: Context): Result {
        val pkg = context.packageName
        val commands = listOf(
            "pm grant $pkg android.permission.POST_NOTIFICATIONS",
            "appops set $pkg POST_NOTIFICATION allow",
            "appops set $pkg RUN_IN_BACKGROUND allow",
            "appops set $pkg RUN_ANY_IN_BACKGROUND allow",
            "appops set $pkg WAKE_LOCK allow",
            "appops set $pkg SCHEDULE_EXACT_ALARM allow",
            "appops set $pkg USE_EXACT_ALARM allow",
            "dumpsys deviceidle whitelist +$pkg",
            "cmd deviceidle whitelist +$pkg",
            "cmd appops set $pkg RUN_IN_BACKGROUND allow"
        )
        val log = StringBuilder()
        var any = false
        for (command in commands) {
            val result = exec(command)
            if (result == null) {
                log.append("нет su: ").append(command).append('\n')
                return Result(available = false, ok = false, log = log.toString().trim())
            }
            val ok = result.exit == 0
            any = any || ok
            log.append(if (ok) "ok   " else "skip ").append(command).append('\n')
            if (!ok && result.output.isNotBlank()) {
                log.append("     ").append(result.output.lineSequence().first()).append('\n')
            }
        }
        // Главный критерий — команды реально выполнились. Состояние
        // PowerManager может обновиться с задержкой, поэтому его не требуем.
        return Result(available = true, ok = any, log = log.toString().trim())
    }

    private fun exec(command: String, timeoutSeconds: Long = 8): CmdResult? {
        return try {
            val process = ProcessBuilder("su", "-c", command)
                .redirectErrorStream(true)
                .start()
            val output = process.inputStream.bufferedReader().use { it.readText() }
            val finished = process.waitFor(timeoutSeconds, TimeUnit.SECONDS)
            if (!finished) {
                process.destroyForcibly()
                CmdResult(-1, output)
            } else {
                CmdResult(process.exitValue(), output.trim())
            }
        } catch (e: Exception) {
            null
        }
    }
}
