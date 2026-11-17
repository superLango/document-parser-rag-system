set -eu
cd /mnt/f/hanson/hanson_doc_parse
docker run --rm -w /app \
  -e PYTHONPATH=/app:/app/packages/contracts/src:/app/packages/domain/src:/app/packages/observability/src \
  -v /mnt/f/hanson/hanson_doc_parse:/data:ro \
  --entrypoint python hanson-new-app:dev-amd64 \
  /data/deploy-package/scripts/debug_table.py "$@"
