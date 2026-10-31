#!/usr/bin/env bash

# Resolve project root directory
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PID_FILE="$PROJECT_DIR/.queuex.pid"
PORT="${PORT:-5000}"

echo "========================================"
echo " Stopping QueueX..."
echo "========================================"

STOPPED=0

# Check PID file
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "Sending stop signal to PID $PID..."
        kill "$PID" 2>/dev/null

        # Wait up to 5 seconds for graceful shutdown
        for i in {1..5}; do
            if ! kill -0 "$PID" 2>/dev/null; then
                STOPPED=1
                break
            fi
            sleep 1
        done

        # Force kill if still running
        if kill -0 "$PID" 2>/dev/null; then
            echo "Force terminating PID $PID..."
            kill -9 "$PID" 2>/dev/null
            STOPPED=1
        fi
    fi
    rm -f "$PID_FILE"
fi

# Fallback: check if any remaining process running QueueX is listening on the app port
PORT_PID=$(lsof -ti :"$PORT" 2>/dev/null)
if [ -n "$PORT_PID" ]; then
    if ps -p "$PORT_PID" -o command= 2>/dev/null | grep -q "app.py"; then
        echo "Stopping QueueX process $PORT_PID occupying port $PORT..."
        kill "$PORT_PID" 2>/dev/null
        sleep 1
        if kill -0 "$PORT_PID" 2>/dev/null; then
            kill -9 "$PORT_PID" 2>/dev/null
        fi
        STOPPED=1
    fi
fi

if [ $STOPPED -eq 1 ]; then
    echo "✅ QueueX stopped successfully."
else
    echo "ℹ️  QueueX is not currently running."
fi
