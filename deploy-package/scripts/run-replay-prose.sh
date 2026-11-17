set -eu
cd /mnt/f/hanson/hanson_doc_parse
ONLY="${ONLY:-}"
OUT="${OUT:-/out/prose-replay.json}"
docker run --rm -w /app \
  -e PYTHONPATH=/data/new_app:/app:/app/packages/contracts/src:/app/packages/domain/src:/app/packages/observability/src \
  -e REPLAY_RUNTIME_DIR=/data/new_app/services/sandbox/runtime \
  -v /mnt/f/hanson/hanson_doc_parse:/data:ro \
  -v /mnt/f/hanson/hanson_doc_parse/deploy-package/reports:/out \
  --entrypoint python hanson-new-app:dev-amd64 \
  /data/deploy-package/scripts/replay_prose_gold.py \
  --root /data/gold_standard_30 --only "$ONLY" --out "$OUT"
