# V4 版本升级指南

## 自动升级（推荐）

entrypoint 脚本在每次容器启动时自动运行 `alembic upgrade head`，所以升级流程是：

```bash
# 1. 拉取最新代码
git pull origin master

# 2. 更新 Docker 镜像
docker compose -f docker-compose.prod.yml pull app

# 3. 重启（entrypoint 自动运行迁移）
docker compose -f docker-compose.prod.yml up -d

# 4. 确认健康
curl http://localhost:8002/health
```

## 手动升级

```bash
# 1. 停止服务
docker compose -f docker-compose.prod.yml down

# 2. 更新代码
git pull origin master

# 3. 手动运行迁移（也可依赖 entrypoint）
pip install -e ".[dev]"
alembic upgrade head

# 4. 重新构建和启动
docker compose -f docker-compose.prod.yml build app
docker compose -f docker-compose.prod.yml up -d
```

## 升级前检查清单

- [ ] 已备份数据库：`bash scripts/backup.sh`
- [ ] 已阅读新版本的 CHANGELOG.md
- [ ] 确认 .env 配置与新版兼容（对比 .env.production.example）
- [ ] 如果有新增的必填环境变量，已补充到 .env

## 回滚

如果升级后出现问题：

```bash
# 1. 停止服务
docker compose -f docker-compose.prod.yml down

# 2. 恢复数据库
gunzip -c backups/backup-YYYYMMDD-HHMMSS.sql.gz | \
  docker exec -i eia-postgres-v4-prod psql -U admin enterprise_db

# 3. 回退代码到上一个版本
git checkout <previous-tag>

# 4. 重新启动
docker compose -f docker-compose.prod.yml up -d
```
