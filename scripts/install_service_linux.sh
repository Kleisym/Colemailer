#!/usr/bin/env bash
# Colemailer - установка службы systemd (Linux: Ubuntu/Debian/Fedora/Arch).
# Запуск: sudo bash scripts/install_service_linux.sh
# Идемпотентно: повторный запуск перезаписывает unit и перезапускает службу.
set -euo pipefail

SERVICE_NAME="colemailer"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
LEGACY_FILE="/etc/systemd/system/spambuster.service"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=========================================================="
echo " Colemailer - служба systemd (24/7)"
echo "=========================================================="
echo " Папка проекта: $ROOT_DIR"

if [ ! -f "$ROOT_DIR/bot.py" ]; then
    echo "[ОШИБКА] В $ROOT_DIR нет bot.py. Скрипт должен лежать в scripts/ рядом с ботом."
    exit 1
fi

if [ "$(id -u)" -ne 0 ]; then
    echo
    echo "[!] Нужны права root."
    echo "    Запусти: sudo bash $0"
    exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
    echo "[ОШИБКА] systemctl не найден - это не systemd-система."
    echo "         Запускай бота через scripts/run_linux.sh или screen/tmux."
    exit 1
fi

RUN_USER="${SUDO_USER:-$(id -un)}"
if [ "$RUN_USER" = "root" ]; then
    echo " [!] Служба будет работать от root. Лучше от отдельного пользователя,"
    echo "     но если это VPS под root - оставляем так."
fi

PYTHON_BIN=""
for candidate in "$ROOT_DIR/.venv/bin/python" "$ROOT_DIR/venv/bin/python" \
                 "$ROOT_DIR/.venv/bin/python3" "$ROOT_DIR/venv/bin/python3"; do
    if [ -x "$candidate" ]; then
        PYTHON_BIN="$candidate"
        break
    fi
done
if [ -z "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(command -v python3 || true)"
fi
if [ -z "$PYTHON_BIN" ]; then
    echo "[ОШИБКА] Не нашёл python3. Поставь: apt install python3 python3-venv"
    exit 1
fi

echo " Пользователь:  $RUN_USER"
echo " Python:        $PYTHON_BIN"

if [ ! -f "$ROOT_DIR/config.txt" ]; then
    cp "$ROOT_DIR/config.example.txt" "$ROOT_DIR/config.txt" 2>/dev/null || true
    chown "$RUN_USER":"$RUN_USER" "$ROOT_DIR/config.txt" 2>/dev/null || true
    echo
    echo "[!] config.txt не было - создал из config.example.txt."
    echo "    Заполни api_id/api_hash (или '$PYTHON_BIN bot.py --auto-api +7999...')"
    echo "    и запусти этот скрипт снова."
fi

# Первый вход (номер, код, 2FA) нельзя сделать из службы - там нет консоли.
# Проверяем, есть ли уже файл сессии.
if ! ls "$ROOT_DIR"/*.session >/dev/null 2>&1; then
    echo
    echo "[!] Файлов сессии нет. Один раз войди вручную:"
    echo "      cd $ROOT_DIR && $PYTHON_BIN bot.py"
    echo "    Без этого служба будет работать, но к Telegram не подключится."
fi

echo
echo " Проверяю конфиг (bot.py --check):"
if [ "$RUN_USER" != "root" ] && command -v runuser >/dev/null 2>&1; then
    runuser -u "$RUN_USER" -- "$PYTHON_BIN" "$ROOT_DIR/bot.py" --check || true
else
    ( cd "$ROOT_DIR" && "$PYTHON_BIN" bot.py --check ) || true
fi

if [ -f "$LEGACY_FILE" ]; then
    echo
    echo "[i] Нашёл старую службу spambuster.service - убираю."
    systemctl stop spambuster.service 2>/dev/null || true
    systemctl disable spambuster.service 2>/dev/null || true
    rm -f "$LEGACY_FILE"
fi

if [ -f "$SERVICE_FILE" ]; then
    echo "[i] Служба уже установлена - останавливаю перед перезаписью."
    systemctl stop "$SERVICE_NAME.service" 2>/dev/null || true
fi

echo
echo " Пишу $SERVICE_FILE"
cat > "$SERVICE_FILE" <<EOF
[Unit]
Description=Colemailer - Telegram userbot (antispam + scheduled broadcasts)
Documentation=https://github.com/Kleisym/Colemailer
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$RUN_USER
WorkingDirectory=$ROOT_DIR
ExecStart=$PYTHON_BIN bot.py
Restart=always
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=20
Environment=PYTHONUNBUFFERED=1
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

chmod 644 "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable "$SERVICE_NAME.service" >/dev/null
systemctl restart "$SERVICE_NAME.service"

if systemctl is-active --quiet "$SERVICE_NAME.service"; then
    echo
    echo "[OK] Служба $SERVICE_NAME запущена и включена в автозагрузку."
else
    echo
    echo "[!] Служба не поднялась. Смотри лог:"
    echo "    sudo journalctl -u $SERVICE_NAME -n 50 --no-pager"
fi

if [ -d "$ROOT_DIR/storage" ]; then
    OWNER="$(stat -c '%U' "$ROOT_DIR/storage" 2>/dev/null || echo '?')"
    if [ "$OWNER" != "$RUN_USER" ]; then
        echo
        echo "[!] Папка storage принадлежит '$OWNER', а служба работает от '$RUN_USER'."
        echo "    Исправь: sudo chown -R $RUN_USER:$RUN_USER $ROOT_DIR/storage"
    fi
fi

echo
echo " Управление:"
echo "   bash scripts/status_linux.sh                      - статус"
echo "   sudo systemctl restart $SERVICE_NAME               - перезапустить"
echo "   sudo systemctl stop $SERVICE_NAME                  - остановить"
echo "   sudo journalctl -u $SERVICE_NAME -f                - логи"
echo "   sudo bash scripts/uninstall_service_linux.sh       - удалить службу"
