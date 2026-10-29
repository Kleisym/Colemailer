#!/usr/bin/env bash
# Самопроверка Colemailer на Linux/macOS/Termux.
set -u
cd "$(dirname "$0")/.." || exit 1
if [ -x ".venv/bin/python" ]; then
    .venv/bin/python scripts/selfcheck.py "$@"
elif [ -x "venv/bin/python" ]; then
    venv/bin/python scripts/selfcheck.py "$@"
else
    python3 scripts/selfcheck.py "$@"
fi
