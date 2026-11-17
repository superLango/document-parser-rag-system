#!/usr/bin/env bash
# Start the deployed stack.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROJECT_NAME="${PROJECT_NAME:-hanson}"
ENV_FILE="${ENV_FILE:-.env}"
COMPOSE=(docker compose --project-name "$PROJECT_NAME" --env-file "$ENV_FILE" -f docker-compose.yml)

[[ -f "$ENV_FILE" ]] || { echo "missing $ENV_FILE; copy .env.example first" >&2; exit 1; }
docker image inspect hanson-sandbox-runtime:local >/dev/null 2>&1 || {
  echo "missing hanson-sandbox-runtime:local; run scripts/load-images.sh" >&2
  exit 1
}

"${COMPOSE[@]}" up -d

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
GATEWAY_PORT="${GATEWAY_PORT:-18000}"
WEB_PORT="${WEB_PORT:-15173}"

echo "waiting for gateway :${GATEWAY_PORT} and web :${WEB_PORT}"
for _ in $(seq 1 60); do
  gateway_ok=0
  web_ok=0
  curl -fsS --max-time 3 "http://127.0.0.1:${GATEWAY_PORT}/healthz" >/dev/null 2>&1 && gateway_ok=1
  curl -fsS --max-time 3 "http://127.0.0.1:${WEB_PORT}/healthz" >/dev/null 2>&1 && web_ok=1
  if [[ "$gateway_ok" == "1" && "$web_ok" == "1" ]]; then
    echo "stack is up:"
    echo "  API:  http://<host>:${GATEWAY_PORT}"
    echo "  Web:  http://<host>:${WEB_PORT}"
    exit 0
  fi
  sleep 3
done

echo "stack did not become healthy in time; inspect: ${COMPOSE[*]} ps" >&2
"${COMPOSE[@]}" ps >&2 || true
exit 1
