set -eu
cd /mnt/f/hanson/hanson_doc_parse
rm -rf /tmp/hanson_baseline
mkdir -p /tmp/hanson_baseline
git archive HEAD new_app | tar -x -C /tmp/hanson_baseline
docker run --rm -w /baseline/new_app \
  -e PYTHONPATH=/baseline/new_app:/baseline/new_app/packages/contracts/src:/baseline/new_app/packages/domain/src:/baseline/new_app/packages/observability/src:/app \
  -e REPLAY_RUNTIME_DIR=/baseline/new_app/services/sandbox/runtime \
  -e REPLAY_RECIPE_DIR=/baseline/new_app/services/recipe_registry/data/recipes \
  -v /tmp/hanson_baseline:/baseline:ro \
  -v /mnt/f/hanson/hanson_doc_parse:/data:ro \
  -v /mnt/f/hanson/hanson_doc_parse/deploy-package/reports:/out \
  --entrypoint python hanson-new-app:dev-amd64 \
  /data/deploy-package/scripts/replay_md_parse.py \
  --docs "/data/标准拆分提取-20261117-094032" \
  --out /out/replay-all-baseline.json
