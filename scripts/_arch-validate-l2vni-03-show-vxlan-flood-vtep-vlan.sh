#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY_SCRIPT="$SCRIPT_DIR/validate-l2vni-03-show-vxlan-flood-vtep-vlan.py"
VENV_PYTHON="$SCRIPT_DIR/../.venv/bin/python"

if [[ -x "$VENV_PYTHON" ]]; then
	exec "$VENV_PYTHON" "$PY_SCRIPT" "$@"
fi

exec python3 "$PY_SCRIPT" "$@"

