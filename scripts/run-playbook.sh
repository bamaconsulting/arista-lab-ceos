#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLAYBOOKS_DIR="$PROJECT_ROOT/playbooks"

print_available_playbooks() {
    echo "Available playbooks in $PLAYBOOKS_DIR:"
    if compgen -G "$PLAYBOOKS_DIR/*.yml" > /dev/null; then
        ls -1 "$PLAYBOOKS_DIR"/*.yml | xargs -n1 basename
    else
        echo "  (none found)"
    fi
}

choose_playbook_interactively() {
    local -a playbooks
    local i choice selected

    mapfile -t playbooks < <(find "$PLAYBOOKS_DIR" -maxdepth 1 -type f -name '*.yml' -printf '%f\n' | sort)

    if [[ ${#playbooks[@]} -eq 0 ]]; then
        echo "No playbooks found in $PLAYBOOKS_DIR"
        exit 1
    fi

    echo "Select a playbook to run:"
    for i in "${!playbooks[@]}"; do
        printf '[%d] %s\n' "$((i + 1))" "${playbooks[$i]}"
    done

    while true; do
        if ! read -r -p "Enter playbook number (1-${#playbooks[@]}): " choice; then
            echo
            echo "No selection received. Exiting."
            exit 1
        fi

        if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#playbooks[@]} )); then
            selected="${playbooks[$((choice - 1))]}"
            echo "Selected: $selected"
            PLAYBOOK_INPUT="$selected"
            return 0
        fi

        echo "Invalid selection. Please enter a number from 1 to ${#playbooks[@]}."
    done
}

print_similar_playbooks() {
    local requested="$1"
    local requested_noext requested_norm
    local file name name_noext name_norm
    local -a matches=()

    requested_noext="${requested%.yml}"
    requested_norm="${requested_noext//-/_}"

    while IFS= read -r file; do
        name="$(basename "$file")"
        name_noext="${name%.yml}"
        name_norm="${name_noext//-/_}"

        if [[ "$name_noext" == *"$requested_noext"* ]] || [[ "$name_norm" == *"$requested_norm"* ]] || [[ "$requested_norm" == *"$name_norm"* ]]; then
            matches+=("$name")
        fi
    done < <(find "$PLAYBOOKS_DIR" -maxdepth 1 -type f -name '*.yml' | sort)

    if [[ ${#matches[@]} -gt 0 ]]; then
        echo "Did you mean one of these?"
        printf '  %s\n' "${matches[@]}"
    fi
}

if [[ $# -lt 1 ]]; then
    choose_playbook_interactively
else
    PLAYBOOK_INPUT="$1"
    shift
fi

if [[ "$PLAYBOOK_INPUT" == */* ]]; then
    echo "Please provide only the playbook file name (without path)."
    echo "Example: $0 03_deploy_configs.yml"
    print_available_playbooks
    exit 1
fi

PLAYBOOK_FILE="$PLAYBOOK_INPUT"
if [[ "$PLAYBOOK_FILE" != *.yml ]]; then
    PLAYBOOK_FILE="${PLAYBOOK_FILE}.yml"
fi

PLAYBOOK_PATH="$PLAYBOOKS_DIR/$PLAYBOOK_FILE"

if [[ ! -f "$PLAYBOOK_PATH" ]]; then
    echo "Playbook not found: $PLAYBOOK_FILE"
    print_similar_playbooks "$PLAYBOOK_FILE"
    print_available_playbooks
    exit 1
fi

mkdir -p "$PROJECT_ROOT/logs"

PLAYBOOK_NAME="$(basename "$PLAYBOOK_PATH" .yml)"
TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
LOG_FILE="$PROJECT_ROOT/logs/${PLAYBOOK_NAME}_${TIMESTAMP}.log"
LATEST_LINK="$PROJECT_ROOT/logs/${PLAYBOOK_NAME}_latest.log"

echo "Running: $PLAYBOOK_PATH"
echo "Project root: $PROJECT_ROOT"
echo "Log: $LOG_FILE"

ANSIBLE_PLAYBOOK_BIN="ansible-playbook"
if [[ -x "$PROJECT_ROOT/.venv/bin/ansible-playbook" ]]; then
    ANSIBLE_PLAYBOOK_BIN="$PROJECT_ROOT/.venv/bin/ansible-playbook"
fi

echo "Using ansible-playbook: $ANSIBLE_PLAYBOOK_BIN"

set +e
(
    cd "$PROJECT_ROOT"
    ANSIBLE_CONFIG="$PROJECT_ROOT/ansible.cfg" \
    ANSIBLE_LOG_PATH="$LOG_FILE" \
    "$ANSIBLE_PLAYBOOK_BIN" "$PLAYBOOK_PATH" "$@"
)
EXIT_CODE=$?
set -e

ln -sfn "$(basename "$LOG_FILE")" "$LATEST_LINK"

if [[ $EXIT_CODE -eq 0 ]]; then
    echo "Playbook completed successfully."
else
    echo "Playbook failed (exit code: $EXIT_CODE)."
fi

echo "Saved log: $LOG_FILE"
echo "Latest log link: $LATEST_LINK"

exit "$EXIT_CODE"
