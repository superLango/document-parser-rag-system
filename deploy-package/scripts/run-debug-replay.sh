set -eu
cd /mnt/f/hanson/hanson_doc_parse
docker run --rm -w /data/new_app \
  -e PYTHONPATH=/data/new_app:/data/new_app/packages/contracts/src:/data/new_app/packages/domain/src:/data/new_app/packages/observability/src:/app \
  -e REPLAY_RUNTIME_DIR=/data/new_app/services/sandbox/runtime \
  -e REPLAY_RECIPE_DIR=/data/new_app/services/recipe_registry/data/recipes \
  -v /mnt/f/hanson/hanson_doc_parse:/data:ro \
  --entrypoint python hanson-new-app:local \
  /data/deploy-package/scripts/debug_replay_doc.py
