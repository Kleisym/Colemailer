package com.colemailer.app.ui

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.core.view.updatePadding
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import com.colemailer.app.AuthQueue
import com.colemailer.app.Notifications
import com.colemailer.app.PermissionFlow
import com.colemailer.app.Prefs
import com.colemailer.app.R
import com.colemailer.app.RootShell
import com.colemailer.app.ShizukuShell
import com.colemailer.app.UpdateManager
import com.google.android.material.bottomnavigation.BottomNavigationView
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

/**
 * Хост: нижняя навигация + один фрагмент-экран.
 *
 * Navigation Component не используется намеренно: четыре экрана переключаются
 * replace'ом, состояние живёт в StatusStore/Prefs, а не во фрагментах.
 */
class MainActivity : AppCompatActivity() {

    companion object {
        private const val KEY_TAB = "tab"
    }

    lateinit var permissionFlow: PermissionFlow
        private set

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        // Android 15 рисует приложение под статус-баром; без явных inset'ов
        // заголовок уезжал под часы и выглядел «сломанным».
        WindowCompat.setDecorFitsSystemWindows(window, false)
        setContentView(R.layout.activity_main)
        applyWindowInsets()

        // Регистрация ActivityResultLauncher'ов должна произойти до STARTED.
        permissionFlow = PermissionFlow(this)

        val bottomNav = findViewById<BottomNavigationView>(R.id.bottom_nav)
        bottomNav.setOnItemSelectedListener { item ->
            when (item.itemId) {
                R.id.nav_home -> {
                    show(DashboardFragment())
                    true
                }

                R.id.nav_connect -> {
                    show(ConnectFragment())
                    true
                }

                R.id.nav_broadcasts -> {
                    show(BroadcastsFragment())
                    true
                }

                R.id.nav_settings -> {
                    show(SettingsFragment())
                    true
                }

                else -> false
            }
        }

        // При повороте восстанавливаем вкладку, иначе контейнер остаётся пустым:
        // listener не вызывается, пока не выбрать item программно.
        bottomNav.selectedItemId = savedInstanceState?.getInt(KEY_TAB, R.id.nav_home)
            ?: R.id.nav_home

        permissionFlow.startOnFirstLaunch()
        autoCheckUpdates()
        autoGrantIfPossible()
    }

    /**
     * Если Shizuku уже запущен и доступ выдан, права выдаются при каждом
     * старте сами — без кнопок. Если доступа нет, остаётся кнопка в настройках.
     */
    private fun autoGrantIfPossible() {
        if (!ShizukuShell.isBinderAlive() || !ShizukuShell.hasPermission()) return
        lifecycleScope.launch {
            runCatching { withContext(Dispatchers.IO) { ShizukuShell.grantAll(applicationContext) } }
        }
    }

    /**
     * Автообновление: раз в 6 часов проверяем GitHub Releases. На root
     * скачиваем и ставим молча; без root показываем уведомление, установку
     * подтверждает пользователь (ограничение Android).
     */
    private fun autoCheckUpdates() {
        if (!Prefs.autoUpdate) return
        val now = System.currentTimeMillis()
        if (now - Prefs.lastUpdateCheck < 6 * 60 * 60 * 1000L) return
        Prefs.lastUpdateCheck = now
        lifecycleScope.launch {
            val info = withContext(Dispatchers.IO) { UpdateManager.fetchLatest() } ?: return@launch
            val current = UpdateManager.currentVersion(applicationContext)
            if (!UpdateManager.isNewer(info.version, current)) return@launch
            val rooted = withContext(Dispatchers.IO) { RootShell.isAvailable() }
            if (!rooted) {
                Notifications.updateAvailable(applicationContext, info.version)
                return@launch
            }
            Toast.makeText(
                this@MainActivity,
                getString(R.string.update_downloading),
                Toast.LENGTH_SHORT
            ).show()
            val file = withContext(Dispatchers.IO) { UpdateManager.download(applicationContext, info) }
            if (file == null) {
                Notifications.updateAvailable(applicationContext, info.version)
                return@launch
            }
            val result = withContext(Dispatchers.IO) { UpdateManager.install(applicationContext, file) }
            val text = if (result == "root") {
                getString(R.string.update_installed_root)
            } else {
                getString(R.string.update_installer_opened)
            }
            Toast.makeText(this@MainActivity, text, Toast.LENGTH_LONG).show()
        }
    }

    private fun applyWindowInsets() {
        val root = findViewById<View>(R.id.root)
        val container = findViewById<View>(R.id.fragment_container)
        val nav = findViewById<View>(R.id.bottom_nav)
        WindowInsetsControllerCompat(window, window.decorView).isAppearanceLightStatusBars = false
        WindowInsetsControllerCompat(window, window.decorView).isAppearanceLightNavigationBars = false
        ViewCompat.setOnApplyWindowInsetsListener(root) { _, insets ->
            val bars = insets.getInsets(WindowInsetsCompat.Type.systemBars())
            val ime = insets.getInsets(WindowInsetsCompat.Type.ime())
            val minTop = (24 * resources.displayMetrics.density).toInt()
            container.updatePadding(top = maxOf(bars.top, minTop))
            nav.updatePadding(bottom = maxOf(bars.bottom, (8 * resources.displayMetrics.density).toInt()))
            // Клавиатура не должна закрывать поля ввода на экране «Подключение».
            container.updatePadding(bottom = if (ime.bottom > bars.bottom) ime.bottom else 0)
            insets
        }
        ViewCompat.requestApplyInsets(root)
    }

    override fun onSaveInstanceState(outState: Bundle) {
        super.onSaveInstanceState(outState)
        val bottomNav = findViewById<BottomNavigationView>(R.id.bottom_nav)
        outState.putInt(KEY_TAB, bottomNav.selectedItemId)
    }

    override fun onResume() {
        super.onResume()
        // Вернулись из Telegram, пока ждали код — сразу показываем ввод,
        // а не заставляем искать уведомление.
        if (AuthQueue.hasPending()) {
            startActivity(
                Intent(this, AuthActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP or Intent.FLAG_ACTIVITY_CLEAR_TOP)
            )
        }
    }

    /** Переключить вкладку из кода (например, «нет ключей — идите в Подключение»). */
    fun openTab(itemId: Int) {
        findViewById<BottomNavigationView>(R.id.bottom_nav).selectedItemId = itemId
    }

    private fun show(fragment: Fragment) {
        supportFragmentManager.beginTransaction()
            .replace(R.id.fragment_container, fragment)
            .commitAllowingStateLoss()
    }
}
