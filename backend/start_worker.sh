#!/bin/bash
# arq worker 启动脚本
# 确保 CUDA 环境变量正确设置，避免 torch 因缺少 LD_LIBRARY_PATH 而 CUDA 错误

# 切换到 backend 目录
cd /home/hanson/doc_parse_project/backend || exit 1

# 激活虚拟环境
source ./venv/bin/activate

# 关键：设置 CUDA 相关环境变量
export CUDA_VISIBLE_DEVICES=0
export CUDA_HOME=/usr/local/cuda
# 必须设置 LD_LIBRARY_PATH，否则 torch 找不到 CUDA 运行时库
export LD_LIBRARY_PATH=/usr/local/cuda/lib64:${LD_LIBRARY_PATH:-}

# Python 编码
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

# 验证 torch CUDA 可用（PP-DocLayoutV3 版面分析 + GLM-OCR 均基于 torch）
python -c "import torch; print('torch cuda:', torch.cuda.is_available(), 'device:', torch.cuda.device_count() if torch.cuda.is_available() else 'N/A')" 2>&1 | tail -3

echo "=== 启动 arq worker ==="
exec arq app.tasks.arq_worker.WorkerSettings
