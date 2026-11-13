#!/bin/sh
# Start the gas agency site on http://127.0.0.1:8000
# First run asks for your secret key and dealer login and saves them to .env.
cd "$(dirname "$0")" || exit 1
if [ ! -d .venv ]; then
  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt || exit 1
fi
.venv/bin/python setup_env.py || exit 1
exec .venv/bin/python -m uvicorn app.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}"
