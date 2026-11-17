set -u
echo "== manifest via mirrors =="
for m in docker.1ms.run docker.m.daocloud.io dockerproxy.net; do
  for img in library/python:3.12-slim library/nginx:1.27-alpine; do
    printf '%s %s -> ' "$m" "$img"
    timeout 25 docker manifest inspect "$m/$img" >/dev/null 2>&1 && echo OK || echo FAIL
  done
done
echo "== buildx platforms =="
docker buildx inspect default 2>/dev/null | grep -i platforms
echo "== dns =="
grep nameserver /etc/resolv.conf | head -2
