#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/.venv"
if [ ! -d "$VENV" ]; then echo "Run ./install.sh first"; exit 1; fi
export FLIPDOT_WEB_PORT="${FLIPDOT_WEB_PORT:-8080}"
exec "$VENV/bin/python3" "$DIR/app.py"
