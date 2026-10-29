#!/data/data/com.termux/files/usr/bin/bash
# Colemailer - автозапуск в Termux (Android, без APK).
# Запуск: bash scripts/install_android_termux.sh
# Идемпотентно: перезаписывает ~/.termux/boot/colemailer.sh и ничего не ломает.
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(dirname "$SCRIPT_DIR")"
BOOT_DIR="$HOME/.termux/boot"
BOOT_SCRIPT="$BOOT_DIR/colemailer.sh"
LOG_FILE="$HOME/colemailer.log"

echo "=========================================================="
echo " Colemailer - автозапуск в Termux"
echo "=========================================================="
echo " Папка проекта: $ROOT_DIR"
echo

if [ ! -f "$ROOT_DIR/bot.py" ]; then
    echo "[ОШИБКА] В $ROOT_DIR нет bot.py."
    exit 1
fi

# Первый вход (номер, код из Telegram, 2FA) нельзя сделать из автозапуска:
# там нет консоли. Проверяем, что сессия уже есть.
if ! ls "$ROOT_DIR"/*.session >/dev/null 2>&1; then
    echo "[!] Файла сессии нет. Сначала войди один раз вручную:"
    echo "      cd $ROOT_DIR && python bot.py"
    echo
fi

# Зависимости
if ! command -v python >/dev/null 2>&1; then
    echo "[ОШИБКА] Нет python. В Termux: pkg install python"
    exit 1
fi

if ! python -c "import telethon" >/dev/null 2>&1; then
    echo "[i] Ставлю зависимости (pip install -r requirements.txt)..."
    python -m pip install --upgrade pip >/dev/null 2>&1 || true
    ( cd "$ROOT_DIR" && python -m pip install -r requirements.txt ) || {
        echo "[ОШИБКА] pip не смог поставить telethon. Проверь интернет и python -V (нужен 3.10+)."
        exit 1
    }
fi

if [ ! -f "$ROOT_DIR/config.txt" ] && [ -f "$ROOT_DIR/config.example.txt" ]; then
    cp "$ROOT_DIR/config.example.txt" "$ROOT_DIR/config.txt"
    echo "[i] Создан config.txt - заполни api_id/api_hash"
fi

echo "[i] Проверка конфига:"
( cd "$ROOT_DIR" && python bot.py --check ) || true
echo

mkdir -p "$BOOT_DIR"
cat > "$BOOT_SCRIPT" <<EOF
#!/data/data/com.termux/files/usr/bin/bash
# Colemailer: поднимается после загрузки Android (нужно приложение Termux:Boot).
termux-wake-lock
cd "$ROOT_DIR" || exit 1
while true; do
    if pgrep -f '[b]ot\\.py' >/dev/null 2>&1; then
        sleep 60
        continue
    fi
    echo "[\$(date '+%Y-%m-%d %H:%M:%S')] старт Colemailer" >> "$LOG_FILE"
    python bot.py >> "$LOG_FILE" 2>&1
    echo "[\$(date '+%Y-%m-%d %H:%M:%S')] бот вышел, перезапуск через 10 с" >> "$LOG_FILE"
    sleep 10
done
EOF

chmod +x "$BOOT_SCRIPT"

if command -v termux-wake-lock >/dev/null 2>&1; then
    termux-wake-lock && echo "[OK] Wake-lock включён: Android не будет усыплять Termux."
else
    echo "[i] termux-wake-lock не найден. Поставь: pkg install termux-tools"
fi

echo
echo "[OK] Автозапуск прописан: $BOOT_SCRIPT"
echo "     Лог: $LOG_FILE"
echo
echo "Что сделать руками (Android не даёт это автоматически):"
echo "  1. Поставь Termux:Boot из F-Droid и один раз запусти его."
echo "  2. Настройки -> Приложения -> Termux -> Батарея -> «Без ограничений»"
echo "     (MIUI/HyperOS: ещё Автозапуск; Samsung: убрать из «Спящих приложений»)."
echo "  3. Проверь: перезагрузи телефон, потом tail -f $LOG_FILE"
