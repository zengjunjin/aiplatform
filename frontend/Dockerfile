# 构建阶段
FROM node:20-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .
RUN npm run build

# 生产阶段
FROM nginx:1.27-alpine

COPY --from=builder /app/dist /usr/share/nginx/html

COPY nginx.conf /etc/nginx/conf.d/default.conf

# Task 84: 非 root 用户运行 nginx，降低容器逃逸风险
# /run 目录用于存放 nginx.pid，必须对 appuser 可写
RUN addgroup -S appgroup && adduser -S appuser -G appgroup \
    && mkdir -p /run /var/cache/nginx /var/log/nginx \
    && chown -R appuser:appgroup /usr/share/nginx/html /var/cache/nginx /var/log/nginx /etc/nginx/conf.d /run

USER appuser

EXPOSE 80

# Task 84: 容器健康检查（alpine nginx 镜像内置 wget）
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD wget -qO- http://127.0.0.1/ || exit 1

CMD ["nginx", "-g", "daemon off;"]