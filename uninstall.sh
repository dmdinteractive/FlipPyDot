#!/bin/bash
# Stops FlipDot from starting at boot. Leaves the code, venv and ~/.flipdot config alone.
DAEMON="/Library/LaunchDaemons/com.flipdot.plist"
sudo launchctl bootout system/com.flipdot 2>/dev/null || true
sudo rm -f "$DAEMON"
echo "Boot service removed — FlipDot will no longer start at power-on."
echo "Run it by hand with ./start.sh, or re-enable with ./install.sh"
