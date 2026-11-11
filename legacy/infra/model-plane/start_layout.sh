#!/usr/bin/env bash
# Start the PP-DocLayoutV3 HTTP shim on the model plane (default :9978).
set -euo pipefail

BACKEND_ROOT=${HANSONDOC_BACKEND:-/home/grainuser/hansonDoc_RAG/backend}
MODEL_DIR=${LAYOUT_MODEL_DIR:-/home/grainuser/hansonDoc_RAG/models/pp_doclayoutv3}
PYTHON=${PYTHON:-$BACKEND_ROOT/venv/bin/python}
PORT=${1:-9978}

export HANSONDOC_BACKEND="$BACKEND_ROOT"
export LAYOUT_MODEL_DIR="$MODEL_DIR"
export PYTHONPATH="$BACKEND_ROOT${PYTHONPATH:+:$PYTHONPATH}"

exec "$PYTHON" "$(dirname "$0")/serve_layout.py" --host 0.0.0.0 --port "$PORT"
