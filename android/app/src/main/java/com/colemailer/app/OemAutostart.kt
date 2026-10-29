package com.colemailer.app

import android.content.ComponentName
import android.content.Context
import android.content.Intent
import android.os.Build
import android.provider.Settings

/**
 * Экраны «Автозапуск / работа в фоне» у производителей.
 *
 * Прочитать состояние автозапуска нельзя: API не существует. Поэтому
 * приложение открывает точный экран и хранит отметку «я включил» — врать
 * зелёной галочкой нельзя.
 */
object OemAutostart {

    private data class Target(val pkg: String, val cls: String)

    private val miui = listOf(
        Target("com.miui.securitycenter", "com.miui.permcenter.autostart.AutoStartManagementActivity"),
        Target("com.miui.powerkeeper", "com.miui.powerkeeper.ui.HiddenAppsConfigActivity"),
        Target("com.miui.securitycenter", "com.miui.permcenter.permissions.PermissionsEditorActivity")
    )
    private val huawei = listOf(
        Target("com.huawei.systemmanager", "com.huawei.systemmanager.startupmgr.ui.StartupNormalAppListActivity"),
        Target("com.huawei.systemmanager", "com.huawei.systemmanager.optimize.process.ProtectActivity"),
        Target("com.huawei.systemmanager", "com.huawei.systemmanager.appcontrol.activity.StartupAppControlActivity")
    )
    private val honor = listOf(
        Target("com.hihonor.systemmanager", "com.hihonor.systemmanager.startupmgr.ui.StartupNormalAppListActivity"),
        Target("com.hihonor.systemmanager", "com.hihonor.systemmanager.optimize.process.ProtectActivity")
    )
    private val colorOs = listOf(
        Target("com.oplus.safecenter", "com.oplus.safecenter.startupapp.StartupAppListActivity"),
        Target("com.oplus.safecenter", "com.oplus.safecenter.permission.startup.StartupAppListActivity"),
        Target("com.coloros.safecenter", "com.coloros.safecenter.startupapp.StartupAppListActivity"),
        Target("com.coloros.safecenter", "com.coloros.safecenter.permission.startup.StartupAppListActivity"),
        Target("com.oppo.safe", "com.oppo.safe.permission.startup.StartupAppListActivity"),
        Target("com.oneplus.security", "com.oneplus.security.chainlaunch.view.ChainLaunchAppListActivity")
    )
    private val vivo = listOf(
        Target("com.vivo.permissionmanager", "com.vivo.permissionmanager.activity.BgStartUpManagerActivity"),
        Target("com.iqoo.secure", "com.iqoo.secure.ui.phoneoptimize.AddWhiteListActivity"),
        Target("com.vivo.abe", "com.vivo.applicationbehaviorengine.ui.ExcessivePowerManagerActivity")
    )
    private val samsung = listOf(
        Target("com.samsung.android.lool", "com.samsung.android.sm.ui.battery.BatteryActivity"),
        Target("com.samsung.android.sm", "com.samsung.android.sm.ui.battery.BatteryActivity")
    )
    private val others = listOf(
        Target("com.meizu.safe", "com.meizu.safe.permission.SmartBGActivity"),
        Target("com.asus.mobilemanager", "com.asus.mobilemanager.entry.FunctionActivity"),
        Target("com.letv.android.letvsafe", "com.letv.android.letvsafe.AutobootManageActivity"),
        Target("com.transsion.phonemaster", "com.transsion.phonemaster.activitys.PhonemasterActivity")
    )

    private fun vendorTargets(): List<Target> = when {
        Build.MANUFACTURER.equals("xiaomi", true) ||
            Build.BRAND.equals("redmi", true) ||
            Build.BRAND.equals("poco", true) -> miui
        Build.MANUFACTURER.equals("huawei", true) -> huawei
        Build.MANUFACTURER.equals("honor", true) -> honor
        Build.MANUFACTURER.equals("oppo", true) ||
            Build.MANUFACTURER.equals("realme", true) ||
            Build.MANUFACTURER.equals("oneplus", true) -> colorOs
        Build.MANUFACTURER.equals("vivo", true) ||
            Build.MANUFACTURER.equals("iqoo", true) -> vivo
        Build.MANUFACTURER.equals("samsung", true) -> samsung
        else -> emptyList()
    }

