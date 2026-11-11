#!/usr/bin/env bash
# K8s 注册中心验证：API 冒烟 + 端到端 + routing artifact 内容。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NEW_APP_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
NAMESPACE="${NAMESPACE:-hanson-standard}"
export PATH="$PATH:$HOME/.local/bin"

kubectl -n "$NAMESPACE" port-forward svc/recipe-registry 18015:8005 \
  >/tmp/recipe-port-forward.log 2>&1 &
PF_PID=$!
trap 'kill "$PF_PID" 2>/dev/null || true' EXIT

for _ in $(seq 1 20); do
  if curl -fsS http://localhost:18015/healthz >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done

echo "[1/3] 注册中心 API"
BASE_URL=http://localhost:18015 bash "$SCRIPT_DIR/recipe-check.sh" | tail -8

echo "[2/3] 端到端"
bash "$SCRIPT_DIR/k8s-e2e.sh" "$NEW_APP_DIR/tests/fixtures/ocr/mechanical.md" \
  | grep -E "document_id|run_id|status=|E2E" | head -6

echo "[3/3] routing artifact"
kubectl -n "$NAMESPACE" exec -i deploy/orchestration -- python - <<'PY'
import asyncio
import json

from sqlalchemy import select

from services.orchestration.config import settings
from services.orchestration.db import SessionLocal
from services.orchestration.models import Artifact
from services.shared.storage import build_store


async def main() -> None:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Artifact)
            .where(Artifact.role == "routing")
            .order_by(Artifact.created_at.desc())
        )
        artifact = result.scalars().first()
    if artifact is None:
        print("  no routing artifact")
        return
    store = build_store(settings.storage_config())
    data = json.loads(await store.get_bytes(artifact.storage_key))
    print("  assignments =", json.dumps(data.get("assignments"), ensure_ascii=False))
    print("  confidence =", data.get("confidence"))
    matches = [item for item in data.get("assignments") or [] if item.get("recipe_id")]
    print("  matched =", len(matches), "of", len(data.get("assignments") or []))


asyncio.run(main())
PY

echo "[recipe] K8S CHECK DONE"
