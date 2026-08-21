---
description: EIA V4 项目开发上下文 — 给任何 AI 工具理解这个项目的启动包
metadata:
  type: reference
---

# EIA V4 — 项目开发场景启动包

> **上传此文件后，AI 进入 EIA V4 开发协作模式。**

---

## 一句话定位

面向连锁零售的 Multi-Agent AI 经营分析平台。用户用自然语言提问，系统 60 秒内输出含数据概览、根因诊断、可执行建议的诊断报告。

**作者**：高志远（独立产品负责人，产品设计/架构决策/评估体系）
**状态**：V4.8，213 条测试（211 通过 / 2 失败——LLM API 连接环境问题，重跑可恢复），GitHub 开源。V4.8 含**金丝雀闭环**：eval 结果落库 `eval_runs`（带 model_version），16 条固定子集每周自动跑分（每日 09:30 兜底检查，7 天幂等窗口），与同模型基线对比超阈值自动告警（模型漂移检测）
**Demo 数据**：100 门店 / 50,925 订单 / 5,000 会员 / 30 供应商

---

## 核心架构

```
Supervisor（规划路由，temperature=0）
    ↓ Send 并行扇出
[sales] [crm] [finance] [inventory] [supply_chain]  ← 5 领域 Agent
    ↓ 扇入
Aggregator（纯 Python 聚合，不耗 Token）
    ↓
Chart Advisor → Report Agent（SSE 流式输出）→ Reflection Agent（4 维质检，最多重试 1 次）
    ↓
Save Memory（pgvector 1024 维，BGE-M3 本地 Embedding）
```

**编排引擎**：LangGraph StateGraph + Send API 并行扇出

**关键设计**：
- Supervisor 用 LLM 判断用户意图 + 关键词匹配兜底，决定扇出哪些 Agent
- 5 个领域 Agent 通过 LangGraph Send 并行执行，互不等待
- Aggregator 纯 Python 拼接，不消耗 Token
- Report Agent SSE 流式输出，首个 token 在 2-3 秒内到达
- Reflection Agent 从 4 个维度质检：数据一致性 / 逻辑严谨性 / 建议可操作性 / 覆盖完整性
- Retry 上限 1 次（实验结论：0 次→25%有问题；1 次→60%修复率；2 次边际递减）

---

## 技术栈

| 层 | 技术 |
|----|------|
| Agent 编排 | LangGraph StateGraph + Send |
| LLM | DeepSeek-V4（¥1/Mtok 输入，¥2/Mtok 输出）|
| Embedding | BGE-M3（本地 Ollama，1024 维）|
| 后端 | FastAPI + SSE 流式 |
| 数据库 | PostgreSQL 16 + pgvector |
| 缓存 | Redis 7 |
| 前端 | 原生 HTML/CSS/JS + ECharts 5 |
| 部署 | Docker Compose 5 容器 |
| 定时调度 | n8n（告警检查 + 周报生成）|
| 日志 | structlog + trace_id 全链路追踪 |
| 安全 | JWT + bcrypt + RBAC + 审计日志 + 多租户 RLS |

---

## 目录结构

```
app/
├── agents/          # 11 个 Agent 节点
├── api/routes/      # 10 个路由组，50 个端点
├── auth/            # JWT + RBAC + RLS
├── database/        # 17 ORM 模型，13 版 Alembic 迁移
├── middleware/       # 审计日志 + 多租户
├── services/        # 通知 + PDF 导出
├── tools/           # SQL 运行器 + Prompt 加载器
└── workflow/        # StateGraph 编排 + 状态定义
prompts/
├── yaml/            # 9 个 Agent Prompt
├── report_prompt.py # Python 硬编码兜底
└── yaml/CHANGELOG.md
scripts/             # 部署/备份/数据填充
workflows/n8n-templates/
```

---

## 关键产品决策

