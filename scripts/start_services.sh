#!/bin/bash
# 后台启动后端 + arq + 前端（断网不影响）
set -e
cd /home/grainuser/hansonDoc_RAG/backend

echo "启动后端 uvicorn ..."
setsid nohup .venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/uvicorn_bg.log 2>&1 &
echo "启动 arq worker ..."
setsid nohup .venv/bin/arq app.tasks.arq_worker.WorkerSettings > /tmp/arq_bg.log 2>&1 &

cd /home/grainuser/hansonDoc_RAG/frontend
echo "启动前端 vite ..."
setsid nohup node_modules/.bin/vite > /tmp/vite_bg.log 2>&1 &

echo "等待服务就绪（最多 60s）..."
for i in $(seq 1 30); do
    sleep 2
    BACK=$(ss -tlnp 2>/dev/null | grep -c ':8000' || true)
    FRONT=$(ss -tlnp 2>/dev/null | grep -c ':5174' || true)
    if [ "$BACK" -ge 1 ] && [ "$FRONT" -ge 1 ]; then
        echo "服务已就绪：后端 :8000 / 前端 :5174"
        echo "日志：/tmp/uvicorn_bg.log /tmp/arq_bg.log /tmp/vite_bg.log"
        exit 0
    fi
done
echo "警告：60s 内未完全就绪，请检查日志：/tmp/uvicorn_bg.log /tmp/arq_bg.log /tmp/vite_bg.log"
