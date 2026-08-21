# Enterprise Insight Agent V4 — 项目全貌

> Claude 新窗口自动加载此文件即可了解项目。

---

## 项目定位

面向连锁零售的 Multi-Agent AI 经营分析平台。11 个 Agent 协作，用户用自然语言提问，60 秒内获得含数据概览、根因诊断、可执行建议的诊断报告。

**作者**：高志远（独立产品负责人，产品设计/架构决策/评估体系）
**状态**：V4.8，213 条测试（211 通过 / 2 失败——LLM API 连接环境问题，重跑可恢复），GitHub 开源。**金丝雀闭环**：eval 结果落库 `eval_runs`（带 model_version），16 条固定子集**每周一次** **应用内 asyncio 定时**跑分（T-12，每日 09:30 检查，幂等判据：最近 7 天已有 canary 记录则跳过，省 DeepSeek 配额；n8n 侧同工作流保留双保险），与同模型基线对比超阈值自动告警（模型漂移检测）。V4.8 另含：PII 脱敏（T-03，sql_runner 结果出口 + 审计 query_params 集中掩码）、金丝雀漂移监控面板（T-11，原生 + React 双版）
**任务清单**：[TASKS.md](TASKS.md) — 项目唯一任务清单（当前 10 项，每项含目标/状态/修改范围/停止条件/验证数据）。开工前必读；任务完成必须归档并附验证数据与 commit
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
- `app/agents/report_agent.py` — 流式报告生成 + FOLLOWUP 提取
- `app/agents/reflection_agent.py` — 4 维质检（一致性/逻辑/可操作/完整）

---

## 技术栈

| 层 | 技术 |
|----|------|
| Agent 编排 | LangGraph StateGraph + Send 并行 |
| LLM | DeepSeek-V4（¥1/Mtok 输入，¥2/Mtok 输出）|
| Embedding | BGE-M3 本地 Ollama，1024 维 |
| 后端 | FastAPI + SSE 流式 + PostgreSQL 16 + pgvector + Redis 7 |
| 前端 | 原生 HTML/CSS/JS + ECharts 5 |
| 部署 | Docker Compose 5 容器 + 应用内 asyncio 定时（金丝雀）+ n8n（周报/告警调度） |
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
├── database/        # 17 ORM 模型，13 版 Alembic 迁移
├── middleware/       # 🆕 audit.py（审计日志） + tenant.py（多租户）
├── services/        # notification.py + pdf_exporter.py + masker.py（PII 脱敏）
├── scheduler.py     # 🆕 金丝雀定时兜底（每日 09:30 检查，7 天幂等窗口 = 每周一次，不依赖 n8n）
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

## V4 本轮修复记录（2026-06-11，60项）

详见 [CHANGELOG.md](CHANGELOG.md)。关键修复：
- `reflection_retries` 永不递增 → 无限循环 → 反射节点正确返回 `reflection_retries`
- 流式端点图执行两次 → LLM 成本翻倍 → `stream_mode=["updates","values"]` 单次执行
- `build_store_filter_sql` SQL 注入 → 单引号转义 + 列名白名单
- 审计中间件 `BaseHTTPMiddleware` 不触发 → 改为 FastAPI 原生 `@app.middleware("http")`
- `save_analysis_history` 不填 `tenant_id` → NOT NULL 违反 → 自动查询用户/默认租户
- `analysis_history.tenant_id` 历史数据回填 + FK 约束（迁移 007）
- 前端 XSS：`marked.parse()` 无转义、onclick 注入 → 添加 `htmlEscape`/`jsEscape`
- 反馈按钮 `submitFeedback(id)` 参数不匹配 → 改为 `showFeedback('helpful')`
- `asyncio.run()` 与 pytest-asyncio 事件循环冲突 → 全部改为 `@pytest.mark.asyncio`
- 图表函数 `_build_*`/`_encode_*` → 重命名为公共 API `build_*`/`encode_*`
- `启动服务.bat` 与 `启动V4服务.bat` 重复 → 删除前者
- `启动指南.md` → 移至 `docs/`

---

## Prompt 机制

优先级：`customer_schema.yaml` > `prompts/yaml/*.yaml` > Python 硬编码
热重载：`POST /api/v1/prompts/reload`（改 Prompt 不用重启）
Feature Flag：`FEATURE_PROMPT_YAML=true`（当前启用）

---

## 面试资料速查

所有面试文档在 `docs/` 下：
- `AI产品经理面试作战包.md` — 16 章完整作战包（自我介绍/决策案例/BadCase/Q&A/讲稿/追问FAQ/能力自评与卖点话术）

> ⚠️ **同步规则**：更新 docs/ 下面试文档后，必须同步镜像到 Obsidian（docs 为源，Obsidian 为镜像；覆盖前先备份到 `D:\Obsidian备份\YYYY-MM-DD-GZY备份\`，覆盖后 diff 校验 0 差异）：面试准备类 → `3-职业发展/面试准备/`；核心知识手册 → `2-AI产品经理/核心知识/`；作品集 Obsidian 侧为 PDF，需手工重新导出。详见记忆 `docs-obsidian-sync-habit`。

- `AI产品经理核心知识手册_v1.1.md` — AI PM 理论参考书（LLM/RAG/Agent/Prompt/运维/面试；文档内版本 v1.2，2026-08 新增 2.8 节 2026 RAG 前沿；镜像 `2-AI产品经理/核心知识/`）
- `AI功能交互流程.md` — 全链路交互（正常/异常/边界）
- `监控页指标设计原则.md` — 决策台 vs 数据仓库：13 项指标裁决表 + 四象限（V4.6.6 落地）
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
- n8n: `http://localhost:5680`（Docker）
- 启动：双击 `重启服务.bat` 或 `uvicorn app.api.main:app --port 8002 --reload`
- **改 `app/api/static/` 前端文件后必须 bump 版本号**（`index.html` 里 `views.js?v=4.56` 等 `?v=` 参数，否则浏览器命中旧缓存，改动"看起来没生效"）——T-11 排查踩坑沉淀
- 热重载 Prompt：`POST /api/v1/prompts/reload`
- 测试：`pytest tests/ -v`（213 条）
- 数据库迁移：`alembic upgrade head`（当前 13 个版本）
