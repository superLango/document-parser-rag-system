set -u
echo "== start $(date +%T) =="
docker pull --platform linux/arm64 docker.1ms.run/library/python:3.12-slim > /tmp/pull_py.log 2>&1 &
PID=$!
while kill -0 $PID 2>/dev/null; do
  sleep 15
  printf '%s ' "$(date +%T)"
  tail -1 /tmp/pull_py.log | cut -c1-120
done
wait $PID; RC=$?
echo "== pull rc=$RC $(date +%T) =="
tail -3 /tmp/pull_py.log
docker image inspect docker.1ms.run/library/python:3.12-slim --format 'arch={{.Architecture}} os={{.Os}} size={{.Size}}' 2>&1 | tail -1
