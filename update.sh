#!/bin/bash
# Pull the latest code for whichever branch this install is on (main, or a
# test branch like v9-revamp), reinstall dependencies, restart the service.
DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/.venv"
cd "$DIR"
BRANCH="$(git rev-parse --abbrev-ref HEAD)"
echo "Updating FlipDot ($BRANCH) from GitHub..."
git fetch origin "$BRANCH"
git reset --hard "origin/$BRANCH"
"$VENV/bin/pip" install --quiet -r requirements.txt
sudo launchctl kickstart -k system/com.flipdot
echo "Done — service restarted"
