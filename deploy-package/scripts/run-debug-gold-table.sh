set -eu
cd /mnt/f/hanson/hanson_doc_parse
docker run --rm -w /app \
  -e PYTHONPATH=/data/new_app:/app:/app/packages/contracts/src:/app/packages/domain/src:/app/packages/observability/src \
  -e REPLAY_RUNTIME_DIR=/data/new_app/services/sandbox/runtime \
  -e REPLAY_RECIPE_DIR=/data/new_app/services/recipe_registry/data/recipes \
  -v /mnt/f/hanson/hanson_doc_parse:/data:ro \
  --entrypoint python hanson-new-app:dev-amd64 \
  /data/deploy-package/scripts/debug_gold_table.py "$@"
