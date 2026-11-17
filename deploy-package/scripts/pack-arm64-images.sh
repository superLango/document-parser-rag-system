set -eu
cd /mnt/f/hanson/hanson_doc_parse/deploy-package
mkdir -p images
OUT=images/hanson-runtime-images-arm64.tar
echo "[$(date +%T)] docker save arm64 images"
docker save -o "$OUT" \
  hanson-new-app:local hanson-web:local hanson-sandbox-runtime:local
ls -lh "$OUT"
echo "[$(date +%T)] checksum"
sha256sum "$OUT" | tee images/hanson-runtime-images-arm64.tar.sha256
