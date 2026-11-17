set -eu
M=docker.m.daocloud.io
NEW_APP=/mnt/f/hanson/hanson_doc_parse/new_app
BUILD=/mnt/f/hanson/hanson_doc_parse/deploy-package/build/arm64
OUT=/mnt/f/hanson/hanson_doc_parse/deploy-package/images/hanson-app-arm64.tar

echo "[$(date +%T)] build hanson-new-app:local (arm64)"
docker build --platform linux/arm64 \
  --build-arg BASE_IMAGE=$M/library/python:3.12-slim \
  -f "$BUILD/Dockerfile.app" -t hanson-new-app:local "$NEW_APP" 2>&1 | tail -6

echo "[$(date +%T)] ocr tests"
docker run --rm --platform linux/arm64 --entrypoint python hanson-new-app:local \
  -m pytest tests -k "ocr or glm" -q 2>&1 | tail -8

echo "[$(date +%T)] save image"
docker save -o "$OUT" hanson-new-app:local
ls -lh "$OUT"
sha256sum "$OUT" | tee "$OUT.sha256"
echo "[$(date +%T)] done"
