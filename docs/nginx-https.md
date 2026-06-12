# Nginx HTTPS 反向代理配置

> V4 默认通过 HTTP 暴露服务。生产环境建议在前面加一层 nginx 反向代理，提供 HTTPS 加密。

---

## 方案一：自签名证书（内网部署）

适用于纯内网环境，不需要公网 CA 签发的证书。

### 1. 生成自签名证书

```bash
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/eia.key \
  -out /etc/nginx/ssl/eia.crt \
  -subj "/CN=eia.internal"
```

### 2. nginx 配置

```nginx
server {
    listen 443 ssl;
    server_name eia.internal;

    ssl_certificate     /etc/nginx/ssl/eia.crt;
    ssl_certificate_key /etc/nginx/ssl/eia.key;

    # 安全头
    add_header X-Content-Type-Options nosniff;
    add_header X-Frame-Options DENY;

    # 反向代理到 V4 应用
    location / {
        proxy_pass http://127.0.0.1:8002;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # SSE 流式支持
        proxy_buffering off;
        proxy_read_timeout 300s;
    }

    # WebSocket（如需）
    location /ws {
        proxy_pass http://127.0.0.1:8002;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}

# HTTP → HTTPS 重定向
server {
    listen 80;
    server_name eia.internal;
    return 301 https://$host$request_uri;
}
```

---

## 方案二：Let's Encrypt（公网部署）

适用于有公网域名的环境。

### 1. 安装 certbot

```bash
# Ubuntu/Debian
apt install certbot python3-certbot-nginx

# CentOS/RHEL
yum install certbot python3-certbot-nginx
```

### 2. 获取证书

```bash
certbot --nginx -d your-domain.com
```

证书自动续期：

```bash
# certbot 默认已添加 systemd timer，确认：
systemctl status certbot.timer
```

---

## 方案三：Docker Compose 集成 nginx

如果需要将 nginx 也纳入 Docker 编排：

```yaml
# docker-compose.prod.yml 追加
nginx:
  image: nginx:alpine
  container_name: eia-nginx
  ports:
    - "443:443"
    - "80:80"
  volumes:
    - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
    - ./ssl:/etc/nginx/ssl:ro
  depends_on:
    - app
  networks:
    - eia-v4-net
  restart: unless-stopped
```

然后将 app 服务的端口改为仅绑定本地：

```yaml
app:
  ports:
    - "127.0.0.1:8000:8000"  # 仅 nginx 可访问
```

---

## 安全加固建议

- 生产环境 `.env` 中 `CORS_ORIGINS` 应设为具体域名，而非 `*`
- 启用 HSTS：`add_header Strict-Transport-Security "max-age=63072000" always;`
- 定期更新 nginx 和 OpenSSL
- 自签名证书每年更新一次
