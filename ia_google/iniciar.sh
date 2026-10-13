#!/usr/bin/env bash
cd "$(dirname "$0")"
if [ ! -d .venv ]; then
  python3 -m venv .venv && source .venv/bin/activate
  pip install -r requirements.txt && playwright install chromium
else
  source .venv/bin/activate
fi
( sleep 2; xdg-open http://127.0.0.1:5000 2>/dev/null || open http://127.0.0.1:5000 ) &
python app.py
