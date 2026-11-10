#!/usr/bin/env bash
# Start the PP-DocLayoutV3 shim on GPU (default :9979).
# The engine uses this as LAYOUT_SERVICE_URL (primary) and falls back to the
# CPU shim on :9978 (LAYOUT_SERVICE_FALLBACK_URL).
set -euo pipefail

PORT=${1:-9979}
export LAYOUT_DEVICE=${LAYOUT_DEVICE:-cuda:0}

exec "$(dirname "$0")/start_layout.sh" "$PORT"
