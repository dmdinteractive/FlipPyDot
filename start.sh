#!/bin/bash
# start.sh — Open the interactive FlipDot console
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$SCRIPT_DIR/.venv"

if [ ! -d "$VENV" ]; then
    echo "Virtual environment not found. Run ./install.sh first."
    exit 1
fi

exec "$VENV/bin/python3" "$SCRIPT_DIR/flipdot.py" "$@"
