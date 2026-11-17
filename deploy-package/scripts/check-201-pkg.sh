set -u
BASE=/home/htjiance8/hanson-deploy/deploy-package
du -sh "$BASE" 2>/dev/null
echo "files=$(find "$BASE" -maxdepth 1 -type f | wc -l) images=$(ls "$BASE/images" 2>/dev/null | wc -l)"
df -h /home | tail -1
echo "== ports in use =="
ss -ltn | grep -E ':(15432|16379|19000|19001|18001|18081)\b' || echo "target ports free"
echo "== compose =="
docker compose version 2>&1 | head -1
