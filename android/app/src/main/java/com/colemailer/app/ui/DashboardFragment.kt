package com.colemailer.app.ui

import android.content.Intent
import android.os.Bundle
import android.view.View
import android.widget.TextView
import android.widget.Toast
import androidx.fragment.app.Fragment
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.lifecycleScope
import androidx.lifecycle.repeatOnLifecycle
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.colemailer.app.BatteryOpt
import com.colemailer.app.BotService
import com.colemailer.app.LogLine
import com.colemailer.app.LogStore
import com.colemailer.app.NetMonitor
import com.colemailer.app.Phase
import com.colemailer.app.Prefs
import com.colemailer.app.PythonBridge
import com.colemailer.app.R
import com.colemailer.app.ServiceState
import com.colemailer.app.StatusStore
import com.google.android.material.button.MaterialButton
import com.google.android.material.progressindicator.LinearProgressIndicator
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Главная: состояние, uptime, аккаунт, чек-лист фона, кнопка Старт/Стоп и лог.
 */
class DashboardFragment : Fragment(R.layout.fragment_dashboard) {

    private lateinit var dotState: View
    private lateinit var tvState: TextView
    private lateinit var tvNetwork: TextView
    private lateinit var tvUptime: TextView
    private lateinit var tvDetail: TextView
    private lateinit var progress: LinearProgressIndicator
    private lateinit var tvAccount: TextView
    private lateinit var tvBgSummary: TextView
    private lateinit var tvNextTask: TextView
    private lateinit var tvLogEmpty: TextView
    private lateinit var rvLogs: RecyclerView
    private lateinit var btnPower: MaterialButton
    private lateinit var logAdapter: LogAdapter

    private val clock = SimpleDateFormat("HH:mm", Locale.getDefault())

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        dotState = view.findViewById(R.id.dot_state)
        tvState = view.findViewById(R.id.tv_state)
        tvNetwork = view.findViewById(R.id.tv_network)
        tvUptime = view.findViewById(R.id.tv_uptime)
        tvDetail = view.findViewById(R.id.tv_detail)
        progress = view.findViewById(R.id.progress)
        tvAccount = view.findViewById(R.id.tv_account)
        tvBgSummary = view.findViewById(R.id.tv_bg_summary)
        tvNextTask = view.findViewById(R.id.tv_next_task)
        tvLogEmpty = view.findViewById(R.id.tv_log_empty)
        rvLogs = view.findViewById(R.id.rv_logs)
        btnPower = view.findViewById(R.id.btn_power)

        logAdapter = LogAdapter()
        rvLogs.layoutManager = LinearLayoutManager(requireContext()).apply { stackFromEnd = true }
        rvLogs.adapter = logAdapter

