set -eu
cd /mnt/f/hanson/hanson_doc_parse
docker run --rm -w /app \
  -e PYTHONPATH=/app:/app/packages/contracts/src:/app/packages/domain/src:/app/packages/observability/src \
  -v /mnt/f/hanson/hanson_doc_parse:/data:ro \
  --entrypoint python hanson-new-app:dev-amd64 \
  -m ruff check --no-cache \
  /data/new_app/services/sandbox/runtime/builtin.py \
  /data/new_app/services/sandbox/runtime/clauses.py \
  /data/new_app/services/sandbox/runtime/inventory.py \
  /data/new_app/services/sandbox/runtime/projection.py \
  /data/new_app/services/sandbox/runtime/references.py \
  /data/new_app/services/recipe_registry/matcher.py \
  /data/deploy-package/scripts/replay_md_parse.py \
  /data/deploy-package/scripts/replay_gold30.py
