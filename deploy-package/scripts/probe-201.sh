set -u
echo "== host =="
hostname; uname -m; cat /etc/os-release | grep PRETTY
echo "== docker =="
docker version --format '{{.Server.Version}} {{.Server.Arch}}' 2>&1 | tail -2
id -nG | tr ' ' '\n' | grep -x docker || echo "NO_DOCKER_GROUP"
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Ports}}' 2>&1 | head -30
echo "== net =="
for u in https://pypi.org/simple/ https://registry.npmjs.org/ https://registry-1.docker.io/v2/; do
  printf '%s ' "$u"; curl -s -m 6 -o /dev/null -w '%{http_code}\n' "$u"
done
echo "== daemon.json =="
cat /etc/docker/daemon.json 2>/dev/null || echo none
echo "== tools =="
for t in node npm python3 rsync tar curl git; do printf '%s=' "$t"; command -v "$t" || echo missing; done
echo "== disk/mem =="
df -h /home /var/lib/docker 2>/dev/null | tail -3
free -g | head -2
echo "== models =="
curl -s -m 4 -o /dev/null -w 'glm9977=%{http_code}\n' http://127.0.0.1:9977/v1/models
curl -s -m 4 -o /dev/null -w 'layout9979_health=%{http_code}\n' http://127.0.0.1:9979/health
curl -s -m 4 -o /dev/null -w 'qwen202_9988=%{http_code}\n' http://193.168.2.202:9988/v1/models
echo "== ports =="
ss -ltnp 2>/dev/null | grep -E ':(18000|18080|18001|18081)\b' || echo "no app ports"
