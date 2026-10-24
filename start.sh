#!/usr/bin/env bash

# Resolve project root directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$PROJECT_DIR/.queuex.pid"
LOG_FILE="$PROJECT_DIR/queuex.log"
PORT="${PORT:-5000}"

echo "========================================"
echo " Starting QueueX..."
echo "========================================"

# Check if already running via PID file
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "⚠️  QueueX is already running (PID: $PID) at http://127.0.0.1:$PORT"
        exit 0
    else
        # Stale PID file
        rm -f "$PID_FILE"
    fi
fi

# Check if port is already in use by another process
PORT_PID=$(lsof -ti :"$PORT" 2>/dev/null)
if [ -n "$PORT_PID" ]; then
    echo "⚠️  Port $PORT is already in use by process $PORT_PID."
    echo "   Run ./stop.sh or check with: lsof -i :$PORT"
    exit 1
fi

# Locate Python environment
if [ -f "$PROJECT_DIR/venv/bin/python" ]; then
    PYTHON_BIN="$PROJECT_DIR/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="$(command -v python3)"
else
    echo "❌ Python 3 not found. Please install Python 3 or create a virtualenv at ./venv"
    exit 1
fi

# Set default environment variables
export PORT="$PORT"
export FLASK_DEBUG="${FLASK_DEBUG:-0}"
export QUEUEX_DB="${QUEUEX_DB:-database.db}"
export PYTHONUNBUFFERED=1

# Start QueueX in background
cd "$PROJECT_DIR"
nohup "$PYTHON_BIN" app.py >> "$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > "$PID_FILE"

# Wait briefly to confirm it didn't crash on startup
sleep 3

if kill -0 "$SERVER_PID" 2>/dev/null; then
    echo "✅ QueueX started successfully!"
    echo "   • PID:  $SERVER_PID"
    echo "   • URL:  http://127.0.0.1:$PORT"
    echo "   • Logs: $LOG_FILE"
    echo ""
    echo "To view live logs: tail -f $LOG_FILE"
    echo "To stop the server: ./stop.sh"
else
    echo "❌ QueueX failed to start. Last log lines:"
    echo "----------------------------------------"
    tail -n 20 "$LOG_FILE" 2>/dev/null
    rm -f "$PID_FILE"
    exit 1
fi
