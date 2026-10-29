package com.colemailer.app

import android.app.Application

/**
 * Application приложения.
 *
 * Осознанно НЕ наследник PyApplication: интерпретатор Python стартует только в
 * [BotService]. Иначе простой запуск экрана тянул бы 40-70 МБ RSS и полторы
 * секунды холодного старта, даже когда юзербот выключен.
 */
class ColemailerApp : Application() {

    override fun onCreate() {
        super.onCreate()
        App.init(this)
        Prefs.init(this)
        Notifications.ensureChannels(this)
        StatusStore.restore()
        WorkScheduler.ensureGuard(this)
    }
}
