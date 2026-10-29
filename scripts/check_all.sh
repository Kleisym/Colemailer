#!/usr/bin/env bash
# Полная локальная проверка перед релизом: самопроверка + все тесты.
set -u
cd "$(dirname "$0")/.." || exit 1
PY=".venv/bin/python"
[ -x "$PY" ] || PY="venv/bin/python"
[ -x "$PY" ] || PY="python3"

echo "== selfcheck =="
"$PY" scripts/selfcheck.py || exit 1

echo "== pytest =="
"$PY" -m pytest tests -q || exit 1
