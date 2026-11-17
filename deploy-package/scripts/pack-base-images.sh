set -eu
cd /mnt/f/hanson/hanson_doc_parse/deploy-package
cat > /tmp/pg16.Dockerfile <<'EOF'
FROM postgres:16-alpine
EOF
rm -f images/hanson-base-images-arm64.tar
echo "[$(date +%T)] buildx export postgres:16-alpine arm64 -> tar"
docker buildx build --platform linux/arm64 \
  -t postgres:16-alpine -f /tmp/pg16.Dockerfile \
  --output type=docker,dest=images/hanson-base-images-arm64.tar /tmp 2>&1 | tail -4
ls -lh images/hanson-base-images-arm64.tar
sha256sum images/hanson-base-images-arm64.tar | tee images/hanson-base-images-arm64.tar.sha256
echo "[$(date +%T)] done"
