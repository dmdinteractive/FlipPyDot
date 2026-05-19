#!/bin/bash
# install.sh — FlipDot CLI one-time setup
# Run once on the Mac mini. Safe to run again — it skips steps already done.

set -e  # Exit on error

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/.venv"
PLIST_SRC="$SCRIPT_DIR/com.flipdot.plist"
PLIST_DST="$HOME/Library/LaunchAgents/com.flipdot.plist"

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  FLIPDOT CLI — INSTALLATION"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Step 1: Virtual environment ───────────────────────────────────
echo "[ 1/5 ] Creating virtual environment..."
if [ ! -d "$VENV" ]; then
    python3 -m venv "$VENV"
    echo "        Created: $VENV"
else
    echo "        Already exists: $VENV"
fi

# ── Step 2: Install dependencies ──────────────────────────────────
echo "[ 2/5 ] Installing dependencies..."
"$VENV/bin/pip" install --quiet --upgrade pip
"$VENV/bin/pip" install --quiet -r "$SCRIPT_DIR/requirements.txt"
echo "        Done"

# ── Step 3: Create required directories ───────────────────────────
echo "[ 3/5 ] Creating directories..."
mkdir -p "$SCRIPT_DIR/shows"
mkdir -p "$SCRIPT_DIR/assets"
mkdir -p "$SCRIPT_DIR/fonts"
mkdir -p "$SCRIPT_DIR/logs"
mkdir -p "$SCRIPT_DIR/scripts"
mkdir -p "$HOME/.flipdot"
echo "        Done"

# ── Step 4: First-run config ──────────────────────────────────────
echo "[ 4/5 ] Configuration..."
CONFIG_FILE="$HOME/.flipdot/config.json"
if [ ! -f "$CONFIG_FILE" ]; then
    echo "        Running first-time setup..."
    "$VENV/bin/python3" "$SCRIPT_DIR/flipdot.py" --setup
else
    echo "        Config already exists: $CONFIG_FILE"
    echo "        (Run './flipdot.py --setup' to reconfigure)"
fi

# ── Step 5: Install launchd service ──────────────────────────────
echo "[ 5/5 ] Installing launchd service..."
mkdir -p "$HOME/Library/LaunchAgents"

# Generate the plist with actual paths filled in
cat > "$PLIST_DST" << PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.flipdot</string>

    <key>ProgramArguments</key>
    <array>
        <string>$VENV/bin/python3</string>
        <string>$SCRIPT_DIR/watchdog.py</string>
        <string>--daemon</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$SCRIPT_DIR</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>ThrottleInterval</key>
    <integer>5</integer>

    <key>StandardOutPath</key>
    <string>$SCRIPT_DIR/logs/launchd_stdout.log</string>

    <key>StandardErrorPath</key>
    <string>$SCRIPT_DIR/logs/launchd_stderr.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>$VENV/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>
</dict>
</plist>
PLIST

# Unload existing service if running
launchctl unload "$PLIST_DST" 2>/dev/null || true

# Load the new service
launchctl load "$PLIST_DST"
echo "        Service installed and started"
echo "        Auto-starts on login/reboot"

# ── Summary ───────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  INSTALLATION COMPLETE"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  The flipdot daemon is now running and will"
echo "  restart automatically on crash or reboot."
echo ""
echo "  To open the interactive console:"
echo "    ./start.sh"
echo ""
echo "  To send a command to the daemon:"
echo "    echo 'text Hello' | nc -U /tmp/flipdot.sock"
echo ""
echo "  To check status:"
echo "    echo 'status' | nc -U /tmp/flipdot.sock"
echo ""
echo "  To update from GitHub:"
echo "    ./update.sh"
echo ""
