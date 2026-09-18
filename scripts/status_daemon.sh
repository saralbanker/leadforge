#!/usr/bin/env bash
PID=$(pgrep -f "leadforge.daemon" || true)
if [ -n "$PID" ]; then
    echo "Orvion Daemon is RUNNING (PID: $PID)"
    echo "Recent activity:"
    tail -n 10 /mnt/data/rj/email_auto/leadforge/logs/daemon.log 2>/dev/null || true
else
    echo "Orvion Daemon is STOPPED."
fi
