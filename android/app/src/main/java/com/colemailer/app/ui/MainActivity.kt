package com.colemailer.app.ui

import android.os.Bundle
import android.view.View
import androidx.appcompat.app.AppCompatActivity
import androidx.core.view.ViewCompat
import androidx.core.view.WindowCompat
import androidx.core.view.WindowInsetsCompat
import androidx.core.view.WindowInsetsControllerCompat
import androidx.core.view.updatePadding
import androidx.fragment.app.Fragment
import com.colemailer.app.PermissionFlow
import com.colemailer.app.R
import com.google.android.material.bottomnavigation.BottomNavigationView

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
            container.updatePadding(top = bars.top)
            nav.updatePadding(bottom = bars.bottom)
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