    /** Первый экран, который реально резолвится (нужен блок <queries>). */
    fun bestIntent(context: Context): Intent? {
        for (target in vendorTargets() + others) {
            val intent = Intent().setComponent(ComponentName(target.pkg, target.cls))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            val resolvable = context.packageManager.resolveActivity(intent, 0) != null
            if (resolvable) return intent
        }
        return null
    }

    /**
     * Открыть экран автозапуска. true — что-то открылось, false — ушли в
     * «Настройки приложения» (fallback).
     */
    fun open(context: Context): Boolean {
        for (target in vendorTargets() + others) {
            val component = ComponentName(target.pkg, target.cls)
            val intent = Intent().setComponent(component)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            if (tryStart(context, intent)) return true
        }
        // Некоторые прошивки прячут класс, но оставляют action.
        val actions = listOf(
            Intent("miui.intent.action.OP_AUTO_START").addCategory(Intent.CATEGORY_DEFAULT),
            Intent("miui.intent.action.APP_PERM_EDITOR")
                .putExtra("extra_pkgname", context.packageName),
            Intent("com.meizu.safe.security.SHOW_APPSEC")
                .putExtra("packageName", context.packageName)
        )
        for (intent in actions) {
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
            if (tryStart(context, intent)) return true
        }
        startQuietly(
            context,
            Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                .setData(android.net.Uri.parse("package:" + context.packageName))
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        )
        return false
    }

    /** Состояние автозапуска не читается: храним отметку пользователя. */
    fun assumeEnabled(): Boolean = Prefs.oemAutostartConfirmed

    fun confirm() {
        Prefs.oemAutostartConfirmed = true
    }

    /** Текстовая инструкция, если экран не открылся. */
    fun manualSteps(): String = when {
        Build.MANUFACTURER.equals("xiaomi", true) ||
            Build.BRAND.equals("redmi", true) ||
            Build.BRAND.equals("poco", true) ->
            "Настройки -> Приложения -> Colemailer -> Автозапуск: включить. " +
                "Батарея -> «Нет ограничений». В «Недавних» зажать карточку и поставить замок."
        Build.MANUFACTURER.equals("huawei", true) || Build.MANUFACTURER.equals("honor", true) ->
            "Настройки -> Батарея -> Запуск приложений -> Colemailer -> «Управлять вручную», все три переключателя."
        Build.MANUFACTURER.equals("samsung", true) ->
            "Настройки -> Обслуживание устройства -> Батарея -> Ограничения фоновой активности: " +
                "убрать Colemailer из «Спящих приложений», поставить «Без ограничений»."
        Build.MANUFACTURER.equals("oppo", true) ||
            Build.MANUFACTURER.equals("realme", true) ||
            Build.MANUFACTURER.equals("oneplus", true) ->
            "Настройки -> Батарея -> Расход батареи приложениями -> Colemailer: " +
                "разрешить фоновую активность и автозапуск."
        Build.MANUFACTURER.equals("vivo", true) || Build.MANUFACTURER.equals("iqoo", true) ->
            "Настройки -> Батарея -> Фоновое энергопотребление -> Colemailer: разрешить автозапуск и фон."
        else ->
            "Настройки -> Приложения -> Colemailer: разрешить автозапуск, " +
                "снять ограничения фоновой активности и энергосбережения."
    }

    private fun tryStart(context: Context, intent: Intent): Boolean = try {
        context.startActivity(intent)
        true
    } catch (e: Exception) {
        false
    }

    private fun startQuietly(context: Context, intent: Intent) {
        try {
            context.startActivity(intent)
        } catch (e: Exception) {
            // нечего открывать — останется текстовая инструкция
        }
    }
}
