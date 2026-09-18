#!/usr/bin/env bash
set -e

DIR="/mnt/data/rj/email_auto/leadforge"
cd "$DIR"

mkdir -p logs

# Kill any existing instance
pkill -f "leadforge.daemon" || true
sleep 1

echo "Starting Orvion 24/7 Daemon (preventing lid-close sleep)..."
PYTHONPATH=. PYTHONUNBUFFERED=1 nohup systemd-inhibit --what=sleep:idle:handle-lid-switch --who="LeadForge" --why="24/7 Lead Outreach" python3 -u -m leadforge.daemon >> logs/daemon.log 2>&1 &

PID=$!
echo "Daemon started successfully! (PID: $PID)"
echo "Logs: tail -f logs/daemon.log"
