set -u
F=/home/htjiance8/Desktop/AI-01/hanson-doc-parse-4e179cc2/infra/model-plane/serve_layout.py
echo "== layout service concurrency-related lines =="
grep -nE 'Semaphore|Lock|lock|ThreadPool|run_in_executor|to_thread|batch|async def|def analyze|uvicorn|workers|gpu' "$F" | head -40
echo "== old project client concurrency =="
grep -rnE 'LAYOUT_.*CONCURRENCY|GLM_.*CONCURRENCY|concurrency' /home/htjiance8/Desktop/AI-01/hanson-doc-parse-4e179cc2/infra /home/htjiance8/Desktop/AI-01/hanson-doc-parse-4e179cc2/apps 2>/dev/null | grep -v Binary | head -20
