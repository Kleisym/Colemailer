package com.colemailer.app

import android.content.Context

/** Глобальный контекст приложения. Заполняется в [ColemailerApp.onCreate]. */
object App {
    lateinit var context: Context
        private set

    fun init(context: Context) {
        this.context = context.applicationContext
    }

    /** Безопасный доступ: колбэк из Python может прийти до старта Application. */
    fun contextOrNull(): Context? = if (this::context.isInitialized) context else null
}
