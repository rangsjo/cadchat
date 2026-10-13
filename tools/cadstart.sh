#!/usr/bin/env bash
# Start the cadchat viewer server if it is not already running, then print the URL.
cd "$(dirname "$0")/.." || exit 1
if ss -ltn 2>/dev/null | grep -q ':8765 '; then
  echo "cadchat already running: http://127.0.0.1:8765"
else
  (nohup .venv/bin/python tools/cadserver.py > /tmp/cadserver.log 2>&1 &)
  sleep 1.5
  cat /tmp/cadserver.log
fi
