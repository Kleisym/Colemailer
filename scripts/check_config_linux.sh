#!/usr/bin/env bash
# Colemailer - проверка config.txt без запуска бота.
# Запуск: bash scripts/check_config_linux.sh
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

echo "=========================================================="
echo " Colemailer - проверка config.txt"
echo " Папка: $ROOT_DIR"
echo "=========================================================="
echo

if [ ! -f "config.txt" ] && [ -f "config.example.txt" ]; then
    echo "[i] config.txt нет - создаю из config.example.txt"
    cp config.example.txt config.txt
    echo "[i] Заполни api_id/api_hash (или: $PYTHON_BIN bot.py --auto-api +79991234567)"
    echo
fi

"$PYTHON_BIN" bot.py --check
code=$?
echo
if [ "$code" -ne 0 ]; then
    echo "[!] В конфиге нет ни одного аккаунта. Проверь секции [accountN] и ключи."
fi
echo "Подсказки:"
echo "  - «нет api_id/api_hash» - ключи не заполнены: my.telegram.org или bot.py --auto-api"
echo "  - «номер не задан» - впиши phone (нужен только для первого входа)"
echo "  - если в файле есть секции [account...], ключи вне секций не читаются"
