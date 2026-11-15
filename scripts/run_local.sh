#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/../services/api"
if [[ ! -d .venv ]]; then python3 -m venv .venv; fi
source .venv/bin/activate
python -m pip install -e '.[dev,mcp]'
exec python -m shiyi_api.local_runtime "$@"
