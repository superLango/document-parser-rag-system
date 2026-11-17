set -u
echo "== Qwen process =="
ps -eo pid,etime,args | grep -E 'vllm.*serve' | grep -v grep | head -3 | cut -c1-600
echo "== GPU =="
nvidia-smi --query-gpu=index,name,memory.total,memory.used,utilization.gpu --format=csv,noheader 2>/dev/null
echo "== CPU =="
nproc
echo "== model list =="
curl -s -m 5 http://127.0.0.1:9988/v1/models | head -c 400; echo
echo "== metrics sample =="
curl -s -m 5 http://127.0.0.1:9988/metrics 2>/dev/null | grep -E 'num_requests_(running|waiting)|gpu_cache_usage' | head -6
