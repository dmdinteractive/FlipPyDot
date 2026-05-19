#!/bin/bash
# update.sh — Pull latest from GitHub without conflicts
# Uses reset --hard so there can never be a merge conflict.
# Config in ~/.flipdot/ is never touched.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/.venv"

echo "Updating FlipDot from GitHub..."
cd "$SCRIPT_DIR"

# Fetch and reset — never conflicts
git fetch origin
git reset --hard origin/main

echo "Installing any new dependencies..."
"$VENV/bin/pip" install --quiet -r requirements.txt

echo "Restarting service..."
PLIST="$HOME/Library/LaunchAgents/com.flipdot.plist"
if [ -f "$PLIST" ]; then
    launchctl unload "$PLIST" 2>/dev/null || true
    sleep 2
    launchctl load "$PLIST"
    echo "Service restarted"
else
    echo "Service not installed — run ./install.sh"
fi

echo "Update complete"
