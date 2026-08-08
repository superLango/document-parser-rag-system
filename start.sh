#!/bin/bash
# ============================================================================
# HansonDOC RAG 应用服务统一启动脚本
# ----------------------------------------------------------------------------
# 管理服务：后端 API(:8000) + arq 异步 worker + 前端(:5174)
# 用法：./start.sh [start|stop|status|restart]    默认 start
#
# 依赖前提：
#   1. 基础设施服务已启动：PostgreSQL(:5432) / Redis(:6379) / MinIO(:9000)
#      / Milvus(:19530) / NebulaGraph(:9669)
#   2. backend/.env 已按 backend/.env.example 配置完成
#   3. backend/venv 已创建并 pip install -r requirements.txt
#   4. frontend 已 pnpm install
#   5. 三个 vLLM 推理服务已单独启动（启动方式见下方注释）
#
# ----------------------------------------------------------------------------
# vLLM 推理服务启动方式（需单独手动启动，本脚本不管理）
# ----------------------------------------------------------------------------
# # 先激活 vLLM 专用虚拟环境
# cd <PROJECT_ROOT> && source venv_model/bin/activate
#
# # 1. GLM-OCR 服务（端口 9977，主 OCR 引擎，整页 Markdown 输出）
# vllm serve ./models/glm-ocr \
#   --host 0.0.0.0 --port 9977 \
#   --served-model-name GLM-OCR \
#   --trust-remote-code \
#   --max-num-seqs 2 --max-num-batched-tokens 8192 --max-model-len 32768 \
#   --enable-prefix-caching --enable-chunked-prefill \
#   --gpu-memory-utilization 0.16
#
# # 2. Qwen3.6-35B 主 LLM 服务（端口 9988，结构化抽取 + RAG 问答）
# vllm serve ./models/Qwen/Qwen3.6-35B-A3B-FP8 \
#   --host 0.0.0.0 --port 9988 \
#   --served-model-name Qwem3.6-35B-A3B-FP8 \
#   --kv-cache-dtype fp8 --trust-remote-code \
#   --max-model-len 55000 --max-num-seqs 8 --max-num-batched-tokens 27500 \
#   --gpu-memory-utilization 0.40 --enable-prefix-caching
#
# # 3. MinerU-Popo 服务（端口 9999，版面分析后处理增强）
# vllm serve ./models/MinerU-Popo \
#   --host 0.0.0.0 --port 9999 \
#   --served-model-name Popo \
#   --max-model-len 32768 --gpu-memory-utilization 0.10 --max-num-seqs 2
#
# # 注意：--served-model-name 必须与 backend/.env 中对应 *_MODEL 变量完全一致（大小写敏感）
# # 显存分配：0.16 + 0.40 + 0.10 = 0.66，剩余供 arq worker 内嵌入/重排/gliclass 模型使用
# ============================================================================

set -e

# ---------- 路径（自动适配克隆目录，无需修改）----------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$SCRIPT_DIR"
BACKEND_DIR="$PROJECT_ROOT/backend"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
LOG_DIR="$PROJECT_ROOT/logs"
PID_DIR="$LOG_DIR/.run"

mkdir -p "$LOG_DIR" "$PID_DIR"

# ---------- CUDA 环境（arq worker 加载 torch 模型必需）----------
export CUDA_VISIBLE_DEVICES=0
export CUDA_HOME=/usr/local/cuda
export LD_LIBRARY_PATH=/usr/local/cuda/lib64:${LD_LIBRARY_PATH:-}
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

