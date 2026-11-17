set -u
echo "== GLM process =="
ps -eo pid,etime,args | grep -E 'vllm.*serve|vllm.entrypoints' | grep -v grep | head -3 | cut -c1-400
echo "== layout process =="
ps -eo pid,etime,args | grep -E 'serve_layout|layout_api' | grep -v grep | head -3 | cut -c1-400
echo "== GPU =="
nvidia-smi --query-gpu=index,name,memory.total,memory.used,utilization.gpu --format=csv,noheader 2>/dev/null
echo "== CPU =="
nproc
echo "== model list =="
curl -s -m 5 http://127.0.0.1:9977/v1/models | head -c 400; echo
curl -s -m 5 http://127.0.0.1:9979/health | head -c 300; echo
echo "== layout api docs =="
curl -s -m 5 http://127.0.0.1:9979/openapi.json | head -c 600; echo
