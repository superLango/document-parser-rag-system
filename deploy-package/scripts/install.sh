#!/usr/bin/env bash
# One-time installation: check runtime, load images, create .env.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

command -v docker >/dev/null || { echo "docker not found" >&2; exit 1; }
docker compose version >/dev/null || { echo "docker compose plugin not found" >&2; exit 1; }

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "created .env from .env.example; review model endpoints and passwords before starting"
fi

bash scripts/load-images.sh "${1:-}"

echo
echo "install checks passed."
echo "next: edit .env, then run: bash scripts/start.sh"
