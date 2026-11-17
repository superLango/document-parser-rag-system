set -eu
cd /mnt/f/hanson/hanson_doc_parse
docker run --rm -w /app \
  -e PYTHONPATH=/app:/app/packages/contracts/src:/app/packages/domain/src:/app/packages/observability/src \
  -v /mnt/f/hanson/hanson_doc_parse:/data:ro \
  -v /mnt/f/hanson/hanson_doc_parse/deploy-package/reports:/out \
  --entrypoint python hanson-new-app:local \
  /data/deploy-package/scripts/replay_md_parse.py \
  --docs "/data/标准拆分提取-20261117-094032" \
  --out /out/replay-all-baseline.json
