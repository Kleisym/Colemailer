package com.colemailer.app

import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import android.provider.Settings
import androidx.core.content.FileProvider
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL

/**
 * Обновление приложения прямо с GitHub Releases.
 *
 * Проверка и скачивание идут в фоновом потоке. Установка:
 *  - есть root — `pm install -r` через su, полностью молча;
 *  - нет root — системный установщик (Android требует подтверждение,
 *    обойти это без прав суперпользователя нельзя).
 */
object UpdateManager {

    private const val API_URL = "https://api.github.com/repos/Kleisym/Colemailer/releases/latest"
    private const val APK_NAME = "colemailer-update.apk"

    data class Info(val version: String, val apkUrl: String, val pageUrl: String)

    fun currentVersion(context: Context): String = try {
        context.packageManager.getPackageInfo(context.packageName, 0).versionName ?: "0"
    } catch (e: Exception) {
        "0"
    }

    fun fetchLatest(): Info? {
        var connection: HttpURLConnection? = null
        return try {
            connection = (URL(API_URL).openConnection() as HttpURLConnection).apply {
                connectTimeout = 15000
                readTimeout = 20000
                setRequestProperty("Accept", "application/vnd.github+json")
                setRequestProperty("User-Agent", "Colemailer-Android")
            }
            if (connection.responseCode != 200) return null
            val body = connection.inputStream.bufferedReader().use { it.readText() }
            val json = JSONObject(body)
            val tag = json.optString("tag_name").removePrefix("v")
            val page = json.optString("html_url")
            val assets = json.optJSONArray("assets") ?: return null
            var apk = ""
            for (i in 0 until assets.length()) {
                val item = assets.optJSONObject(i) ?: continue
                if (item.optString("name").endsWith(".apk", ignoreCase = true)) {
                    apk = item.optString("browser_download_url")
                    break
                }
            }
            if (tag.isBlank() || apk.isBlank()) null else Info(tag, apk, page)
        } catch (e: Exception) {
            null
        } finally {
            connection?.disconnect()
        }
    }

    fun isNewer(latest: String, current: String): Boolean {
        fun parts(value: String): List<Int> =
            value.trim().removePrefix("v").split('.', '-', '+')
                .map { it.toIntOrNull() ?: 0 }
        val a = parts(latest)
        val b = parts(current)
        for (i in 0 until maxOf(a.size, b.size)) {
            val x = a.getOrElse(i) { 0 }
            val y = b.getOrElse(i) { 0 }
            if (x != y) return x > y
        }
        return false
    }

    /** Скачать APK в cache/updates. Возвращает файл или null. */
    fun download(context: Context, info: Info): File? {
        var connection: HttpURLConnection? = null
        return try {
            val dir = File(context.cacheDir, "updates").apply { mkdirs() }
            val target = File(dir, APK_NAME)
            connection = (URL(info.apkUrl).openConnection() as HttpURLConnection).apply {
                connectTimeout = 20000
                readTimeout = 60000
                instanceFollowRedirects = true
                setRequestProperty("User-Agent", "Colemailer-Android")
            }
            if (connection.responseCode !in 200..299) return null
            connection.inputStream.use { input ->
                target.outputStream().use { output -> input.copyTo(output) }
            }
            if (target.length() < 1_000_000L) {
                target.delete()
                return null
            }
            target
        } catch (e: Exception) {
            null
        } finally {
            connection?.disconnect()
        }
    }

    /**
     * Установить скачанный APK.
     * @return "root" — установлено молча, "prompt" — открыт установщик,
     *         "permission" — нужно разрешить установку из этого источника,
     *         иначе текст ошибки.
     */
    fun install(context: Context, file: File): String {
        if (RootShell.isAvailable()) {
            val result = RootShell.installApk(file)
            if (result.ok) return "root"
        }
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O &&
            !context.packageManager.canRequestPackageInstalls()
        ) {
            runCatching {
                context.startActivity(
                    Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES)
                        .setData(Uri.parse("package:" + context.packageName))
                        .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                )
            }
            return "permission"
        }
        val uri = FileProvider.getUriForFile(context, context.packageName + ".files", file)
        val intent = Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, "application/vnd.android.package-archive")
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION)
        return try {
            context.startActivity(intent)
            "prompt"
        } catch (e: Exception) {
            "нет установщика APK: " + (e.message ?: e.javaClass.simpleName)
        }
    }
}
