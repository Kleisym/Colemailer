#!/usr/bin/env bash
# Colemailer - автозапуск через launchd на macOS (10.13+, проверено на 12-14).
# Запуск: bash scripts/install_launchd_macos.sh
# Идемпотентно: повторный запуск перезаписывает plist и перезапускает агента.
# Удалить: launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.colemailer.bot.plist
#          rm ~/Library/LaunchAgents/com.colemailer.bot.plist
set -u

LABEL="com.colemailer.bot"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG_DIR="$HOME/Library/Logs"
LOG_FILE="$LOG_DIR/colemailer.log"
UID_NUM="$(id -u)"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=========================================================="
echo " Colemailer - автозапуск launchd (macOS)"
echo "=========================================================="
echo " Папка проекта: $ROOT_DIR"

if [ "$(uname -s)" != "Darwin" ]; then
    echo "[!] Это не macOS. Для Linux: scripts/install_service_linux.sh"
    exit 1
fi

if [ ! -f "$ROOT_DIR/bot.py" ]; then
    echo "[ОШИБКА] В $ROOT_DIR нет bot.py."
    exit 1
fi

PYTHON_BIN=""
for candidate in "$ROOT_DIR/.venv/bin/python3" "$ROOT_DIR/venv/bin/python3" \
                 "$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/venv/bin/python"; do
    if [ -x "$candidate" ]; then
        PYTHON_BIN="$candidate"
        break
    fi
done
if [ -z "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(command -v python3 || true)"
fi
if [ -z "$PYTHON_BIN" ]; then
    echo "[ОШИБКА] Не нашёл python3. Поставь: brew install python@3.12"
    exit 1
fi

if [ ! -f "$ROOT_DIR/config.txt" ] && [ -f "$ROOT_DIR/config.example.txt" ]; then
    cp "$ROOT_DIR/config.example.txt" "$ROOT_DIR/config.txt"
    echo "[i] Создан config.txt - заполни api_id/api_hash"
fi

if ! ls "$ROOT_DIR"/*.session >/dev/null 2>&1; then
    echo
    echo "[!] Файла сессии нет. Один раз войди вручную:"
    echo "      cd \"$ROOT_DIR\" && \"$PYTHON_BIN\" bot.py"
    echo "    launchd запускает бота без консоли, ввести код будет некуда."
fi

echo
echo " Проверяю конфиг:"
( cd "$ROOT_DIR" && "$PYTHON_BIN" bot.py --check ) || true

mkdir -p "$HOME/Library/LaunchAgents" "$LOG_DIR"

echo
echo " Пишу $PLIST"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON_BIN</string>
        <string>bot.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$ROOT_DIR</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PYTHONUNBUFFERED</key>
        <string>1</string>
    </dict>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>ThrottleInterval</key>
    <integer>10</integer>
    <key>StandardOutPath</key>
    <string>$LOG_FILE</string>
    <key>StandardErrorPath</key>
    <string>$LOG_FILE</string>
</dict>
</plist>
EOF

# Снять предыдущую версию агента, если она была: иначе bootstrap ругнётся.
launchctl bootout "gui/$UID_NUM" "$PLIST" >/dev/null 2>&1 || launchctl unload "$PLIST" >/dev/null 2>&1 || true

if launchctl bootstrap "gui/$UID_NUM" "$PLIST" >/dev/null 2>&1; then
    launchctl enable "gui/$UID_NUM/$LABEL" >/dev/null 2>&1 || true
    launchctl kickstart -k "gui/$UID_NUM/$LABEL" >/dev/null 2>&1 || true
    echo
    echo "[OK] Агент $LABEL загружен и запущен."
else
    launchctl load -w "$PLIST" >/dev/null 2>&1 && echo "[OK] Агент загружен (старый launchctl load)." \
        || { echo "[ОШИБКА] launchd не принял plist. Проверь: plutil -lint \"$PLIST\""; exit 1; }
fi

echo " Лог: $LOG_FILE"
echo
echo " Управление:"
echo "   launchctl print gui/$UID_NUM/$LABEL | head -30   - статус"
echo "   launchctl kickstart -k gui/$UID_NUM/$LABEL      - перезапустить"
echo "   launchctl bootout gui/$UID_NUM $PLIST           - остановить"
