package com.colemailer.app.ui

import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
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
        setContentView(R.layout.activity_main)

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

        if (savedInstanceState == null) {
            bottomNav.selectedItemId = R.id.nav_home
        }

        permissionFlow.startOnFirstLaunch()
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
