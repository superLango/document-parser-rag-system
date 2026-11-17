set -u
cd /home/htjiance8/hanson-deploy/deploy-package
echo "== agent log timeline (last 40 lines with time) =="
docker compose logs --timestamps --tail 200 agent 2>&1 | grep -E 'INFO|WARNING|ERROR|ContextOverflow' | tail -25 | cut -c1-220
echo "== tokenize latency from agent net =="
docker compose exec -T agent python -c "
import time, urllib.request, json
text = '牌号 抗拉强度 屈服强度 伸长率 断面收缩率 冲击功 ' * 4000
body = json.dumps({'model':'Qwen3.6-35B-A3B-FP8','prompt':text}).encode()
t=time.time()
req=urllib.request.Request('http://193.168.2.202:9988/tokenize', data=body, headers={'content-type':'application/json'})
try:
    r=urllib.request.urlopen(req, timeout=60); d=json.loads(r.read())
    print('bytes=%d tokens=%s elapsed=%.2fs' % (len(text), d.get('count'), time.time()-t))
except Exception as e:
    print('FAIL', e)
"
