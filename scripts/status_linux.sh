#!/usr/bin/env bash
# Colemailer - статус службы и процессов. Ничего не меняет, sudo не нужен.
set -u

SERVICE_NAME="colemailer"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=========================================================="
echo " Colemailer - статус"
echo "=========================================================="
echo " Папка проекта: $ROOT_DIR"
echo

if command -v systemctl >/dev/null 2>&1 && [ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]; then
    if systemctl is-active --quiet "$SERVICE_NAME.service"; then
        echo "[Служба] активна"
    else
        echo "[Служба] не активна (установлена, но остановлена)"
    fi
    systemctl status "$SERVICE_NAME.service" --no-pager --lines=0 2>/dev/null || true
    echo
    echo "[Последние строки лога]"
    if command -v journalctl >/dev/null 2>&1; then
        journalctl -u "$SERVICE_NAME" -n 15 --no-pager 2>/dev/null || echo "  (журнал недоступен без прав)"
    fi
else
    echo "[Служба] не установлена (scripts/install_service_linux.sh)"
fi

echo
echo "[Процессы bot.py]"
if pgrep -af "[b]ot\.py" >/dev/null 2>&1; then
    pgrep -af "[b]ot\.py"
else
    echo "  не запущены"
fi

echo
echo "[Файлы]"
for f in config.txt storage/bot.db; do
    if [ -e "$ROOT_DIR/$f" ]; then
        echo "  $f - есть"
    else
        echo "  $f - нет"
    fi
done
if ls "$ROOT_DIR"/*.session >/dev/null 2>&1; then
    echo "  сессии: $(cd "$ROOT_DIR" && ls -1 ./*.session | wc -l | tr -d ' ')"
else
    echo "  сессии: нет (первый вход не сделан)"
fi
