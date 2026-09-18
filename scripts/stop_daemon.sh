#!/usr/bin/env bash
echo "Stopping Orvion Daemon..."
pkill -f "leadforge.daemon" && echo "Daemon stopped." || echo "No active daemon found."
