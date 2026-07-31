#!/bin/bash
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/.venv"
PORT="${FLIPDOT_WEB_PORT:-8080}"
DAEMON="/Library/LaunchDaemons/com.flipdot.plist"
OLD_AGENT="$HOME/Library/LaunchAgents/com.flipdot.plist"

if [ "$(id -u)" -eq 0 ]; then
  echo "Run this WITHOUT sudo — it will ask for your password when it needs it."
  exit 1
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  FLIPDOT CONSOLE V8 — INSTALLATION"
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

echo "[ 4/4 ] Installing boot service (needs admin password)..."

# Retire the old per-user LaunchAgent, which only ran after login.
if [ -f "$OLD_AGENT" ]; then
  launchctl bootout "gui/$(id -u)/com.flipdot" 2>/dev/null || launchctl unload "$OLD_AGENT" 2>/dev/null || true
  rm -f "$OLD_AGENT"
  echo "        Removed old login-time LaunchAgent"
fi

TMP_PLIST="$(mktemp)"
cat > "$TMP_PLIST" << PLIST
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
  <key>UserName</key><string>$USER</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>HOME</key><string>$HOME</string>
    <key>FLIPDOT_WEB_PORT</key><string>$PORT</string>
    <key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin:/usr/local/bin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>5</integer>
  <key>StandardOutPath</key><string>$DIR/logs/stdout.log</string>
  <key>StandardErrorPath</key><string>$DIR/logs/stderr.log</string>
</dict></plist>
PLIST

plutil -lint "$TMP_PLIST" > /dev/null
sudo cp "$TMP_PLIST" "$DAEMON"
sudo chown root:wheel "$DAEMON"
sudo chmod 644 "$DAEMON"
rm -f "$TMP_PLIST"

sudo launchctl bootout system/com.flipdot 2>/dev/null || true
sudo launchctl bootstrap system "$DAEMON"
echo "        Service installed — starts at power-on, no login required"

case "$DIR" in
  "$HOME"/Desktop/*|"$HOME"/Documents/*|"$HOME"/Downloads/*)
    echo ""
    echo "  ! This folder lives under a macOS privacy-protected directory."
    echo "    Grant Full Disk Access to:"
    echo "      $VENV/bin/python3"
    echo "    (System Settings > Privacy & Security > Full Disk Access > +,"
    echo "     press Cmd+Shift+G and paste the path above), then run:"
    echo "      sudo launchctl kickstart -k system/com.flipdot"
    echo "    Or move this folder somewhere like /usr/local/flipdot and re-run install.sh."
    ;;
esac

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  DONE. Open http://$(scutil --get LocalHostName).local:$PORT"
echo "  Or:   http://$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null):$PORT"
echo ""
echo "  Status:  sudo launchctl print system/com.flipdot | head -20"
echo "  Restart: sudo launchctl kickstart -k system/com.flipdot"
echo "  Logs:    tail -f $DIR/logs/stderr.log"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
