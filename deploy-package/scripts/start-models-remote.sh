#!/usr/bin/env bash
# Copy model scripts to the model server and start all three services.
# Run from the deployment package root on the application host.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_HOST="${MODEL_HOST:-grainuser@192.168.1.35}"
REMOTE_DIR="${REMOTE_DIR:-/home/grainuser/hanson-model-scripts}"

echo "copying model scripts to ${MODEL_HOST}:${REMOTE_DIR}"
tar -C "$ROOT/models" -cf - . | ssh "$MODEL_HOST" "mkdir -p '$REMOTE_DIR' && tar -C '$REMOTE_DIR' -xf -"

echo "starting model services on ${MODEL_HOST}"
ssh "$MODEL_HOST" "bash '$REMOTE_DIR/start-all.sh'"
