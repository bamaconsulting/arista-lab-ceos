#!/usr/bin/env bash

set -euo pipefail

if [[ $# -lt 1 ]]; then
    echo "Usage: $0 <playbook.yml> [ansible-playbook-args...]"
    exit 1
fi

PLAYBOOK_PATH="$1"
shift

if [[ ! -f "$PLAYBOOK_PATH" ]]; then
    echo "Playbook not found: $PLAYBOOK_PATH"
    exit 1
fi

LOG_DIR="logs"
mkdir -p "$LOG_DIR"

PLAYBOOK_NAME="$(basename "$PLAYBOOK_PATH" .yml)"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="$LOG_DIR/${PLAYBOOK_NAME}_${TIMESTAMP}.log"
LATEST_LINK="$LOG_DIR/${PLAYBOOK_NAME}_latest.log"

echo "Running $PLAYBOOK_PATH"
echo "Log file: $LOG_FILE"

set +e
ANSIBLE_LOG_PATH="$LOG_FILE" ansible-playbook "$PLAYBOOK_PATH" "$@"
EXIT_CODE=$?
set -e

ln -sfn "$(basename "$LOG_FILE")" "$LATEST_LINK"

if [[ $EXIT_CODE -eq 0 ]]; then
    echo "Playbook finished successfully."
else
    echo "Playbook failed with exit code $EXIT_CODE."
fi

echo "Saved log: $LOG_FILE"
echo "Latest log link: $LATEST_LINK"

exit "$EXIT_CODE"
