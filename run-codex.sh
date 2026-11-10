#!/usr/bin/env bash
set -euo pipefail
task_root=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
exec /root/404-round4-venv/bin/python "$task_root/main.py" \
  --wallet-name sn118-miner \
  --wallet-hotkey default \
  --wallet-path /root/.bittensor/wallets \
  "$@"
