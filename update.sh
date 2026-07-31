#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/.venv"
echo "Updating FlipDot from GitHub..."
cd "$DIR"
git fetch origin
git reset --hard origin/main
"$VENV/bin/pip" install --quiet -r requirements.txt
sudo launchctl kickstart -k system/com.flipdot
echo "Done — service restarted"
