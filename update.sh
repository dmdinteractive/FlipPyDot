#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/.venv"
PLIST="$HOME/Library/LaunchAgents/com.flipdot.plist"
echo "Updating FlipDot from GitHub..."
cd "$DIR"
git fetch origin
git reset --hard origin/main
"$VENV/bin/pip" install --quiet -r requirements.txt
launchctl unload "$PLIST" 2>/dev/null || true
sleep 2
launchctl load "$PLIST"
echo "Done — service restarted"
