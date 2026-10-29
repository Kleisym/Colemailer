#!/usr/bin/env bash
# Colemailer - остановить службу и все процессы bot.py.
# Идемпотентно: если ничего не запущено, просто сообщает об этом.
set -u

SERVICE_NAME="colemailer"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "Останавливаю Colemailer..."

if command -v systemctl >/dev/null 2>&1 && [ -f "/etc/systemd/system/${SERVICE_NAME}.service" ]; then
    if systemctl is-active --quiet "$SERVICE_NAME.service"; then
        sudo systemctl stop "$SERVICE_NAME.service" && echo "[OK] Служба $SERVICE_NAME остановлена."
    else
        echo "[i] Служба $SERVICE_NAME уже остановлена."
    fi
fi

PIDS="$(pgrep -f "[b]ot\.py" 2>/dev/null | tr '\n' ' ' || true)"
if [ -n "$PIDS" ]; then
    echo "[i] Останавливаю процессы: $PIDS"
    # shellcheck disable=SC2086
    kill $PIDS 2>/dev/null || true
    sleep 2
    LEFT="$(pgrep -f "[b]ot\.py" 2>/dev/null | tr '\n' ' ' || true)"
    if [ -n "$LEFT" ]; then
        echo "[i] Не вышли сами - добиваю: $LEFT"
        # shellcheck disable=SC2086
        kill -9 $LEFT 2>/dev/null || true
    fi
    echo "[OK] Процессы bot.py остановлены."
else
    echo "[i] Отдельных процессов bot.py не было."
fi

echo "Папка: $ROOT_DIR"
echo "Запустить снова: bash scripts/run_linux.sh или sudo systemctl start $SERVICE_NAME"
