#!/usr/bin/env bash
# Show container status, public health and model connectivity.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PROJECT_NAME="${PROJECT_NAME:-hanson}"
ENV_FILE="${ENV_FILE:-.env}"
COMPOSE=(docker compose --project-name "$PROJECT_NAME" --env-file "$ENV_FILE" -f docker-compose.yml)

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a
GATEWAY_PORT="${GATEWAY_PORT:-18000}"
WEB_PORT="${WEB_PORT:-15173}"

echo "== containers =="
"${COMPOSE[@]}" ps

echo
echo "== public health =="
for item in "gateway http://127.0.0.1:${GATEWAY_PORT}/healthz" "web http://127.0.0.1:${WEB_PORT}/healthz"; do
  name="${item%% *}"
  url="${item#* }"
  if curl -fsS --max-time 3 "$url" >/dev/null 2>&1; then
    echo "OK   $name $url"
  else
    echo "FAIL $name $url"
  fi
done

if docker image inspect hanson-sandbox-runtime:local >/dev/null 2>&1; then
  echo "OK   sandbox runtime image present"
else
  echo "FAIL sandbox runtime image missing"
fi

echo
echo "== model endpoints =="
MODEL_HOST="${MODEL_HOST:-192.168.1.35}" bash models/check-models.sh || true
