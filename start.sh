#!/bin/bash
DIR="$(cd "$(dirname "$0")" && pwd)"
VENV="$DIR/.venv"
if [ ! -d "$VENV" ]; then echo "Run ./install.sh first"; exit 1; fi
exec "$VENV/bin/python3" "$DIR/app.py"
