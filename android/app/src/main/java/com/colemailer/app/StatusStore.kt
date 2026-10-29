package com.colemailer.app

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Состояние сервиса: единственный источник правды для UI.
 *
 * Живёт в памяти процесса и дублируется в SharedPreferences, поэтому после
 * смерти процесса экран не врёт «Остановлен», пока сервис работает.
 */
object StatusStore {
    private const val SEPARATOR = "|"

    private val _state = MutableStateFlow(
        ServiceState(text = "Остановлен", running = false, level = Level.INFO, phase = Phase.IDLE)
    )
    val state: StateFlow<ServiceState> = _state.asStateFlow()

    fun current(): ServiceState = _state.value

    fun set(text: String, running: Boolean, level: Level = Level.INFO) {
        publish(ServiceState(text, running, level, phaseFor(running, level), System.currentTimeMillis()))
    }

    /** Явная фаза нужна там, где по тексту её не угадать (ожидание кода). */
    fun setPhase(phase: Phase, text: String? = null, running: Boolean = _state.value.running) {
        val level = when (phase) {
            Phase.ERROR -> Level.ERROR
            Phase.DEGRADED, Phase.CODE_REQUIRED, Phase.PASSWORD_REQUIRED, Phase.STOPPED -> Level.WARN
            Phase.RUNNING -> Level.OK
            else -> Level.INFO
        }
        val body = text ?: _state.value.text
        publish(ServiceState(body, running, level, phase, System.currentTimeMillis()))
    }

    fun markRunning(text: String) {
        Prefs.sessionStartedAt = System.currentTimeMillis()
        publish(ServiceState(text, true, Level.OK, Phase.RUNNING, System.currentTimeMillis()))
    }

    fun markStopped(text: String = "Остановлен") {
        Prefs.sessionStartedAt = 0L
        publish(ServiceState(text, false, Level.INFO, Phase.STOPPED, System.currentTimeMillis()))
    }

    fun restore() {
        val raw = Prefs.lastStatus
        if (raw.isBlank()) return
        val parts = raw.split(SEPARATOR)
        if (parts.size < 4) return
        val text = parts[0]
        val running = parts[1].toBooleanStrictOrNull() ?: false
        val level = runCatching { Level.valueOf(parts[2]) }.getOrDefault(Level.INFO)
        val at = parts[3].toLongOrNull() ?: 0L
        val phase = if (running) Phase.CONNECTING else Phase.STOPPED
        _state.value = ServiceState(text, running, level, phase, at)
    }

    private fun publish(state: ServiceState) {
        _state.value = state
        Prefs.lastStatus = listOf(
            state.text,
            state.running.toString(),
            state.level.name,
            state.at.toString()
        ).joinToString(SEPARATOR)
    }

    private fun phaseFor(running: Boolean, level: Level): Phase = when {
        running && level == Level.OK -> Phase.RUNNING
        running && level == Level.ERROR -> Phase.ERROR
        running && level == Level.WARN -> Phase.DEGRADED
        running -> Phase.CONNECTING
        level == Level.ERROR -> Phase.ERROR
        else -> Phase.STOPPED
    }
}
