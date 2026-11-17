set -u
try_pull() {
  ref="$1"
  echo "--- pull $ref"
  timeout 180 docker pull --platform linux/arm64 "$ref" 2>&1 | tail -3
}
try_pull docker.1ms.run/library/python:3.12-slim
docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' | grep -i 'python.*3.12' || true
