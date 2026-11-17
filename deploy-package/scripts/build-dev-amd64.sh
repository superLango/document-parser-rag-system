set -eu
cd /mnt/f/hanson/hanson_doc_parse
docker build --platform linux/amd64 \
  --build-arg BASE_IMAGE=python:3.12-slim \
  -f deploy-package/build/arm64/Dockerfile.app \
  -t hanson-new-app:dev-amd64 new_app 2>&1 | tail -6
docker image inspect hanson-new-app:dev-amd64 --format 'arch={{.Architecture}} size={{.Size}}'
