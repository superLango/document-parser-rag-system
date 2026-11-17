set -eu
M=docker.m.daocloud.io
NEW_APP=/mnt/f/hanson/hanson_doc_parse/new_app
BUILD=/mnt/f/hanson/hanson_doc_parse/deploy-package/build/arm64
export DOCKER_DEFAULT_PLATFORM=linux/arm64

echo "[$(date +%T)] build hanson-sandbox-runtime:local (arm64)"
docker build --platform linux/arm64 \
  --build-arg BASE_IMAGE=$M/library/python:3.12-slim \
  -f "$BUILD/Dockerfile.sandbox" -t hanson-sandbox-runtime:local "$NEW_APP" 2>&1 | tail -5

echo "[$(date +%T)] build hanson-web:local (arm64)"
docker build --platform linux/arm64 \
  --build-arg BASE_IMAGE=$M/library/nginx:1.27-alpine \
  -f "$BUILD/Dockerfile.web" -t hanson-web:local "$NEW_APP" 2>&1 | tail -5

echo "[$(date +%T)] build hanson-new-app:local (arm64, pip install via qemu)"
docker build --platform linux/arm64 \
  --build-arg BASE_IMAGE=$M/library/python:3.12-slim \
  -f "$BUILD/Dockerfile.app" -t hanson-new-app:local "$NEW_APP" 2>&1 | tail -15

echo "[$(date +%T)] verify"
docker run --rm --platform linux/arm64 hanson-sandbox-runtime:local -c "import platform;print('sandbox='+platform.machine())" 2>&1 | tail -1
docker run --rm --platform linux/arm64 --entrypoint python hanson-new-app:local -c "import platform,sys;print('app='+platform.machine(),sys.version.split()[0])" 2>&1 | tail -1
docker run --rm --platform linux/arm64 hanson-web:local nginx -v 2>&1 | tail -1
docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' | grep -E 'hanson-(new-app|web|sandbox-runtime):local'
echo "[$(date +%T)] build done"
