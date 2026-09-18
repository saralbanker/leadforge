#!/usr/bin/env bash
# 8am entry point.
#
# Two things happen here, in this order and independently:
#   1. The deterministic outreach run. This must happen whether or not anyone is
#      logged in, so it runs headless and logs to logs/daily/.
#   2. An interactive Claude Code panel, opened only if a graphical session
#      actually exists. A missing display must never block (1).
set -uo pipefail

REPO=/mnt/data/rj/email_auto/leadforge
LOGDIR="$REPO/logs/daily"
STAMP=$(date +%Y-%m-%d)
LOG="$LOGDIR/$STAMP.log"
mkdir -p "$LOGDIR"

cd "$REPO" || exit 1

{
  echo "==================== $(date -Is) ===================="
  timeout 10800 python scripts/daily_outreach.py --pairs 4
  echo "exit=$? at $(date -Is)"
} >>"$LOG" 2>&1

# Retain two months of run logs; they are the only record of what was sent.
find "$LOGDIR" -name '*.log' -mtime +60 -delete 2>/dev/null

# --- interactive panel, best effort -----------------------------------------
have_display() {
  [ -n "${WAYLAND_DISPLAY:-}" ] && [ -S "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}/${WAYLAND_DISPLAY}" ] && return 0
  [ -n "${DISPLAY:-}" ] && return 0
  return 1
}

if ! have_display; then
  for sock in /run/user/$(id -u)/wayland-*; do
    case "$sock" in *.lock) continue;; esac
    [ -S "$sock" ] || continue
    export WAYLAND_DISPLAY="$(basename "$sock")"
    export XDG_RUNTIME_DIR="/run/user/$(id -u)"
    break
  done
fi

if have_display && command -v kitty >/dev/null 2>&1; then
  kitty --detach --title "LeadForge morning run" --directory "$REPO" -- \
    claude --dangerously-skip-permissions \
    "Read .mission/DAILY.md and carry out today's outreach review. The unattended run for $STAMP has already finished; its log is logs/daily/$STAMP.log. Start by reading that log." \
    >>"$LOG" 2>&1 || echo "panel launch failed" >>"$LOG"
else
  echo "no graphical session; skipped interactive panel" >>"$LOG"
fi