# 颜色输出
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[0;33m'
NC='\033[0m'

# ---------- 前置检查 ----------
preflight() {
    local missing=0
    [ -f "$BACKEND_DIR/.env" ] || { echo -e "${RED}✗ 缺少 backend/.env，请 cp backend/.env.example backend/.env 并配置${NC}"; missing=1; }
    [ -f "$BACKEND_DIR/venv/bin/activate" ] || { echo -e "${RED}✗ 缺少 backend/venv，请先创建虚拟环境并安装依赖${NC}"; missing=1; }
    [ -d "$FRONTEND_DIR/node_modules" ] || { echo -e "${RED}✗ 缺少 frontend/node_modules，请先 cd frontend && pnpm install${NC}"; missing=1; }
    command -v pnpm >/dev/null 2>&1 || { echo -e "${RED}✗ 未找到 pnpm，请先安装 Node.js + pnpm${NC}"; missing=1; }
    return $missing
}

# ---------- 进程状态检查 ----------
is_running() {
    local pid_file="$1"
    [ -f "$pid_file" ] || return 1
    local pid
    pid=$(cat "$pid_file" 2>/dev/null)
    [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null
}

# ---------- 启动单个服务 ----------
start_api() {
    if is_running "$PID_DIR/api.pid"; then
        echo -e "${YELLOW}⚠ 后端 API 已在运行 (PID $(cat "$PID_DIR/api.pid"))${NC}"
        return 0
    fi
    cd "$BACKEND_DIR" || return 1
    source ./venv/bin/activate
    nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > "$LOG_DIR/api.log" 2>&1 &
    echo $! > "$PID_DIR/api.pid"
    echo -e "${GREEN}✓ 后端 API 已启动 (PID $!, :8000, 日志 logs/api.log)${NC}"
}

start_worker() {
    if is_running "$PID_DIR/worker.pid"; then
        echo -e "${YELLOW}⚠ arq worker 已在运行 (PID $(cat "$PID_DIR/worker.pid"))${NC}"
        return 0
    fi
    cd "$BACKEND_DIR" || return 1
    source ./venv/bin/activate
    # 验证 torch CUDA 可用（PP-DocLayoutV3 版面分析 + GLM-OCR 均基于 torch）
    python -c "import torch; print('torch cuda:', torch.cuda.is_available(), 'devices:', torch.cuda.device_count() if torch.cuda.is_available() else 0)" 2>&1 | tail -1
    nohup arq app.tasks.arq_worker.WorkerSettings > "$LOG_DIR/worker.log" 2>&1 &
    echo $! > "$PID_DIR/worker.pid"
    echo -e "${GREEN}✓ arq worker 已启动 (PID $!, 日志 logs/worker.log)${NC}"
}

start_frontend() {
    if is_running "$PID_DIR/frontend.pid"; then
        echo -e "${YELLOW}⚠ 前端已在运行 (PID $(cat "$PID_DIR/frontend.pid"))${NC}"
        return 0
    fi
    cd "$FRONTEND_DIR" || return 1
    nohup pnpm dev > "$LOG_DIR/frontend.log" 2>&1 &
    echo $! > "$PID_DIR/frontend.pid"
    echo -e "${GREEN}✓ 前端已启动 (PID $!, :5174, 日志 logs/frontend.log)${NC}"
}

# ---------- 停止单个服务 ----------
stop_service() {
    local name="$1" pid_file="$2"
    if ! is_running "$pid_file"; then
        echo -e "${YELLOW}⚠ ${name} 未在运行${NC}"
        rm -f "$pid_file"
        return 0
    fi
    local pid
    pid=$(cat "$pid_file")
    kill "$pid" 2>/dev/null || true
    # 等待退出（最多 10 秒）
    for _ in $(seq 1 10); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 1
    done
    # 仍未退出则强制杀
    if kill -0 "$pid" 2>/dev/null; then
        kill -9 "$pid" 2>/dev/null || true
        echo -e "${YELLOW}⚠ ${name} (PID ${pid}) 已强制终止${NC}"
    else
        echo -e "${GREEN}✓ ${name} (PID ${pid}) 已停止${NC}"
    fi
    rm -f "$pid_file"
}

# ---------- 启动全部 ----------
do_start() {
    echo "========== 启动 HansonDOC RAG 应用服务 =========="
    preflight || { echo -e "${RED}前置检查未通过，请按提示修复后重试${NC}"; exit 1; }
    start_api
    start_worker
    start_frontend
    echo ""
    echo -e "${GREEN}全部服务已启动。访问前端：http://localhost:5174${NC}"
    echo "查看日志：tail -f logs/api.log logs/worker.log logs/frontend.log"
}

# ---------- 停止全部 ----------
do_stop() {
    echo "========== 停止 HansonDOC RAG 应用服务 =========="
    stop_service "前端"      "$PID_DIR/frontend.pid"
    stop_service "arq worker" "$PID_DIR/worker.pid"
    stop_service "后端 API"   "$PID_DIR/api.pid"
    echo -e "${GREEN}全部服务已停止${NC}"
}

# ---------- 状态查看 ----------
do_status() {
    echo "========== HansonDOC RAG 服务状态 =========="
    for svc in "后端 API:api" "arq worker:worker" "前端:frontend"; do
        local name="${svc%%:*}" key="${svc##*:}"
        if is_running "$PID_DIR/${key}.pid"; then
            echo -e "${GREEN}● ${name} 运行中 (PID $(cat "$PID_DIR/${key}.pid"))${NC}"
        else
            echo -e "${RED}○ ${name} 未运行${NC}"
        fi
    done
}

# ---------- 入口 ----------
case "${1:-start}" in
    start)  do_start ;;
    stop)   do_stop ;;
    status) do_status ;;
    restart) do_stop; sleep 2; do_start ;;
    *)
        echo "用法: $0 [start|stop|status|restart]"
        echo "  start   启动后端 API + arq worker + 前端（默认）"
        echo "  stop    停止全部服务"
        echo "  status  查看服务运行状态"
        echo "  restart 重启全部服务"
        exit 1
        ;;
esac
