# hansonDoc_RAG 后端镜像（GPU：嵌入/重排/版面 CUDA）
# 使用 python:3.13-slim + torch cu130 wheel（NVIDIA GB10 已验证）
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 系统依赖：opencv/pymupdf/doclayout_yolo 编译与运行所需
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libgomp1 gcc g++ \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# torch/torchvision CUDA 13.0（先装，满足 requirements 中 torch>=2.13.0）
RUN pip install --index-url https://download.pytorch.org/whl/cu130 \
        torch==2.13.0 torchvision==0.28.0

COPY backend/requirements.txt /app/requirements.txt
RUN pip install -r /app/requirements.txt \
    && pip install croniter

# 应用代码
COPY backend /app/backend

# 小模型权重：不打包进镜像（离线部署传 tar 体积大），由宿主机目录卷挂载到 /app/models
# 部署机需提供 models/bge-m3、models/bge-reranker-v2-m3、models/pp_doclayoutv3

COPY backend/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

WORKDIR /app/backend
ENTRYPOINT ["/app/entrypoint.sh"]
