#!/usr/bin/env bash
# Colemailer - удаление службы systemd. Данные бота не трогаются.
# Запуск: sudo bash scripts/uninstall_service_linux.sh
set -u

SERVICE_NAME="colemailer"
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
LEGACY_FILE="/etc/systemd/system/spambuster.service"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=========================================================="
echo " Colemailer - удаление службы"
echo "=========================================================="

if [ "$(id -u)" -ne 0 ]; then
    echo "[!] Нужны права root: sudo bash $0"
    exit 1
fi

REMOVED=0
for unit in "$SERVICE_NAME" "spambuster"; do
    file="/etc/systemd/system/${unit}.service"
    if [ -f "$file" ]; then
        systemctl stop "$unit.service" 2>/dev/null || true
        systemctl disable "$unit.service" 2>/dev/null || true
        rm -f "$file"
        echo "[OK] Удалена служба: $unit.service"
        REMOVED=1
    fi
done

[ -f "$LEGACY_FILE" ] && rm -f "$LEGACY_FILE"

if [ "$REMOVED" -eq 0 ]; then
    echo "[i] Служб Colemailer в системе нет - удалять нечего."
fi

if command -v systemctl >/dev/null 2>&1; then
    systemctl daemon-reload
fi

echo
echo "Данные остались на месте:"
echo "  $ROOT_DIR/config.txt, *.session, storage/ ($ROOT_DIR/storage)"
echo "Снести их - удали файлы руками. Это единственное место, где хранятся ключи и вход."
