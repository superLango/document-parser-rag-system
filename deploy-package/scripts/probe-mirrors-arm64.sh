set -u
MIRRORS="docker.m.daocloud.io docker.1panel.live docker.xuanyuan.me dockerpull.org hub.rat.dev docker.rainbond.cc"
for m in $MIRRORS; do
  printf '%-24s ' "$m"
  out=$(timeout 25 docker manifest inspect "$m/library/python:3.12-slim" 2>&1)
  if printf '%s' "$out" | grep -q 'architecture'; then
    printf 'arm64='; printf '%s' "$out" | grep -c '"architecture": "arm64"'
  else
    printf 'FAIL %s\n' "$(printf '%s' "$out" | head -1 | cut -c1-60)"
  fi
done
