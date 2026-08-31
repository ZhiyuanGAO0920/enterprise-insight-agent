# Enterprise Insight Agent V5 — 项目全貌

> Codex 新窗口自动加载此文件即可了解项目。

---

## 项目定位

面向连锁零售的 Multi-Agent AI 经营分析平台。10 个 Agent 协作，用户用自然语言提问，60 秒内获得含数据概览、根因诊断、可执行建议的诊断报告。

**作者**：高志远（独立产品负责人，产品设计/架构决策/评估体系）
**状态**：V5.0.0（收官版），242 条测试（238 通过 / 4 失败——均为本地环境问题：LLM API 连接 ×2 + 配置测试 .env 污染 ×2，重跑可恢复）
**Demo 数据**：100 门店 / 50,925 订单 / 5,000 会员 / 30 供应商

---

## 架构速览

```
Supervisor（规划路由，temperature=0）
    ↓ LangGraph Send 并行扇出
[sales] [crm] [finance] [inventory] [supply_chain]  ← 5 领域 Agent
    ↓ 扇入
Aggregator（纯 Python 聚合，不耗 Token）
    ↓
Chart Advisor → Report Agent（SSE 流式输出）→ Reflection Agent（4 维质检，最多重试 1 次）
    ↓
Save Memory（pgvector 1024 维，BGE-M3 本地 Embedding）
```

**关键文件**：
- `app/workflow/graph.py` — 11 节点 StateGraph 编排
- `app/agents/supervisor_agent.py` — 路由决策（LLM + 关键词兜底）
- `app/agents/report_agent.py` — 流式报告生成 + 图表注入 + FOLLOWUP 提取
- `app/agents/reflection_agent.py` — 4 维质检（V4.2：区分查询型/分析型标准）
- `app/agents/chart_advisor_agent.py` — 图表推荐 + 规则兜底表格解析
- `app/tools/sql_runner.py` — RLS 注入（V4.2：sqlparse AST 解析）
- `app/tools/stream_utils.py` — safe_get_stream_writer 降级兜底

---

## 技术栈

| 层 | 技术 |
|----|------|
| Agent 编排 | LangGraph StateGraph + Send 并行 |
| LLM | DeepSeek-V4（¥1/Mtok 输入，¥2/Mtok 输出）|
| Embedding | BGE-M3 本地 Ollama，1024 维 |
| 后端 | FastAPI + SSE 流式 + PostgreSQL 16 + pgvector + Redis 7 |
| 前端 | 原生 HTML/CSS/JS + ECharts 5 |
| 部署 | Docker Compose 5 容器 + n8n 定时调度 |
| 日志 | **structlog** + trace_id 全链路追踪 |
| 安全 | JWT + bcrypt + RBAC + **审计日志 + 多租户** |

---

## 目录结构

```
app/
├── agents/          # 11 个 Agent 节点（含 supervisor, 5 领域, aggregator, chart, report, reflection, memory）
├── api/routes/      # 10 个路由组，50 个端点
│   ├── analysis.py  # /analyze + /analyze-stream（SSE）
│   ├── dashboard.py # /today-summary + /overview
│   ├── alerts.py    # /check（n8n 定时触发 + 飞书/钉钉/企微通知）
│   └── weekly.py    # /generate + /export（PDF）
├── auth/            # JWT + RBAC + RLS（行级安全）
├── database/        # 16 ORM 模型，10 版 Alembic 迁移
├── middleware/       # 🆕 audit.py（审计日志） + tenant.py（多租户）
├── services/        # notification.py + pdf_exporter.py
├── tools/           # sql_runner.py（RLS 注入），prompt_loader.py（3 级 fallback）
└── workflow/        # graph.py（StateGraph 编排），state.py（AnalysisState TypedDict）
prompts/
├── yaml/            # 9 个 Agent Prompt（FEATURE_PROMPT_YAML=true 时生效）
├── report_prompt.py # Python 硬编码兜底
└── yaml/CHANGELOG.md
scripts/             # deploy.sh, backup.sh, seed_data.py, enrich_demo_data.py, record_demo.py
workflows/n8n-templates/  # alert-check.json, weekly-report.json
```

---

## 核心产品决策（速查）

| # | 决策 | 一句话 |
|---|------|--------|
| 1 | Multi-Agent vs 单 Agent | 上下文竞争（3000 token 数据库结构 + 注意力衰减）+ 故障隔离 + 迭代效率 |
| 2 | Reflection 重试 1 次 | 0 次→25% 报告有问题；1 次→修复率 60%，成本 3000-5000 token；2 次边际递减 |
| 3 | 流式优先 | 95%+ 查询是新问题，缓存命中率极低 |
| 4 | 数据库结构三层适配器 | 自动发现→YAML 映射→Prompt 生成，零驻场部署 |
| 5 | 双模式输出 | 查询型→表格+关键洞察，分析型→完整报告 |
| 6 | 经营看板作为首页 | 解决用户"冷启动焦虑" |
| 14 | n8n vs cron | 运维可视化 + 扩展性 + 非技术人员友好 |

---

## V4 修复记录

| 版本 | 日期 | 主要内容 |
|------|------|----------|
| [V4.5.0](CHANGELOG.md#V450-2026-07-29) | 2026-07-29 | 前端重构 + 反馈闭环 + 性能优化 |
| [V4.2.0](CHANGELOG.md#V420-2026-07-27) | 2026-07-27 | 报告质量升级（四段式方法论）、41 项安全/稳定性/测试修复 |
| [V4.1.0](CHANGELOG.md#V410-2026-07-16) | 2026-07-16 | 质量监控面板、真实成本追踪、评估测试集扩充 |
| [V4.0.0](CHANGELOG.md#V400-2026-06-11) | 2026-06-11 | 60 项修复（无限循环/LLM 成本翻倍/XSS/SQL 注入等） |

---

## Prompt 机制

优先级：`customer_schema.yaml` > `prompts/yaml/*.yaml` > Python 硬编码
热重载：`POST /api/v1/prompts/reload`（改 Prompt 不用重启）
Feature Flag：`FEATURE_PROMPT_YAML=true`（当前启用）

---

## 面试资料速查

所有面试文档在 `docs/` 下：
- `AI产品经理面试作战包.md` — 15 章完整作战包（自我介绍/决策案例/BadCase/Q&A/讲稿/追问FAQ）
- `AI产品经理核心知识手册_v1.1.md` — AI PM 理论参考书（LLM/RAG/Agent/Prompt/运维/面试）
- `AI功能交互流程.md` — 全链路交互（正常/异常/边界）
- `Demo视频脚本-V4.md` — 9 段视频脚本
- `作品集-EIA-V4.md` — 10 章作品集（截图+架构+数据）
- `面试准备计划.md` — 5 天计划
- `个人简历-AI产品经理.md` / `个人简历-B端产品经理.md` — 两份简历（已 gitignore）
- `启动指南.md` → 已移至 `docs/启动指南.md`

---

## 运维须知

- 三版本同时运行：V2(8000) / V3(8001) / V4(8002)
- PostgreSQL: `localhost:15432`，admin / admin123（Docker）
- Redis: `localhost:6381`（Docker）
- n8n: `http://localhost:5678`（Docker）
- 启动：双击 `重启服务.bat` 或 `uvicorn app.api.main:app --port 8002 --reload`
- 热重载 Prompt：`POST /api/v1/prompts/reload`
- 测试：`pytest tests/ -v`（242 条）
- 数据库迁移：`alembic upgrade head`（当前 10 个版本）