| # | 决策 | 一句话 |
|---|------|--------|
| 1 | Multi-Agent vs 单 Agent | 上下文竞争（3000 token 数据库结构 + 注意力衰减）+ 故障隔离 + 迭代效率 |
| 2 | Reflection 重试 1 次 | 0 次→25% 有问题；1 次→修复率 60%，成本 3000-5000 token；2 次边际递减 |
| 3 | 流式优先 | 95%+ 查询是新问题，缓存命中率极低，流式进度条改善等待体验 |
| 4 | 数据库结构三层适配器 | 自动发现→YAML 映射→Prompt 生成，零驻场部署 |
| 5 | 双模式输出 | 查询型→表格+关键洞察，分析型→完整报告 |
| 6 | 经营看板作为首页 | 解决用户冷启动焦虑 |
| 7 | n8n 定时调度 | 运维可视化 + 扩展性 + 非技术人员友好 |

---

## Prompt 机制

**三级 fallback**：`customer_schema.yaml` > `prompts/yaml/*.yaml` > Python 硬编码
**热重载**：`POST /api/v1/prompts/reload`（改 Prompt 不用重启服务）
**Feature Flag**：`FEATURE_PROMPT_YAML=true`

---

## 安全设计

- JWT 认证 + bcrypt 密码哈希
- RBAC 三角色：admin（全部数据）/ manager（本区域数据）/ store（本店数据）
- **RLS 行级安全**：`inject_store_filter` 在 SQL 层注入 WHERE store_id IN (...)，根据用户角色自动过滤
- 审计日志：`@app.middleware("http")` 记录所有请求的 user_id、path、method、status_code
- 多租户：`tenant_id` 列 + `build_store_filter_sql` 白名单校验
- **对抗式安全审查（V4.7）**：21 项发现 / 16 项修复——RLS 注入器重写 / UNION 越权 / 多租户中间件 / 微信后门 / ECharts tooltip XSS

---

## 评估体系（AI 质量三层 + 金丝雀闭环）

1. **离线评估集**：102 条标准问题（50 查询 + 38 分析 + 14 边界，覆盖 5 领域 + 综合 + 边界），每次 Prompt 修改后自动运行
2. **Reflection 在线质检**：4 维度，每次分析后自动执行
3. **用户反馈闭环**：👍👎 按钮，写入 `user_feedback` 表驱动 Prompt 迭代
4. **金丝雀闭环（V4.7）**：eval 结果落库 `eval_runs`（带 model_version），16 条固定子集每周自动跑分（每日 09:30 兜底检查，7 天幂等窗口，应用内调度 + n8n 双保险），与同模型基线对比超阈值自动告警——检测模型漂移/API 变更导致的隐性质量退化

---

## 运维数据

- 三版本并行：V2(8000) / V3(8001) / V4(8002)
- PostgreSQL: `localhost:15432`，admin/admin123
- Redis: `localhost:6381`
- n8n: `http://localhost:5678`
- 启动：`uvicorn app.api.main:app --port 8002 --reload`
- 测试：`pytest tests/ -v`（192 条）
- 迁移：`alembic upgrade head`（当前 13 版）

---

## 今天开发任务（请 AI 据此调整）

> **下面几行由用户每次开始开发前填写，AI 按照最新内容执行。**

```
今天任务：【              】   ← 例：修复 Bug / 设计新功能 / 写测试 / 重构模块
涉及文件：【              】   ← 例：app/agents/report_agent.py
目标描述：【              】   ← 具体的需求和期望结果
约束条件：【              】   ← 例：不需改数据库 / 兼容现有 API
```

---

## AI 协作规范（EIA 开发模式）

1. **先理解再动手**——解释你对任务的理解，确认方向正确再开始写代码
2. **改动范围最小化**——不重构未涉及的部分，不"顺手"改不相关代码
3. **提供改动前后对比**——说明每处改动的理由和预期影响
4. **涉及数据库**——先确认是否需要迁移，优先向前兼容
5. **涉及 API**——保持现有端点兼容性，新增端点加版本前缀

---

> 完整项目决策记录在 `docs/关键产品决策记录.md`，完整 PRD 在 `docs/AI-PRD-V4.md`，如需深入细节可引用。
> 版本：V4.7 | 2026-08-12 | 同步金丝雀闭环 / 对抗式安全审查 / 50 端点 / 13 迁移
