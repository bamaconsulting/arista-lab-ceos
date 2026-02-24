#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

PLAYBOOKS=(
    "playbooks/01_build_structured_configs.yml"
    "playbooks/02_build_device_cli.yml"
    "playbooks/03_deploy_configs.yml"
    "playbooks/04_validate_fabric.yml"
)

for playbook in "${PLAYBOOKS[@]}"; do
    "$SCRIPT_DIR/run-playbook.sh" "$playbook"
done

echo "All playbooks finished successfully."
