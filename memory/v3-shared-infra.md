---
name: v3-shared-infra
description: V4 shares V3's PostgreSQL and Redis — connection details
metadata:
  type: reference
---

# V4 共享 V3 基础设施

V4 不创建独立数据库，而是直接连接 V3 的运行中 PostgreSQL 和 Redis。

**Why:** V4 是 V3 的增量升级，共享同一套业务数据（100 门店、5 万订单、5000 会员）。多版本同时运行时各自使用不同端口。

**How to apply:** 部署 V4 时在 `.env` 中配置：

| 配置项 | 值 |
|--------|-----|
| `DATABASE_URL` | `postgresql+asyncpg://admin:admin123@localhost:15432/enterprise_db` |
| `DATABASE_URL_SYNC` | `postgresql+psycopg2://admin:admin123@localhost:15432/enterprise_db` |
| `REDIS_URL` | `redis://localhost:6379/0` |
| `JWT_SECRET_KEY` | 沿用 V3 密钥（否则已有 token 失效） |
| `SERVER_PORT` | `8002`（V2:8000, V3:8001） |

**迁移注意事项：** V3 数据库停在 alembic 版本 `003_inventory_supply_chain`。运行 V4 迁移前需先 `alembic stamp 004_rbac_enhancement`（V3 未运行 004，但数据已通过 seed 脚本存在），然后再 `alembic upgrade head` 执行 005-007。
