set -u
echo "== dns/http =="
curl -s -m 5 -o /dev/null -w 'http_pypi=%{http_code}\n' http://pypi.org/simple/ || true
curl -s -m 5 -o /dev/null -w 'http_docker=%{http_code}\n' http://registry-1.docker.io/v2/ || true
getent hosts pypi.org || echo dns_fail
echo "== proxy env =="
env | grep -iE 'proxy' || echo no_proxy_env
grep -riE 'proxy' "$HOME/.bashrc" "$HOME/.profile" /etc/environment 2>/dev/null | head -5
echo "== gateway =="
ip route | head -3
ping -c 2 -W 2 223.5.5.5 2>&1 | tail -2
