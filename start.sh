#!/bin/bash
# ===================================================
# QueueX Startup Script
# Smart Virtual Queue Management System
# Target: CGC University Mohali, Punjab, India
# ===================================================

# Find python from virtualenv or system
if [ -d "venv" ]; then
    PYTHON_BIN="./venv/bin/python"
    GUNICORN_BIN="./venv/bin/gunicorn"
elif [ -d ".venv" ]; then
    PYTHON_BIN="./.venv/bin/python"
    GUNICORN_BIN="./.venv/bin/gunicorn"
else
    PYTHON_BIN="python3"
    GUNICORN_BIN="gunicorn"
fi

export FLASK_APP=app.py
PORT="${PORT:-5000}"

echo "==================================================="
echo " Starting QueueX – CGC University Mohali"
echo " Portal: http://localhost:${PORT}"
echo "==================================================="

# If gunicorn is available, run via gunicorn, otherwise fallback to python
if [ -x "$GUNICORN_BIN" ] || command -v "$GUNICORN_BIN" &> /dev/null; then
    exec "$GUNICORN_BIN" --worker-class gthread --workers 1 --threads 20 --bind "0.0.0.0:${PORT}" app:app
else
    exec "$PYTHON_BIN" app.py
fi
