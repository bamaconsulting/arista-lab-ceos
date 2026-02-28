#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_ACTIVATE="$SCRIPT_DIR/.venv/bin/activate"

if [[ ! -f "$VENV_ACTIVATE" ]]; then
	echo "Virtual environment not found: $VENV_ACTIVATE"
	echo "Create it first with: python3 -m venv .venv"
	if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
		return 1
	fi
	exit 1
fi

activate_venv() {
	source "$VENV_ACTIVATE"
	hash -r
	echo "Activated venv: $VIRTUAL_ENV"
}

if [[ "${BASH_SOURCE[0]}" != "$0" ]]; then
	activate_venv
	return 0
fi

if [[ $# -gt 0 ]]; then
	activate_venv
	exec "$@"
fi

echo "This script cannot activate your current shell when run as './start-venv.sh'."
echo "Use one of these options:"
echo "  1) source ./start-venv.sh"
echo "  2) ./start-venv.sh <command>"
exit 1

