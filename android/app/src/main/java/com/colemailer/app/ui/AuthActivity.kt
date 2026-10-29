package com.colemailer.app.ui

import android.os.Bundle
import android.text.InputType
import android.view.View
import android.widget.TextView
import androidx.appcompat.app.AppCompatActivity
import com.colemailer.app.AuthQueue
import com.colemailer.app.R
import com.google.android.material.button.MaterialButton
import com.google.android.material.textfield.TextInputEditText
import com.google.android.material.textfield.TextInputLayout

/**
 * Ввод кода Telegram или пароля 2FA.
 *
 * Открывается из уведомления (или из главного экрана), поэтому не зависит от
 * того, жив ли главный экран. Ответ уходит в очередь сервиса [AuthQueue].
 */
class AuthActivity : AppCompatActivity() {

    companion object {
        const val EXTRA_MODE = "mode"
        const val EXTRA_TITLE = "title"
        const val EXTRA_HINT = "hint"
        const val MODE_CODE = "code"
        const val MODE_PASSWORD = "password"
    }

    private val isCode: Boolean by lazy {
        (intent?.getStringExtra(EXTRA_MODE) ?: MODE_CODE) == MODE_CODE
    }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_auth)

        val title = findViewById<TextView>(R.id.tv_auth_title)
        val description = findViewById<TextView>(R.id.tv_auth_hint)
        val inputLayout = findViewById<TextInputLayout>(R.id.til_auth_input)
        val input = findViewById<TextInputEditText>(R.id.et_auth_input)
        val error = findViewById<TextView>(R.id.tv_auth_error)

        title.text = intent?.getStringExtra(EXTRA_TITLE)
            ?: getString(if (isCode) R.string.auth_title_code else R.string.auth_title_password)
        description.text = intent?.getStringExtra(EXTRA_HINT)
            ?: getString(if (isCode) R.string.auth_hint_code else R.string.auth_hint_password)
        inputLayout.hint = getString(if (isCode) R.string.auth_hint_code else R.string.auth_hint_password)

        input.inputType = if (isCode) {
            InputType.TYPE_CLASS_NUMBER
        } else {
            InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_PASSWORD
        }
        error.visibility = View.GONE

        findViewById<MaterialButton>(R.id.btn_auth_ok).setOnClickListener {
            val value = input.text?.toString()?.trim().orEmpty()
            if (value.isEmpty()) {
                error.text = getString(if (isCode) R.string.auth_hint_code else R.string.auth_hint_password)
                error.visibility = View.VISIBLE
                return@setOnClickListener
            }
            val kind = if (isCode) AuthQueue.Kind.CODE else AuthQueue.Kind.PASSWORD
            if (AuthQueue.submit(kind, value)) {
                finish()
            } else {
                error.text = getString(R.string.auth_unknown)
                error.visibility = View.VISIBLE
            }
        }

        findViewById<MaterialButton>(R.id.btn_auth_cancel).setOnClickListener {
            val kind = if (isCode) AuthQueue.Kind.CODE else AuthQueue.Kind.PASSWORD
            AuthQueue.cancel(kind)
            finish()
        }
    }
}
