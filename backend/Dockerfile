# ===== Stage 1: Builder =====
# 构建阶段：在 python:3.12-slim 中编译并安装 Python 依赖
FROM python:3.12-slim AS builder

WORKDIR /app

# 安装编译所需的系统依赖（C 编译器与各类开发库）
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpoppler-cpp-dev \
    default-libmysqlclient-dev \
    libpq-dev \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# 仅复制依赖清单，充分利用 Docker 缓存层
COPY requirements.txt .

# 安装依赖到 /usr/local（相比 --user 更便于跨阶段复制，避免污染用户家目录）
RUN pip install --no-cache-dir -r requirements.txt

# ===== Stage 2: Runtime =====
# 运行阶段：基于 NVIDIA CUDA 运行时镜像，提供 GPU 支持能力
FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04

# GPU 与 Python 运行时环境变量
ENV NVIDIA_VISIBLE_DEVICES=all \
    NVIDIA_DRIVER_CAPABILITIES=compute,utility \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/usr/local/lib/python3.12/site-packages

WORKDIR /app

# 安装运行时系统依赖与 Python 3.12
# Ubuntu 22.04 默认提供 Python 3.10，通过 deadsnakes PPA 获取与构建阶段一致的 3.12
RUN apt-get update && apt-get install -y --no-install-recommends \
    software-properties-common \
    ca-certificates \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
    python3.12 \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libpoppler-cpp-dev \
    default-libmysqlclient-dev \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# 从构建阶段复制已安装的 Python 包（仅复制 site-packages，避免覆盖运行时的解释器二进制）
COPY --from=builder /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages

# 创建非 root 用户以提升安全性
RUN useradd -m -s /bin/bash appuser \
    && chown appuser:appuser /app

# 复制应用源码
COPY --chown=appuser:appuser . .

USER appuser

EXPOSE 8000

# 健康检查：调用 /health 端点确认服务可用性
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
    CMD python3.12 -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).status==200 else 1)"

CMD ["python3.12", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
