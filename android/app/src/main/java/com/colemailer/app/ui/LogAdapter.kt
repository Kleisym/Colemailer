package com.colemailer.app.ui

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.core.content.ContextCompat
import androidx.recyclerview.widget.DiffUtil
import androidx.recyclerview.widget.ListAdapter
import androidx.recyclerview.widget.RecyclerView
import com.colemailer.app.LogLine
import com.colemailer.app.R

/** Строки лога: цвет зависит от уровня, ключ сравнения — seq. */
class LogAdapter : ListAdapter<LogLine, LogAdapter.Holder>(DIFF) {

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): Holder {
        val view = LayoutInflater.from(parent.context).inflate(R.layout.item_log, parent, false)
        return Holder(view)
    }

    override fun onBindViewHolder(holder: Holder, position: Int) {
        holder.bind(getItem(position))
    }

    class Holder(view: View) : RecyclerView.ViewHolder(view) {
        private val time: TextView = view.findViewById(R.id.tv_time)
        private val level: TextView = view.findViewById(R.id.tv_level)
        private val message: TextView = view.findViewById(R.id.tv_message)

        fun bind(line: LogLine) {
            val context = itemView.context
            val colorRes = when (line.level.uppercase()) {
                "ERROR" -> R.color.log_error
                "WARN" -> R.color.log_warn
                "OK" -> R.color.log_send
                "DEBUG" -> R.color.log_debug
                else -> R.color.log_info
            }
            val color = ContextCompat.getColor(context, colorRes)
            time.text = line.time
            level.text = line.level
            level.setTextColor(color)
            message.text = line.message
            message.setTextColor(color)
        }
    }

    companion object {
        private val DIFF = object : DiffUtil.ItemCallback<LogLine>() {
            override fun areItemsTheSame(oldItem: LogLine, newItem: LogLine): Boolean =
                oldItem.seq == newItem.seq

            override fun areContentsTheSame(oldItem: LogLine, newItem: LogLine): Boolean =
                oldItem == newItem
        }
    }
}
