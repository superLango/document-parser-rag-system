#!/usr/bin/env bash
# Check model server endpoints from the application host.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MODEL_HOST="${MODEL_HOST:-192.168.1.35}" bash "$ROOT/models/check-models.sh"
