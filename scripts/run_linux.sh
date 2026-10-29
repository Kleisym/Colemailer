#!/usr/bin/env bash
# Colemailer - запуск в текущем терминале (для первого входа и отладки).
# Для 24/7 используй systemd: sudo bash scripts/install_service_linux.sh
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
cd "$ROOT_DIR" || exit 1

PYTHON_BIN="python3"
for candidate in ".venv/bin/python" "venv/bin/python" ".venv/bin/python3" "venv/bin/python3"; do
    if [ -x "$candidate" ]; then
        PYTHON_BIN="$candidate"
        break
    fi
done

if [ ! -f "bot.py" ]; then
    echo "[ОШИБКА] В $ROOT_DIR нет bot.py"
    exit 1
fi

if [ ! -f "config.txt" ] && [ -f "config.example.txt" ]; then
    cp config.example.txt config.txt
    echo "[i] Создан config.txt из примера - заполни api_id/api_hash"
fi

echo "=========================================================="
echo " Colemailer"
echo " Python: $PYTHON_BIN"
echo " Папка:  $ROOT_DIR"
echo " Ctrl+C - остановить. Для 24/7: sudo bash scripts/install_service_linux.sh"
echo "=========================================================="
echo

exec "$PYTHON_BIN" bot.py "$@"
