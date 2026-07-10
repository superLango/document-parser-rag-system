# ===== Stage 1: Builder =====
# 构建阶段：安装 Python 依赖到用户目录，便于后续复制
FROM python:3.12-slim AS builder

WORKDIR /app

# 仅复制依赖清单，利用 Docker 缓存层
COPY requirements.txt .

# 安装依赖到用户目录，避免污染系统环境
RUN pip install --no-cache-dir --user -r requirements.txt

# ===== Stage 2: Runtime =====
# 运行阶段：精简镜像，仅包含运行所需内容
FROM python:3.12-slim

WORKDIR /app

# 从构建阶段复制已安装的 Python 包
COPY --from=builder /root/.local /root/.local

# 确保用户安装的可执行文件在 PATH 中
ENV PATH=/root/.local/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# 复制应用源码
COPY . .

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
