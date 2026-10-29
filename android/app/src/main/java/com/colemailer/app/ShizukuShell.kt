package com.colemailer.app

import android.content.Context
import android.content.pm.PackageManager
import rikka.shizuku.Shizuku
import java.util.concurrent.TimeUnit

/**
 * Права через Shizuku (ADB/root-посредник).
 *
 * Root в APK вшить нельзя: su — это ядро и загрузчик конкретного телефона.
 * Shizuku даёт тот же практический результат без root: пользователь один раз
 * запускает Shizuku (по ADB или на рутованном телефоне), после чего приложение
 * выполняет pm grant/appops от имени shell и получает все нужные разрешения.
 */
object ShizukuShell {

    const val REQUEST_CODE = 0x5A17

    fun isBinderAlive(): Boolean = try {
        Shizuku.pingBinder()
    } catch (e: Throwable) {
        false
    }

    fun hasPermission(): Boolean {
        return try {
            !Shizuku.isPreV11() && Shizuku.checkSelfPermission() == PackageManager.PERMISSION_GRANTED
        } catch (e: Throwable) {
            false
        }
    }

    fun requestPermission(): Boolean {
        return try {
            if (!isBinderAlive()) return false
            if (Shizuku.isPreV11()) return false
            Shizuku.requestPermission(REQUEST_CODE)
            true
        } catch (e: Throwable) {
            false
        }
    }

    fun grantAll(context: Context): RootShell.Result {
        if (!isBinderAlive()) {
            return RootShell.Result(false, false, "Shizuku не запущен")
        }
        if (!hasPermission()) {
            return RootShell.Result(false, false, "нет разрешения Shizuku")
        }
        val log = StringBuilder()
        var any = false
        for (command in RootShell.grantCommands(context.packageName)) {
            val result = exec(command)
            if (result == null) {
                log.append("skip ").append(command).append('\n')
                continue
            }
            val ok = result.first == 0
            any = any || ok
            log.append(if (ok) "ok   " else "skip ").append(command).append('\n')
            if (!ok && result.second.isNotBlank()) {
                log.append("     ").append(result.second.lineSequence().first()).append('\n')
            }
        }
        return RootShell.Result(available = true, ok = any, log = log.toString().trim())
    }

    private fun exec(command: String): Pair<Int, String>? {
        return try {
            // В 13.1.5 newProcess приватный; он всё ещё есть в классе и
            // прекрасно работает через reflection. Это только запуск shell
            // от имени Shizuku, никакого скрытого API Android.
            val method = Shizuku::class.java.getDeclaredMethod(
                "newProcess",
                Array<String>::class.java,
                Array<String>::class.java,
                String::class.java
            )
            method.isAccessible = true
            val process = method.invoke(null, arrayOf("sh", "-c", command), null, null) as Process
            val output = process.inputStream.bufferedReader().use { it.readText() }
            val finished = process.waitFor(8, TimeUnit.SECONDS)
            if (!finished) {
                process.destroyForcibly()
                Pair(-1, output)
            } else {
                Pair(process.exitValue(), output.trim())
            }
        } catch (e: Throwable) {
            null
        }
    }
}
