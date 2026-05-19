#!/bin/bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/.venv"
PLIST="$HOME/Library/LaunchAgents/com.flipdot.plist"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  FLIPDOT CONSOLE V7 — INSTALLATION"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

echo "[ 1/4 ] Creating virtual environment..."
[ ! -d "$VENV" ] && python3 -m venv "$VENV" && echo "        Created" || echo "        Already exists"

echo "[ 2/4 ] Installing dependencies..."
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$DIR/requirements.txt"
echo "        Done"

echo "[ 3/4 ] Creating directories..."
mkdir -p "$DIR/shows" "$DIR/assets" "$DIR/fonts" "$DIR/logs" "$HOME/.flipdot"
echo "        Done"

echo "[ 4/4 ] Installing launchd service..."
mkdir -p "$HOME/Library/LaunchAgents"
cat > "$PLIST" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.flipdot</string>
  <key>ProgramArguments</key>
  <array>
    <string>$VENV/bin/python3</string>
    <string>$DIR/app.py</string>
  </array>
  <key>WorkingDirectory</key><string>$DIR</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>5</integer>
  <key>StandardOutPath</key><string>$DIR/logs/stdout.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/stderr.log</string>
</dict></plist>
PLIST
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "        Service installed and started"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  DONE. Open http://$(hostname).local:5000"
echo "  Or:   http://$(ipconfig getifaddr en0):5000"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
