package com.colemailer.app

import android.content.Context
import android.content.Intent
import android.content.pm.PackageInfo
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.os.Handler
import android.os.Looper
import android.provider.Settings
import androidx.core.content.FileProvider
import org.json.JSONObject
import java.io.File
import java.net.HttpURLConnection
import java.net.URL
import java.security.MessageDigest
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.zip.ZipFile

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

    data class Info(val version: String, val apkUrl: String, val pageUrl: String, val size: Long = 0, val sha256: String? = null)

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
            var size = 0L
            var sha256: String? = null
            for (i in 0 until assets.length()) {
                val item = assets.optJSONObject(i) ?: continue
                if (item.optString("name").endsWith(".apk", ignoreCase = true)) {
                    apk = item.optString("browser_download_url")
                    size = item.optLong("size", 0L)
                    val digest = item.optString("digest")
                    sha256 = digest.removePrefix("sha256:").takeIf { digest.startsWith("sha256:") && it.matches(Regex("[a-fA-F0-9]{64}")) }
                    break
                }
            }
            if (!tag.matches(Regex("[0-9]+(\\.[0-9]+)*")) || apk.isBlank()) null else Info(tag, apk, page, size, sha256)
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

    @Suppress("DEPRECATION")
    private fun signatureSet(info: PackageInfo): Set<String> =
        info.signatures?.map { it.toByteArray().joinToString("") { b -> "%02x".format(b.toInt() and 0xff) } }?.toSet() ?: emptySet()

    @Suppress("DEPRECATION")
    private fun validApk(context: Context, file: File, info: Info): Boolean {
        if (!file.isFile || file.length() < 1_000_000L || (info.size > 0 && file.length() != info.size)) return false
        return try {
            val expected = info.sha256
            if (expected != null) {
                val digest = MessageDigest.getInstance("SHA-256")
                file.inputStream().use { input ->
                    val buffer = ByteArray(64 * 1024)
                    while (true) {
                        val count = input.read(buffer)
                        if (count < 0) break
                        digest.update(buffer, 0, count)
                    }
                }
                val actual = digest.digest().joinToString("") { "%02x".format(it.toInt() and 0xff) }
                if (!actual.equals(expected, ignoreCase = true)) return false
            }
            val nativeAbis = ZipFile(file).use { zip ->
                zip.entries().asSequence().mapNotNull { entry ->
                    val parts = entry.name.split('/')
                    if (parts.size >= 3 && parts[0] == "lib" && entry.name.endsWith(".so")) parts[1] else null
                }.toSet()
            }
            if (nativeAbis.isNotEmpty() && Build.SUPPORTED_ABIS.none { it in nativeAbis }) return false
            val pm = context.packageManager
            val archive = pm.getPackageArchiveInfo(file.absolutePath, PackageManager.GET_SIGNATURES) ?: return false
            val installed = pm.getPackageInfo(context.packageName, PackageManager.GET_SIGNATURES)
            val oldCode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) installed.longVersionCode else installed.versionCode.toLong()
            val newCode = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) archive.longVersionCode else archive.versionCode.toLong()
            val oldSigners = signatureSet(installed)
            archive.packageName == context.packageName && archive.versionName == info.version &&
                newCode > oldCode && oldSigners.isNotEmpty() && oldSigners == signatureSet(archive)
        } catch (_: Exception) {
            false
        }
    }

    /** Use only complete, verified cached APKs. */
    @Synchronized
    fun cachedFile(context: Context, info: Info): File? {
        if (!info.version.matches(Regex("[0-9]+(\\.[0-9]+)*"))) return null
        val file = File(context.cacheDir, "updates/colemailer-${info.version}.apk")
        if (validApk(context, file, info)) return file
        file.delete()
        return null
    }

    /** Download into a temporary file and publish it only after validation. */
    @Synchronized
    fun download(context: Context, info: Info): File? {
        cachedFile(context, info)?.let { return it }
        if (!info.version.matches(Regex("[0-9]+(\\.[0-9]+)*"))) return null
        val dir = File(context.cacheDir, "updates")
        if (!dir.exists() && !dir.mkdirs()) return null
        val target = File(dir, "colemailer-${info.version}.apk")
        var connection: HttpURLConnection? = null
        return try {
            connection = (URL(info.apkUrl).openConnection() as HttpURLConnection).apply {
                connectTimeout = 20000
                readTimeout = 60000
                instanceFollowRedirects = true
                setRequestProperty("User-Agent", "Colemailer-Android")
            }
            if (connection.responseCode !in 200..299) return null
            val expectedLength = connection.contentLengthLong
            connection.inputStream.use { input ->
                UpdateFileTransfer.copy(input, target, expectedLength, info.size, info.sha256) { file ->
                    validApk(context, file, info)
                }
            }
        } catch (_: Exception) {
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
            Handler(Looper.getMainLooper()).post {
                runCatching {
                    context.startActivity(
                        Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES)
                            .setData(Uri.parse("package:" + context.packageName))
                            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
                    )
                }
            }
            return "permission"
        }
        val uri = FileProvider.getUriForFile(context, context.packageName + ".files", file)
        val intent = Intent(Intent.ACTION_VIEW)
            .setDataAndType(uri, "application/vnd.android.package-archive")
            .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_GRANT_READ_URI_PERMISSION)
        if (Looper.myLooper() == Looper.getMainLooper()) {
            return try {
                context.startActivity(intent)
                "prompt"
            } catch (e: Exception) {
                "нет установщика APK: " + (e.message ?: e.javaClass.simpleName)
            }
        }
        val done = CountDownLatch(1)
        var result = "не удалось открыть установщик APK"
        if (!Handler(Looper.getMainLooper()).post {
            try {
                context.startActivity(intent)
                result = "prompt"
            } catch (e: Exception) {
                result = "нет установщика APK: " + (e.message ?: e.javaClass.simpleName)
            } finally {
                done.countDown()
            }
        }) return result
        return if (done.await(10, TimeUnit.SECONDS)) result else "установщик не ответил"
    }
}
