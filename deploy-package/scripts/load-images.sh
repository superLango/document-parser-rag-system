#!/usr/bin/env bash
# Load the deployment images from images/.
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ARCHIVE="${1:-}"
if [[ -z "$ARCHIVE" ]]; then
  if [[ -f images/hanson-runtime-images.tar.gz ]]; then
    ARCHIVE="images/hanson-runtime-images.tar.gz"
  elif [[ -f images/hanson-runtime-images.tar ]]; then
    ARCHIVE="images/hanson-runtime-images.tar"
  else
    echo "image archive not found under images/" >&2
    exit 1
  fi
fi

echo "loading images from $ARCHIVE"
docker load -i "$ARCHIVE"

required=(
  "hanson-new-app:local"
  "hanson-web:local"
  "hanson-sandbox-runtime:local"
  "postgres:16-alpine"
  "redis:7-alpine"
  "minio/minio:latest"
)
for image in "${required[@]}"; do
  if ! docker image inspect "$image" >/dev/null 2>&1; then
    echo "missing image after load: $image" >&2
    exit 1
  fi
done
echo "all required images are present"
