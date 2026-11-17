set -u
for M in docker.1panel.live hub.rat.dev docker.m.daocloud.io; do
  echo "--- $M"
  if docker pull --platform linux/arm64 "$M/library/postgres:16-alpine" >/tmp/pgx.log 2>&1; then
    docker tag "$M/library/postgres:16-alpine" postgres:16-alpine
    echo "OK via $M"
    docker image inspect postgres:16-alpine --format 'arch={{.Architecture}}'
    break
  else
    tail -2 /tmp/pgx.log | cut -c1-140
  fi
done
