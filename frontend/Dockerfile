# ===== Stage 1: Builder =====
# 构建阶段：编译 Vue 前端应用
FROM node:20-alpine AS builder

WORKDIR /app

# 启用 pnpm（通过 corepack 激活，与 pnpm-lock.yaml 的 v9.0 格式匹配）
RUN corepack enable && corepack prepare pnpm@9 --activate

# 复制依赖清单与 .npmrc（node-linker=hoisted + npmmirror 镜像源），充分利用 Docker 缓存层
COPY .npmrc package.json pnpm-lock.yaml ./

# 安装依赖（存在 lockfile，使用冻结模式保证可重复构建）
RUN pnpm install --frozen-lockfile

# 复制源码并构建
COPY . .
RUN pnpm build

# ===== Stage 2: Runtime =====
# 运行阶段：使用 nginx 托管静态资源
FROM nginx:alpine

# 清除默认静态资源
RUN rm -rf /usr/share/nginx/html/*

# 复制构建产物
COPY --from=builder /app/dist /usr/share/nginx/html

# 复制自定义 nginx 配置（SPA 回退 + /api 反向代理至 backend:8000）
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
