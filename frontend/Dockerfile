# Stage 1: Build the Vue app
FROM node:20-alpine AS builder

WORKDIR /app

# Copy package files and install dependencies using npmmirror registry
COPY package.json package-lock.json* ./
RUN npm config set registry https://registry.npmmirror.com \
    && npm install

# Copy source and build
COPY . .
RUN npm run build

# Stage 2: Serve with nginx
FROM nginx:alpine

# Remove default nginx static assets
RUN rm -rf /usr/share/nginx/html/*

# Copy built assets from builder stage
COPY --from=builder /app/dist /usr/share/nginx/html

# Copy custom nginx config
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
