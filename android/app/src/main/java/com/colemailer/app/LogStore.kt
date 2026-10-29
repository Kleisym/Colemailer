package com.colemailer.app

import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.flow.asStateFlow

/**
 * Кольцевой буфер логов для экрана.
 *
 * print() из Chaquopy уходит в logcat, а UI его не видит, поэтому Python-мост
 * отдаёт строки через callback.onLog. Пишет Python-поток, читает UI — доступ
 * сериализуем.
 */
object LogStore {
    private const val LIMIT = 400
    private val pattern = Regex("""^(\d{2}:\d{2}:\d{2})\s+([A-Z]+)\s+(.*)$""")
    private val lock = Any()

    private val _lines = MutableStateFlow<List<LogLine>>(emptyList())
    val lines: StateFlow<List<LogLine>> = _lines.asStateFlow()

    private var seq = 0L

    fun append(raw: String) {
        appendAll(listOf(raw))
    }

    fun appendAll(raw: List<String>) {
        if (raw.isEmpty()) return
        synchronized(lock) {
            val parsed = raw.map { parse(it) }
            _lines.value = (_lines.value + parsed).takeLast(LIMIT)
        }
    }

    fun clear() {
        synchronized(lock) { _lines.value = emptyList() }
    }

    fun snapshot(): String = _lines.value.joinToString("\n") { it.rawText() }

    // Вызывается только под lock.
    private fun parse(raw: String): LogLine {
        seq += 1
        val match = pattern.find(raw.trim())
        return if (match != null) {
            LogLine(seq, match.groupValues[1], match.groupValues[2], match.groupValues[3])
        } else {
            LogLine(seq, "", "", raw.trim())
        }
    }

    private fun LogLine.rawText(): String =
        if (time.isBlank()) message else "$time $level $message"
}
