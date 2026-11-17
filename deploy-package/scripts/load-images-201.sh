set -eu
PKG=/home/htjiance8/hanson-deploy/deploy-package
cd "$PKG"
echo "== images =="
ls -lh images/
echo "== checksum =="
sha256sum -c images/hanson-runtime-images-arm64.tar.sha256 2>&1 | tail -2
sha256sum -c images/hanson-base-images-arm64.tar.sha256 2>&1 | tail -2
echo "== load runtime =="
docker load -i images/hanson-runtime-images-arm64.tar | tail -3
echo "== load base =="
docker load -i images/hanson-base-images-arm64.tar | tail -2
echo "== loaded =="
docker image inspect hanson-new-app:local --format 'app={{.Os}}/{{.Architecture}}'
docker image inspect hanson-web:local --format 'web={{.Os}}/{{.Architecture}}'
docker image inspect hanson-sandbox-runtime:local --format 'sandbox={{.Os}}/{{.Architecture}}'
docker image inspect postgres:16-alpine --format 'postgres={{.Os}}/{{.Architecture}}'
docker image inspect redis:7-alpine --format 'redis={{.Os}}/{{.Architecture}}'
docker image inspect minio/minio:latest --format 'minio={{.Os}}/{{.Architecture}}'
