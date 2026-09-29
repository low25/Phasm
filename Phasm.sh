#!/usr/bin/env bash
# Launch Phasm from any working directory.

set -Eeuo pipefail

# Resolve the project directory from this script rather than from the caller's
# current directory. This keeps config, artwork, sounds, and emulators working
# when the launcher is started from a desktop shortcut or file manager.
SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
cd "$SCRIPT_DIR"

# A project-local virtual environment takes priority. Set PYTHON_BIN to use a
# specific interpreter, otherwise fall back to the system's python3.
if [[ -n "${PYTHON_BIN:-}" ]]; then
    PYTHON="${PYTHON_BIN}"
elif [[ -x "$SCRIPT_DIR/.venv/bin/python" ]]; then
    PYTHON="$SCRIPT_DIR/.venv/bin/python"
elif [[ -x "$SCRIPT_DIR/venv/bin/python" ]]; then
    PYTHON="$SCRIPT_DIR/venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON="$(command -v python3)"
else
    printf '%s\n' 'Phasm: Python 3 is required but was not found.' >&2
    exit 127
fi

if [[ ! -x "$PYTHON" ]]; then
    printf 'Phasm: Python interpreter is not executable: %s\n' "$PYTHON" >&2
    exit 126
fi

# Keep the launcher's terminal behavior transparent and forward every option
# (for example: ./Phasm.sh --check).
exec "$PYTHON" "$SCRIPT_DIR/main.py" "$@"
