# Enterprise Insight Agent V5 — Reliable Analytics Agent（收官版）

<div align="center">

**用自然语言，让 AI 帮你从企业数据中发现经营洞察**

[![Python](https://img.shields.io/badge/Python-3.12-blue.svg)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Multi--Agent-green.svg)](https://langchain.com/langgraph)
[![DeepSeek](https://img.shields.io/badge/LLM-DeepSeek-purple.svg)](https://deepseek.com)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-teal.svg)](https://fastapi.tiangolo.com/)
[![PostgreSQL](https://img.shields.io/badge/DB-PostgreSQL%2016%20%2B%20pgvector-blue.svg)](https://www.postgresql.org/)
[![Frontend](https://img.shields.io/badge/Frontend-Native%20HTML%2FJS%20%2B%20ECharts5-lightgrey.svg)](app/api/static/)
[![Docker](https://img.shields.io/badge/Deploy-Docker%20One--Click-2496ed.svg)](https://www.docker.com/)
[![Tests](https://img.shields.io/badge/Tests-238%20pass%20%7C%204%20env--fail-brightgreen.svg)](tests/)
[![Prompt](https://img.shields.io/badge/Prompt-v2.0.0%20%22Data%E2%86%92Insight%E2%86%92Action%22-orange.svg)](prompts/yaml/report.yaml)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

*多租户 · 审计日志 · 原生 HTML 前端 · PDF 导出 · 结构化日志 · 全链路追踪 · AI 质量监控面板 · 规则兜底图表注入 🆕*

</div>

---

## 这是什么？

**面向连锁零售企业的 AI 经营决策平台**。5 个 AI Agent 并行分析销售、会员、财务、库存、供应链数据，11 个节点全链路编排，从问题到报告全自动。

> "BI 工具让你做出好看的报表，我们让你不用做报表——用中文提问，直接得到答案和行动建议。"

---

## 产品截图

> 📸 *点击展开大图*

| 分析对话页 | 经营报告页 |
|:---:|:---:|
| ![分析对话](docs/screenshots/chat.png) | ![经营报告](docs/screenshots/report.png) |
| *自然语言提问，实时流式生成* | *Markdown 报告 + ECharts 图表 + 追问建议* |

| 管理面板 | Dashboard 快报 |
|:---:|:---:|
| ![管理面板](docs/screenshots/admin.png) | ![Dashboard](docs/screenshots/dashboard.png) |
| *用户管理 + 权限分配 + 数据库结构配置* | *今日经营数据一屏总览* |

---

## 为什么选 V5？

| 对比维度 | 传统 BI 工具（帆软/Tableau） | 通用 AI（ChatGPT + 数据） | **V5** |
|---------|--------------------------|------------------------|------|
| **使用方式** | 拖拽配置，需要培训 | 需要描述数据结构、写 Prompt | **直接问中文，零门槛** |
| **输出内容** | 可视化图表看板 | 通用对话答复 | **结构化经营报告 + 图表 + 诊断 + 行动建议** |
| **行业适配** | 通用数据平台 | 不懂零售术语 | **预置零售 SQL 模板 + 客户数据库结构自动适配** |
| **数据安全** | 私有化部署 | 数据上传到云端 | **私有化 Docker 部署，数据不出企业** |
| **成本** | 数万～数十万/年 | 按 Token 计费 | **LLM 成本 ¥0.03/次，年费 ~¥300** |
| **质量监控** | ❌ 无 | ❌ 无 | **✅ AI 质量监控面板：量·质·速·稳四象限（通过率三态 / P50 延迟 / 异常会话 / 单任务成本）+ 质检四维原因分布 + 兜底报告下钻** |
| **5 分钟部署** | 需专人实施 | 需开发集成 | ✅ **`./deploy.sh` 一键完成** |

---

## 5 分钟快速开始

> **前提**：已安装 Docker（24+）。

```bash
# 1. 获取项目
git clone <repo-url> && cd enterprise-insight-agent

# 2. 下载预打包的 BGE-M3 嵌入模型（可选，跳过则首次启动自动下载）
#    从 Release 页面下载 bge-m3.tar.gz，放入 ollama-models/ 目录

# 3. 一键部署
chmod +x deploy.sh && ./deploy.sh

# deploy.sh 会自动：
#   ✅ 检测 Docker 环境
#   ✅ 创建 .env 生产配置（首次，含引导提示）
#   ✅ 验证必填配置项（API Key、密钥、密码）
#   ✅ 检查端口可用性
#   ✅ 启动 5 个容器（App + PostgreSQL + Redis + Ollama + n8n）
#   ✅ 等待健康检查通过
#   ✅ 输出访问地址和账号

# 4. 打开浏览器
# http://localhost:8002
```

### 演示账号

| 角色 | 用户名 | 密码 | 数据范围 |
|------|--------|------|----------|
| 总部管理员 | `admin` | `admin123` | 全部门店 |

> 首次部署自动创建 1 个管理员 + 3 个角色 + 7 个权限 + 5 个演示门店。

### 手动部署（开发者）

```bash
cp .env.production.example .env    # 编辑 .env 填入必填项
pip install -e ".[dev]"
alembic upgrade head
python scripts/seed_data.py
uvicorn app.api.main:app --host 0.0.0.0 --port 8002
```

---

## 你可以问什么？

### 老板视角
- "本周华东区域销售概况"
- "本月退款率最高的 5 家门店是哪些"
- "过去 30 天会员新增和流失趋势"
- "对比各区域毛利率，给出优化建议"

### 区域经理视角
- "我们区域的库存周转情况怎么样"
- "哪些商品快缺货了，需要补货"
- "上月华北区供应商准时交货率排名"

### 店长视角
- "我们门店近 7 天客单价变化趋势"
- "本月哪些品类的销量下降最多"
- "会员复购率对比上月变化"

---

## 系统架构

### Agent 拓扑 — 11 节点全链路

```
       ┌──────────────┐
       │  Supervisor  │  智能路由：根据问题语义激活 1~5 个领域 Agent
       └──────┬───────┘
              │ activated_agents
    ┌─────────┼─────────┬──────────┬──────────┐
    ▼         ▼         ▼          ▼          ▼
┌──────┐ ┌──────┐ ┌──────┐ ┌────────┐ ┌──────────┐
│Sales │ │ CRM  │ │Finance│ │Inventory│ │SupplyChain│  并行分析（LangGraph Send）
└──┬───┘ └──┬───┘ └──┬───┘ └───┬────┘ └────┬─────┘
   │        │        │         │           │
   └────────┴────────┴─────────┴───────────┘
                     │
              ┌──────▼──────┐
              │ Aggregator  │  确定性聚合（纯 Python，零 Token 消耗）
              └──────┬──────┘
                     │
              ┌──────▼──────┐
              │Chart Advisor│  ECharts 图表智能推荐（bar/line/pie/scatter/radar）
              └──────┬──────┘
                     │
              ┌──────▼──────┐
              │Report Agent │  结构化报告生成（Markdown + Token 流式推送）
              └──────┬──────┘
                     │
              ┌──────▼──────┐
              │ Reflection  │  4 维质检：一致性 / 逻辑 / 可操作 / 完整
              └──────┬──────┘
              ✅通过   ❌不通过 → 重试报告（最多 1 次）
                     │
              ┌──────▼──────┐
              │Memory Node  │  BGE-M3 嵌入 → pgvector 存储（语义记忆）
              └──────┬──────┘
                     ▼
                   END
```

### 10 个 Agent 一览

| Agent | 职责 | 一句话 |
|-------|------|--------|
| **Supervisor** | 路由决策 | 理解问题 → 决定激活哪些领域 Agent |
| **Sales Agent** | 销售分析 | 销售额、门店排名、区域分布、退款率 |
| **CRM Agent** | 会员分析 | 会员增长、流失、复购、RFM 分层 |
| **Finance Agent** | 财务分析 | 客单价、利润率、成本、现金流 |
| **Inventory Agent** | 库存分析 | 缺货预警、滞销识别、补货建议 |
| **Supply Chain Agent** | 供应链分析 | 供应商绩效、采购成本、物流时效 |
| **Aggregator** | 聚合 | 将各 Agent 结果拼接为统一摘要（纯 Python） |
| **Chart Advisor** | 图表推荐 | 根据数据特征推荐最佳 ECharts 图表类型 |
| **Report Agent** | 报告生成 | 综合生成 Markdown 报告 + 追问建议 |
| **Reflection Agent** | 质量审核 | 4 维交叉验证，不通过自动触发重试 |
| **Memory Node** | 记忆 | BGE-M3 向量嵌入 + pgvector 语义搜索 |

### 中间件栈

```
请求 → CORS → 审计日志(Audit) → 多租户(Tenant) → API版本头 → FastAPI 路由
```

### 完整技术栈

| 层级 | 技术 | 说明 |
|------|------|------|
| **前端** | 原生 HTML/CSS/JS + ECharts 5（React 版 `web/` 重构中） | 管理界面 + 分析对话 UI |
| **后端框架** | FastAPI 0.115 | 异步 API + 自动 OpenAPI 文档 |
| **Agent 引擎** | LangGraph 0.2+ | 11 节点有状态图编排 + 并行扇出 |
| **LLM** | DeepSeek-V4 | 路由决策 / SQL 生成 / 报告撰写 / 质检 |
| **Embedding** | Ollama + BGE-M3（1024 维） | 本地部署，向量语义搜索 |
| **数据库** | PostgreSQL 16 + pgvector | 主存储 + 向量索引 |
| **缓存** | Redis 7 | 会话 / 分析结果缓存 / 速率限制 |
| **定时任务** | n8n | 周报自动生成 + 异常检测 |
| **容器化** | Docker + Compose | 5 容器一键部署 |
| **日志** | structlog 24+ | 结构化 JSON 日志 + trace_id 全链路 |
| **PDF** | WeasyPrint | Markdown → A4 PDF 导出 |
| **认证** | JWT + bcrypt | Token 管理 + 黑名单 + 会话鉴权 |

---

## 项目结构

```
enterprise-insight-agent/
├── app/
│   ├── agents/            # 11 个 Agent 节点
│   │   ├── supervisor_agent.py
│   │   ├── sales_agent.py / crm_agent.py / finance_agent.py
│   │   ├── inventory_agent.py / supply_chain_agent.py
│   │   ├── chart_advisor_agent.py / report_agent.py
│   │   ├── reflection_agent.py / memory_node.py
│   ├── adapters/          # 客户数据库结构适配层（3 层）
│   │   ├── schema_discovery.py    # 自动发现客户数据库结构
│   │   ├── schema_mapping.py      # 逻辑概念 → 物理表/列映射
│   │   └── prompt_builder.py      # 动态生成适配后的 Agent Prompt
│   ├── api/                # FastAPI 路由 + 中间件
│   │   ├── routes/         # 10 组路由（50 个端点）
│   │   ├── static/         # 前端静态文件
│   │   └── dependencies.py # 认证/权限/限流 依赖注入
│   ├── workflow/           # LangGraph 图谱定义
│   │   ├── graph.py        # 11 节点拓扑编排（compile）
│   │   └── state.py        # AnalysisState TypedDict
│   ├── auth/               # JWT + RBAC + 行级安全
│   ├── tools/              # SQL 执行/安全检查/记忆/嵌入/RAG
│   ├── database/           # ORM 模型 + 异步引擎
│   ├── middleware/          # 🆕 审计 + 多租户中间件
│   └── services/           # 🆕 通知服务（邮件 + Webhook）
├── web/                    # 🆕 React 18 + TypeScript 前端（重构中）
├── prompts/                # Prompt 模板（Python + YAML）
├── scripts/                # 🆕 部署/备份/验证/离线镜像脚本
├── tests/                  # 242 条测试用例
├── alembic/                # 13 个数据库迁移版本
├── docs/                   # 14 份产品/技术文档
├── ollama-models/          # 🆕 预打包 BGE-M3 模型目录
├── docker-entrypoint.sh    # 🆕 容器启动脚本
├── deploy.sh / deploy.bat  # 🆕 一键部署脚本
└── customer_schema.yaml    # 客户数据库结构映射配置
```

---

## API 一览

| 分组 | 端点 | 说明 |
|------|------|------|
| **认证** | `POST /api/v1/auth/login` `.../logout` | JWT 登录/登出 |
| **分析** | `POST /api/v1/analysis/analyze` | 提交分析（同步） |
| | `POST /api/v1/analysis/analyze-stream` | 提交分析（SSE 流式） |
| | `GET /api/v1/analysis/history` `.../history/{id}` | 历史记录查询 |
| | `GET /api/v1/analysis/similar` | 向量相似搜索 |
| **会话** | `POST /api/v1/session/create` `GET /.../{id}` | 多轮对话管理 |
| **Dashboard** | `GET /api/v1/dashboard/today-summary` | 今日经营快报 |
| **反馈** | `POST /api/v1/feedback/submit` `.../contact` `GET /.../history` | 用户反馈闭环（提交/意见反馈/我的历史） |
| | `GET /api/v1/feedback/stats` `.../admin-list` `.../analyze` | 管理端反馈统计 / 明细（admin-list V4.6.7） / Agent 聚合 |
| **管理** | `GET/POST/PUT/DELETE /api/v1/admin/users` | 用户 CRUD |
| | `POST /api/v1/admin/users/{id}/reset-password` | 密码重置 |
| | `POST /api/v1/admin/users/batch-import` | 批量导入 |
| | `POST /api/v1/admin/impersonate/{id}` 🆕 | 模拟登录 |
| | `GET /api/v1/admin/audit-logs` 🆕 | 审计日志查询 |
| | `GET /api/v1/admin/schema/discover` | 数据库结构自动发现 |
| | `POST /api/v1/admin/schema/preview-yaml` | 预览 YAML 映射 |
| | `GET /api/v1/admin/schema/test-connection` | 测试 DB 连接 |
| **Prompt** | `GET /api/v1/prompts` `.../{agent}` `POST .../reload` | Prompt 管理 + 热重载 |
| **周报** | `POST /api/v1/weekly/generate` `GET /.../reports` | 周报生成与查询 |
| **预警** | `POST /api/v1/alerts/check` `GET /.../rules` | 异常检测与规则管理 |
| **系统** | `GET /health` `GET /health/ready` | 健康检查（含 DB + Redis） |

> 全部路由使用 `/api/v1/` 前缀。旧版 `/api/` 自动 308 重定向。

---

## 数据库模型（25 张表）

| 类别 | 表名 | 说明 |
|------|------|------|
| **业务** | `store` / `orders` / `member` / `employee_performance` | 门店/订单/会员/绩效 |
| | `product` / `supplier` / `inventory` / `purchase_order` | 商品/供应商/库存/采购 |
| **权限** | `users` / `roles` / `permissions` | RBAC 三元组 |
| | `user_roles` / `role_permissions` / `user_store_access` | 角色-权限-门店关联 |
| **多租户** 🆕 | `tenants` | 租户信息 + 套餐/容量限制 |
| **审计** 🆕 | `audit_log` | 全量 API 操作审计（180 天保留） |
| **分析** | `analysis_history`（含 pgvector 嵌入） | 分析记录 + 向量语义搜索 |
| | `conversation_sessions` / `agent_trace_events` | 多轮对话 / APM 追踪 |
| **运营** | `alert_rules` / `alerts` / `weekly_reports` | 预警规则 / 预警记录 / 周报 |
| | `user_feedback` / `prompt_versions` | 反馈 / Prompt 版本管理 |

---

## 配置说明

### 必填（3 项）

```bash
DEEPSEEK_API_KEY=sk-your-key      # DeepSeek API Key
JWT_SECRET_KEY=a-random-64-chars   # JWT 签名密钥
POSTGRES_PASSWORD=strong-password   # 数据库密码
```

### V4 新增配置

```bash
LOG_FORMAT=console                  # console | json（生产环境用 json）
SYSTEM_USER_ID=0                    # 系统用户 ID（定时任务用）
# 通知 Webhook（可选，留空不发送）
FEISHU_WEBHOOK_URL=                 # 飞书机器人 webhook
DINGTALK_WEBHOOK_URL=               # 钉钉机器人 webhook
WECOM_WEBHOOK_URL=                  # 企业微信机器人 webhook
```

### 功能开关（8 个 Feature Flag，默认全开）

| Flag | 控制 | 默认 |
|------|------|:--:|
| `FEATURE_CHART` | ECharts 图表可视化 | ✅ |
| `FEATURE_MULTI_TURN` | 多轮对话上下文 | ✅ |
| `FEATURE_DATA_TRACE` | 数据来源可追溯 | ✅ |
| `FEATURE_FEEDBACK` | 用户反馈闭环 | ✅ |
| `FEATURE_APM` | Agent 性能追踪 | ✅ |
| `FEATURE_FRIENDLY_ERRORS` | 中文友好错误 | ✅ |
| `FEATURE_PROMPT_YAML` | Prompt YAML 外部化 | ✅ |
| `FEATURE_MOBILE_UI` | 移动端适配 | ✅ |

---

## 测试

```bash
pytest tests/ -v
# 242 collected, 238 passed, 4 failed（均为环境问题：LLM API 连接 ×2 + 配置测试 .env 污染 ×2，重跑可恢复）
```

---

## 文档索引

| 文档 | 说明 |
|------|------|
| **[启动指南](docs/启动指南.md)** | Docker/手动部署 + 首次引导 + FAQ |
| **[部署方案](docs/启动指南.md)** | 一键部署 + 离线部署 + 备份策略 |
| **[升级指南](UPGRADE.md)** | V4 版本升级与回滚 |
| **[AI 产品需求文档](docs/AI-PRD-V4.md)** | AI 能力定义 · 评估方案 · 成本模型 |
| **[产品需求文档 PRD](docs/产品需求文档-PRD.md)** | 完整功能规格 · 数据库 · API · 路线图 |
| **[竞品分析](docs/竞品分析.md)** | 竞争格局 · 壁垒 · 30 秒电梯演讲 |
| **[商业思考](docs/商业思考.md)** | 定价/GTM/市场规模/单位经济 |
| **[CHANGELOG](CHANGELOG.md)** | V4 60 项修复全记录 |
| **[V1-V4 四版对比](docs/V1-V2-V3-V4-四版对比.md)** | 完整版本演化 |
| **[AI 产品设计原则](docs/AI产品设计原则.md)** | 7 条方法论 + AI 产品指标体系 |
| **[Prompt 迭代日志](docs/Prompt迭代日志.md)** | 5 次 Prompt 迭代全记录 |
| **[Bad Case 复盘](docs/BadCase复盘.md)** | 3 个 AI 犯错复盘案例 |

---

## 许可证

MIT License © 2025 高志远
