for u in https://docker.1ms.run/v2/ https://docker.m.daocloud.io/v2/ https://dockerproxy.net/v2/ https://pypi.org/simple/ https://registry.npmjs.org/; do
  printf '%s ' "$u"
  curl -s -m 10 -o /dev/null -w '%{http_code}\n' "$u" || echo ERR
done
echo "== resolve =="
getent hosts docker.1ms.run || echo no_dns_1ms
getent hosts pypi.org || echo no_dns_pypi