        btnPower.setOnClickListener { onPowerClicked() }
        view.findViewById<MaterialButton>(R.id.btn_fix_background).setOnClickListener {
            (activity as? MainActivity)?.permissionFlow?.requestNext()
        }
        view.findViewById<MaterialButton>(R.id.btn_clear_log).setOnClickListener {
            LogStore.clear()
        }

        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                StatusStore.state.collect { state -> render(state) }
            }
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                LogStore.lines.collect { lines -> renderLogs(lines) }
            }
        }
        viewLifecycleOwner.lifecycleScope.launch {
            viewLifecycleOwner.repeatOnLifecycle(Lifecycle.State.STARTED) {
                while (true) {
                    renderUptime()
                    delay(5_000L)
                }
            }
        }
    }

    override fun onResume() {
        super.onResume()
        refreshBackgroundCard()
        tvNetwork.text = NetMonitor.label(requireContext())
        loadBridgeInfo()
    }

    private fun onPowerClicked() {
        val context = requireContext()
        val state = StatusStore.current()

        // Пока бот ждёт код/пароль, главная кнопка ведёт туда, а не «Стоп».
        if (state.phase == Phase.CODE_REQUIRED) {
            openAuth(code = true)
            return
        }
        if (state.phase == Phase.PASSWORD_REQUIRED) {
            openAuth(code = false)
            return
        }

        if (state.running) {
            BotService.stop(context)
            return
        }
        if (!Prefs.hasCredentials()) {
            Toast.makeText(context, R.string.toast_need_keys, Toast.LENGTH_LONG).show()
            (activity as? MainActivity)?.openTab(R.id.nav_connect)
            return
        }
        BotService.start(context, "ui")
        // Не все шаги фона закрыты — сразу ведём по ним, иначе бот «заснёт»
        // сразу после гашения экрана.
        if (BatteryOpt.fixedCount(context) < 4) {
            (activity as? MainActivity)?.permissionFlow?.requestNext()
        }
    }

    private fun openAuth(code: Boolean) {
        val intent = Intent(requireContext(), AuthActivity::class.java)
            .putExtra(
                AuthActivity.EXTRA_MODE,
                if (code) AuthActivity.MODE_CODE else AuthActivity.MODE_PASSWORD
            )
        startActivity(intent)
    }

    private fun render(state: ServiceState) {
        tvState.text = state.text
        dotState.setBackgroundResource(dotFor(state.phase))
        progress.visibility = if (state.busy) View.VISIBLE else View.GONE
        btnPower.text = when (state.phase) {
            Phase.CODE_REQUIRED -> getString(R.string.btn_enter_code)
            Phase.PASSWORD_REQUIRED -> getString(R.string.btn_enter_password)
            else -> getString(if (state.running) R.string.btn_stop else R.string.btn_start)
        }
        tvDetail.text = detailFor(state)
        tvAccount.text = Prefs.user.ifBlank { getString(R.string.label_account_empty) }
        tvNetwork.text = NetMonitor.label(requireContext())
        renderUptime()
    }

    private fun renderUptime() {
        val started = Prefs.sessionStartedAt
        val running = StatusStore.current().running
        tvUptime.text = if (running && started > 0L) {
            formatUptime(System.currentTimeMillis() - started)
        } else {
            getString(R.string.state_uptime_zero)
        }
    }

    private fun renderLogs(lines: List<LogLine>) {
        logAdapter.submitList(lines)
        val hasAny = lines.isNotEmpty()
        rvLogs.visibility = if (hasAny) View.VISIBLE else View.GONE
        tvLogEmpty.visibility = if (hasAny) View.GONE else View.VISIBLE
        if (hasAny) {
            rvLogs.scrollToPosition(lines.size - 1)
        }
    }

    private fun refreshBackgroundCard() {
        val fixed = BatteryOpt.fixedCount(requireContext())
        tvBgSummary.text = getString(R.string.bg_summary_fmt, fixed, 4)
    }

    private fun loadBridgeInfo() {
        viewLifecycleOwner.lifecycleScope.launch {
            val state: JSONObject? = withContext(Dispatchers.IO) {
                if (BotService.isRunning() && PythonBridge.isAlive) PythonBridge.state() else null
            }
            renderNextTask(state)
            if (state != null) {
                val user = state.optString("user")
                if (user.isNotBlank()) tvAccount.text = user
            }
        }
    }

    private fun renderNextTask(state: JSONObject?) {
        val due = state?.optLong("next_due_ms", 0L) ?: 0L
        tvNextTask.text = if (due > 0L) {
            clock.format(Date(due))
        } else {
            getString(R.string.label_no_task)
        }
    }

    private fun dotFor(phase: Phase): Int = when (phase) {
        Phase.RUNNING -> R.drawable.dot_running
        Phase.ERROR -> R.drawable.dot_error
        Phase.DEGRADED, Phase.CODE_REQUIRED, Phase.PASSWORD_REQUIRED -> R.drawable.dot_warn
        else -> R.drawable.dot_idle
    }

    private fun detailFor(state: ServiceState): String = when (state.phase) {
        Phase.RUNNING -> getString(R.string.detail_running)
        Phase.CODE_REQUIRED -> getString(R.string.detail_code)
        Phase.PASSWORD_REQUIRED -> getString(R.string.detail_password)
        Phase.CONNECTING, Phase.STARTING -> getString(R.string.detail_connecting)
        Phase.ERROR -> state.text
        else -> getString(R.string.detail_idle)
    }

    private fun formatUptime(ms: Long): String {
        if (ms <= 0L) return getString(R.string.state_uptime_zero)
        val minutes = ms / 60_000L
        val hours = minutes / 60L
        return when {
            hours > 0L -> "$hours ч ${minutes % 60L} мин"
            minutes > 0L -> "$minutes мин"
            else -> "меньше минуты"
        }
    }
}
