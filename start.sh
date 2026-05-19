#!/bin/bash
cd "$(dirname "$0")/backend"
if [ -f "../.env" ]; then
  export $(cat ../.env | xargs)
fi
python3 app.py
