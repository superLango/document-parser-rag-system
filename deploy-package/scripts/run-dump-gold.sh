set -eu
cd /mnt/f/hanson/hanson_doc_parse
DATA="${DATA:-/data/标准拆分提取-20261117-094032}"
FOLDERS="${FOLDERS:-1,9,57,197}"
OUT="${OUT:-/out/replay-gold-overlap.json}"
INV="${INV:-}"
RT="${RT:-/data/new_app/services/sandbox/runtime}"
docker run --rm -w /app \
  -e PYTHONPATH=/data/new_app:/app:/app/packages/contracts/src:/app/packages/domain/src:/app/packages/observability/src \
  -e REPLAY_RUNTIME_DIR="$RT" \
  -e REPLAY_RECIPE_DIR=/data/new_app/services/recipe_registry/data/recipes \
  -v /mnt/f/hanson/hanson_doc_parse:/data:ro \
  -v /mnt/f/hanson/hanson_doc_parse/deploy-package/reports:/out \
  --entrypoint python hanson-new-app:dev-amd64 \
  /data/deploy-package/scripts/replay_md_parse.py \
  --docs "$DATA" --folders "$FOLDERS" --dump ${INV:+--dump-inventory} \
  --out "$OUT"
