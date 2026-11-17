H=$(ip route | awk '/default/ {print $3; exit}')
echo "host=$H"
if [ -z "$H" ]; then H=$(grep nameserver /etc/resolv.conf | awk '{print $2}' | head -1); echo "host_from_resolv=$H"; fi
for p in "http://$H:7897" "http://127.0.0.1:7897"; do
  echo "-- proxy $p"
  curl -s -m 8 -x "$p" -o /dev/null -w 'pypi=%{http_code} ' https://pypi.org/simple/ || true
  curl -s -m 8 -x "$p" -o /dev/null -w 'dockerhub=%{http_code} ' https://registry-1.docker.io/v2/ || true
  curl -s -m 8 -x "$p" -o /dev/null -w 'dockerproxy=%{http_code}\n' https://docker.m.daocloud.io/v2/ || true
done
echo "-- direct"
curl -s -m 6 -o /dev/null -w 'pypi_direct=%{http_code}\n' https://pypi.org/simple/ || true
