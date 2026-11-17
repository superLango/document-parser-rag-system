set -u
echo "== layout endpoints =="
for p in /health /healthz /v1/layout /layout; do
  printf '%-12s GET=' "$p"; curl -s -m 4 -o /dev/null -w '%{http_code}' "http://127.0.0.1:9979$p"
  printf ' POST='; curl -s -m 4 -X POST -H 'content-type: application/json' -d '{}' -o /dev/null -w '%{http_code}\n' "http://127.0.0.1:9979$p"
done
echo "== glm =="
curl -s -m 4 http://127.0.0.1:9977/v1/models | head -c 300; echo
echo "== qwen 202 =="
curl -s -m 5 http://193.168.2.202:9988/v1/models | head -c 300; echo
echo "== docker networks =="
docker network ls --format '{{.Name}} {{.Driver}} {{.Scope}}'
for n in $(docker network ls --format '{{.Name}}' | grep -vE '^(host|none)$'); do
  echo "-- $n"; docker network inspect "$n" --format '{{range .IPAM.Config}}{{.Subnet}} {{end}}' 2>/dev/null
done
echo "== host ip =="
hostname -I
