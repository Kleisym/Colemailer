package com.colemailer.app

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.os.PowerManager

/**
 * Один сетевой callback на приложение.
 *
 * Смена сети или возврат связи — единственный законный повод «пнуть» бота:
 * после Doze или переключения Wi-Fi <-> LTE сокет Telethon остаётся
 * полумёртвым, и is_connected() продолжает врать, что всё хорошо.
 */
object NetMonitor {
    private var callback: ConnectivityManager.NetworkCallback? = null

    fun register(context: Context, onChange: (Boolean) -> Unit) {
        if (callback != null) return
        val manager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
            ?: return
        val cb = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) {
                onChange(true)
            }

            override fun onLost(network: Network) {
                onChange(false)
            }
        }
        runCatching { manager.registerDefaultNetworkCallback(cb) }
            .onSuccess { callback = cb }
    }

    fun unregister(context: Context) {
        val cb = callback ?: return
        callback = null
        val manager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
            ?: return
        runCatching { manager.unregisterNetworkCallback(cb) }
    }

    fun isOnline(context: Context): Boolean {
        val manager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
            ?: return false
        val network = manager.activeNetwork ?: return false
        val caps = manager.getNetworkCapabilities(network) ?: return false
        return caps.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET)
    }

    fun label(context: Context): String {
        val manager = context.getSystemService(Context.CONNECTIVITY_SERVICE) as? ConnectivityManager
            ?: return ""
        val network = manager.activeNetwork ?: return "нет сети"
        val caps = manager.getNetworkCapabilities(network) ?: return "нет сети"
        return when {
            caps.hasTransport(NetworkCapabilities.TRANSPORT_WIFI) -> "Wi-Fi"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_CELLULAR) -> "моб. сеть"
            caps.hasTransport(NetworkCapabilities.TRANSPORT_ETHERNET) -> "Ethernet"
            else -> "сеть есть"
        }
    }

    /**
     * CPU будим только на время сетевой операции.
     *
     * Постоянный PARTIAL_WAKE_LOCK не спасает от Doze (сеть всё равно
     * отрезается), но гарантированно съедает батарею — поэтому его нет.
     */
    fun <T> withCpuWake(context: Context, timeoutMs: Long = 15_000L, block: () -> T): T {
        val manager = context.getSystemService(Context.POWER_SERVICE) as? PowerManager
        val lock = manager?.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Colemailer:net")
        lock?.setReferenceCounted(false)
        try {
            lock?.acquire(timeoutMs)
        } catch (e: Exception) {
            // без лока тоже работаем: FGS держит процесс живым
        }
        return try {
            block()
        } finally {
            try {
                if (lock != null && lock.isHeld) lock.release()
            } catch (e: Exception) {
                // ignore
            }
        }
    }
}
