package com.colemailer.app

/** Уровень события для статуса и логов. */
enum class Level { INFO, OK, WARN, ERROR }

/**
 * Что показывает главный экран. [Phase] выставляется на стороне Kotlin
 * (сервис/очередь ввода), текст приходит и из Python-моста.
 */
enum class Phase {
    IDLE,
    STARTING,
    CONNECTING,
    CODE_REQUIRED,
    PASSWORD_REQUIRED,
    RUNNING,
    DEGRADED,
    ERROR,
    STOPPED
}

data class ServiceState(
    val text: String = "",
    val running: Boolean = false,
    val level: Level = Level.INFO,
    val phase: Phase = Phase.IDLE,
    val at: Long = 0L
) {
    val busy: Boolean
        get() = phase == Phase.STARTING || phase == Phase.CONNECTING
}

/** Строка лога для экрана «Главная». */
data class LogLine(
    val seq: Long,
    val time: String,
    val level: String,
    val message: String
)
