#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PY_SCRIPT="$SCRIPT_DIR/fabric-pulse.py"

if [[ ! -f "$PY_SCRIPT" ]]; then
	echo "Missing script: $PY_SCRIPT"
	exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
	echo "python3 is required"
	exit 1
fi

if ! python3 -c "import pyeapi, rich" >/dev/null 2>&1; then
	echo "Missing dependencies: pyeapi and/or rich"
	echo "Install with: pip install pyeapi rich"
	exit 1
fi

cd "$REPO_ROOT"
exec python3 "$PY_SCRIPT" "$@"

