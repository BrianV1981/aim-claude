#!/usr/bin/env bash
# Run the full aim-claude test suite using the project venv.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AIM_ROOT="$(dirname "$SCRIPT_DIR")"
PYTHON="$AIM_ROOT/venv/bin/python3"

if [ ! -x "$PYTHON" ]; then
    echo "[ERROR] venv not found at $AIM_ROOT/venv — run: python3 -m venv venv && venv/bin/pip install -r requirements.txt"
    exit 1
fi

exec "$PYTHON" -m pytest "$AIM_ROOT/tests/" -v --tb=short "$@"
