package com.colemailer.app.ui

import android.os.Bundle
import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.fragment.app.Fragment
import androidx.lifecycle.lifecycleScope
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.colemailer.app.BotService
import com.colemailer.app.PythonBridge
import com.colemailer.app.R
import com.google.android.material.button.MaterialButton
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/** Строка списка рассылок. */
data class TaskItem(val title: String, val subtitle: String)

/**
 * Рассылки: то, что реально лежит в БД бота — шаблоны и активные задачи.
 * Управление (создание/правка) — командами в чате, здесь только просмотр.
 */
class BroadcastsFragment : Fragment(R.layout.fragment_broadcasts) {

    private lateinit var tvStatus: TextView
    private lateinit var adapter: TaskAdapter
    private val clock = SimpleDateFormat("dd.MM HH:mm", Locale.getDefault())

    override fun onViewCreated(view: View, savedInstanceState: Bundle?) {
        super.onViewCreated(view, savedInstanceState)

        tvStatus = view.findViewById(R.id.tv_broadcasts_status)
        val list = view.findViewById<RecyclerView>(R.id.rv_tasks)
        adapter = TaskAdapter()
        list.layoutManager = LinearLayoutManager(requireContext())
        list.adapter = adapter

        view.findViewById<MaterialButton>(R.id.btn_refresh).setOnClickListener { load() }
        load()
    }

    private fun load() {
        val context = requireContext().applicationContext
        if (!BotService.isRunning() && !PythonBridge.isAlive) {
            tvStatus.text = getString(R.string.broadcasts_not_ready)
            return
        }
        viewLifecycleOwner.lifecycleScope.launch {
            val json: JSONObject? = withContext(Dispatchers.IO) {
                PythonBridge.tasks()
            }
            if (json == null) {
                tvStatus.text = getString(R.string.broadcasts_not_ready)
                return@launch
            }
            val items = mutableListOf<TaskItem>()
            val templates = json.optJSONArray("templates")
            if (templates != null) {
                for (index in 0 until templates.length()) {
                    val item = templates.optJSONObject(index) ?: continue
                    val name = item.optString("name").ifBlank { "шаблон" }
                    val preview = item.optString("preview")
                    items.add(TaskItem(name, preview))
                }
            }
            val tasks = json.optJSONArray("tasks")
            if (tasks != null) {
                for (index in 0 until tasks.length()) {
                    val item = tasks.optJSONObject(index) ?: continue
                    val template = item.optString("template").ifBlank { "шаблон" }
                    val chat = item.optString("chat_id")
                    val nextAt = item.optDouble("next_at", 0.0)
                    val subtitle = buildString {
                        append(getString(R.string.item_task_chat, chat))
                        if (nextAt > 0.0) {
                            append(" · ")
                            append(getString(R.string.item_task_next, clock.format(Date((nextAt * 1000).toLong()))))
                        }
                    }
                    items.add(TaskItem(template, subtitle))
                }
            }
            adapter.submitList(items)
            tvStatus.text = if (items.isEmpty()) {
                getString(if (json.optBoolean("ready")) R.string.broadcasts_empty else R.string.broadcasts_not_ready)
            } else {
                ""
            }
        }
    }
}

/** Адаптер списка рассылок. */
class TaskAdapter : ListAdapter<TaskItem, TaskAdapter.Holder>(DIFF) {

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): Holder {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_task, parent, false)
        return Holder(view)
    }

    override fun onBindViewHolder(holder: Holder, position: Int) {
        holder.bind(getItem(position))
    }

    class Holder(view: View) : RecyclerView.ViewHolder(view) {
        private val title: TextView = view.findViewById(R.id.tv_task_title)
        private val subtitle: TextView = view.findViewById(R.id.tv_task_sub)

        fun bind(item: TaskItem) {
            title.text = item.title
            subtitle.text = item.subtitle
        }
    }

    companion object {
        private val DIFF = object : DiffUtil.ItemCallback<TaskItem>() {
            override fun areItemsTheSame(oldItem: TaskItem, newItem: TaskItem): Boolean =
                oldItem.title == newItem.title && oldItem.subtitle == newItem.subtitle

            override fun areContentsTheSame(oldItem: TaskItem, newItem: TaskItem): Boolean =
                oldItem == newItem
        }
    }
}
