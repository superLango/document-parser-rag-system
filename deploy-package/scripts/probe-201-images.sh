set -u
echo "== images =="
docker images --format '{{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}' | head -40
echo "== old image history (base) =="
docker history --no-trunc hanson-doc-parse:4e179cc2-p1 2>/dev/null | tail -5 | cut -c1-160
docker history --no-trunc hansondoc-frontend:latest 2>/dev/null | tail -3 | cut -c1-160
echo "== pip/npm config =="
cat /etc/pip.conf 2>/dev/null; cat "$HOME/.pip/pip.conf" 2>/dev/null; cat "$HOME/.config/pip/pip.conf" 2>/dev/null; echo "--npmrc--"; cat "$HOME/.npmrc" 2>/dev/null; cat /usr/etc/npmrc 2>/dev/null
echo "== extra mirrors =="
for u in https://docker.m.daocloud.io/v2/ https://pypi.tuna.tsinghua.edu.cn/simple/ http://mirrors.aliyun.com/pypi/simple/ https://registry.npmmirror.com/; do
  printf '%s ' "$u"; curl -s -m 6 -o /dev/null -w '%{http_code}\n' "$u"
done
echo "== internal hosts =="
curl -s -m 4 -o /dev/null -w 'model35_9977=%{http_code}\n' http://192.168.1.35:9977/v1/models
getent hosts registry.local 2>/dev/null || true
echo "== old compose =="
ls /home/htjiance8/Desktop/AI-01/hanson-doc-parse-4e179cc2/infra/docker/ 2>/dev/null
