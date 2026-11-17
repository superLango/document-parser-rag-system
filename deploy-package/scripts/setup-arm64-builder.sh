set -u
M=docker.m.daocloud.io
echo "[$(date +%T)] pull python:3.12-slim arm64"
docker pull --platform linux/arm64 $M/library/python:3.12-slim > /tmp/p1.log 2>&1 || { echo FAIL_PY; tail -3 /tmp/p1.log; exit 1; }
echo "[$(date +%T)] pull nginx:1.27-alpine arm64"
docker pull --platform linux/arm64 $M/library/nginx:1.27-alpine > /tmp/p2.log 2>&1 || { echo FAIL_NGINX; tail -3 /tmp/p2.log; exit 1; }
echo "[$(date +%T)] install binfmt qemu"
docker run --privileged --rm $M/tonistiigi/binfmt:latest --install arm64 2>&1 | tail -3
echo "[$(date +%T)] verify arm64 exec"
docker run --rm --platform linux/arm64 $M/library/python:3.12-slim python -c "import platform;print('machine='+platform.machine())" 2>&1 | tail -2
docker image inspect $M/library/python:3.12-slim --format 'py_arch={{.Architecture}}'
docker image inspect $M/library/nginx:1.27-alpine --format 'nginx_arch={{.Architecture}}'
echo "[$(date +%T)] done"
