#!/usr/bin/env bash
# Launches SE Manager Hub, waits for it to answer, curls two endpoints, stops it.
# Run from the se-manager-hub project root:
#   .claude/skills/run-se-manager-hub/smoke.sh
set -euo pipefail

PORT="${PORT:-5050}"
LOG=/tmp/se-manager-hub.log

venv/Scripts/python.exe app.py &> "$LOG" &
SERVER_PID=$!
echo "started pid $SERVER_PID, log: $LOG"

for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:${PORT}/api/settings" > /dev/null; then
    echo "up after ${i}s"
    break
  fi
  sleep 1
done

echo "-- /api/settings --"
curl -s "http://127.0.0.1:${PORT}/api/settings"
echo
echo "-- /api/reps (first 500 bytes) --"
curl -s "http://127.0.0.1:${PORT}/api/reps" | head -c 500
echo

kill "$SERVER_PID" 2>/dev/null || true
