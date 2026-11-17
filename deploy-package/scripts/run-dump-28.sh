set -eu
cd /mnt/f/hanson/hanson_doc_parse
docker run --rm -w /app \
  -e PYTHONPATH=/app:/app/packages/contracts/src:/app/packages/domain/src:/app/packages/observability/src \
  -v /mnt/f/hanson/hanson_doc_parse:/data:ro \
  -v /mnt/f/hanson/hanson_doc_parse/deploy-package/reports:/out \
  --entrypoint python hanson-new-app:dev-amd64 \
  /data/deploy-package/scripts/replay_md_parse.py \
  --docs "/data/标准拆分提取-20261117-094032" --folders 28 --dump \
  --out /out/replay-28-opt.json
docker run --rm -w /baseline/new_app \
  -e PYTHONPATH=/baseline/new_app:/baseline/new_app/packages/contracts/src:/baseline/new_app/packages/domain/src:/baseline/new_app/packages/observability/src:/app \
  -e REPLAY_RUNTIME_DIR=/baseline/new_app/services/sandbox/runtime \
  -e REPLAY_RECIPE_DIR=/baseline/new_app/services/recipe_registry/data/recipes \
  -v /tmp/hanson_baseline:/baseline:ro \
  -v /mnt/f/hanson/hanson_doc_parse:/data:ro \
  -v /mnt/f/hanson/hanson_doc_parse/deploy-package/reports:/out \
  --entrypoint python hanson-new-app:dev-amd64 \
  /data/deploy-package/scripts/replay_md_parse.py \
  --docs "/data/标准拆分提取-20261117-094032" --folders 28 --dump \
  --out /out/replay-28-baseline.json
