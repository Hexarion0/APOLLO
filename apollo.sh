#!/usr/bin/env bash
# Local APOLLO CLI Launcher
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ -f "$SCRIPT_DIR/.venv/bin/python" ]; then
    PYTHON_EXEC="$SCRIPT_DIR/.venv/bin/python"
else
    PYTHON_EXEC="python3"
fi

exec "$PYTHON_EXEC" -m apollo.cli "$@"
