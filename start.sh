#!/bin/sh
set -eu
cd "$(dirname "$0")"
test -d .venv || python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python scripts/fetch_assets.py
exec .venv/bin/python run.py
