#!/usr/bin/env bash
# Stop the deployed stack. Data volumes are kept by default.
# Usage: bash scripts/stop.sh [--volumes]
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROJECT_NAME="${PROJECT_NAME:-hanson}"
ENV_FILE="${ENV_FILE:-.env}"
COMPOSE=(docker compose --project-name "$PROJECT_NAME" --env-file "$ENV_FILE" -f docker-compose.yml)

if [[ "${1:-}" == "--volumes" ]]; then
  echo "WARNING: this removes PostgreSQL, MinIO and agent-session volumes."
  read -r -p "type YES to continue: " answer
  [[ "$answer" == "YES" ]] || { echo "aborted"; exit 1; }
  "${COMPOSE[@]}" down --volumes --remove-orphans
else
  "${COMPOSE[@]}" down --remove-orphans
fi
