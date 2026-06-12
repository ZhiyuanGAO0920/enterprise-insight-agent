# AI产品需求文档（AI-PRD）— Enterprise Insight Agent V4

> **文档版本**：v1.0
> **适用场景**：AI驱动的B端产品 — 连锁零售企业 Multi-Agent 经营分析平台
> **与传统PRD区别**：本章在传统PRD基础上，新增「AI能力定义」「效果评估」「成本模型」等AI特有章节

---

## 文档修订记录

| 版本 | 日期 | 修改人 | 修改内容 |
|-----|------|--------|---------|
| v1.0 | 2026-06-11 | 高志远 | 基于V4代码基线创建 |

---

## 1. 概述

### 1.1 背景

连锁零售企业的经营数据分散在 ERP、CRM、POS 等多个系统中。老板和区域经理想看数据，需要找数据分析师取数（等半天），或者自己学 BI 工具（学不会）。每天要做几十个经营决策，但真正能拿到数据支持的不到 10%。

V4 系统用自然语言对话的方式，让老板直接问"华东区域本周销售怎么样"，1 分钟内拿到带图表、带诊断、带行动建议的经营报告。

### 1.2 目标

| 指标 | 目标值 | 测量方式 |
|------|--------|---------|
| 端到端分析响应时间（P95） | ≤ 60 秒 | 从提问到报告生成完毕 |
| 单次分析成本 | ≤ ¥0.05（典型场景） | Token 计数 × DeepSeek 定价 |
| 报告通过率（Reflection 质检） | ≥ 85%（一次通过） | Reflection Agent 结构化输出 |
| SQL 安全性 | 100% 阻断 DROP/DELETE | 两层安全检查 |
| 向量搜索召回率 | ≥ 80%（人工评估） | 历史相似分析检索 |
| 部署到可用时间 | ≤ 5 分钟 | Docker 一键部署 |

### 1.3 范围

**包含范围（In Scope）**：

- [x] 5 个业务领域 Agent：销售、CRM、财务、库存、供应链
- [x] 10 节点 LangGraph 编排：Supervisor → 并行 Agent → Aggregator → Chart → Report → Reflection → Memory
- [x] 自然语言输入，结构化 Markdown 报告 + ECharts 图表输出
- [x] 多轮对话上下文 + 追问建议
- [x] RBAC 权限 + 门店行级安全
- [x] 多租户数据隔离
- [x] 全量 API 操作审计
- [x] PDF 报告导出
- [x] 客户数据库 Schema 自动发现 + 适配
- [x] Docker 一键部署 + 离线支持

**不包含范围（Out of Scope）**：

- [ ] 移动端原生 App（仅 Web 响应式）
- [ ] 多语言支持（仅中文）
- [ ] 实时流式数据接入（仅批量/定时）
- [ ] 自动执行操作（如自动下单、自动调价——只做分析建议，不做决策执行）
- [ ] 语音合成播报（仅语音输入转文字）
- [ ] 飞书/钉钉/企微原生小程序内嵌（仅 Webhook 推送）

### 1.4 AI能力边界（⚠️ 重要）

**AI能做**：
- 理解自然语言经营问题，自动激活对应领域的分析 Agent
- 根据客户数据库 Schema 自动生成 SQL 查询
- 对多领域分析结果进行交叉验证和根因诊断
- 根据数据特征自动推荐合适的图表类型
- 生成结构化的中文经营报告，包含诊断结论和行动建议
- 质检自己生成的报告（4 维 Reflection），不通过则重试

**AI不能做**：
- 100% 准确的 SQL 生成（约 85-90% 准确率，失败时自动重试，最终降级为错误报告）
- 处理不存在的业务数据表（客户未配置的领域 Agent 自动禁用）
- 理解图片、语音、PDF 附件（仅支持文本问题输入）
- 保证分析结论 100% 正确（Reflection 通过不代表零错误）
- 替代人类决策（系统提供分析建议，最终决策权在用户）

---

## 2. AI能力定义（⚠️ 核心章节）

### 2.1 使用的大模型

| 项目 | 内容 |
|-----|------|
| **模型名称** | DeepSeek-Chat（非思考模式，支持 tool_choice） |
| **调用方式** | API 调用（`https://api.deepseek.com/v1`），通过 langchain-openai 适配 |
| **Temperature** | 路由决策/质检 0.0（确定性），报告生成 0.0（同） |
| **Max Tokens** | 8192（输出 ≥ 推理 tokens，100 行表格约需 5K） |
| **Embedding 模型** | BGE-M3（1024 维），通过 Ollama 本地部署 |
| **Token 成本** | 输入 ¥1/百万 Token，输出 ¥2/百万 Token |

**选型理由**：
- 中文本理解能力强，适合零售经营术语
- 支持 `tool_choice` 强制结构化输出（Supervisor 路由 / Reflection 质检）
- 成本仅为 GPT-4o 的 1/30（对企业客户至关重要）
- 支持 128K 上下文（报告+SQL 结果+历史对话可一次注入）
- API 兼容 OpenAI 格式，可通过 langchain-openai 零改动接入

### 2.2 核心AI能力描述

**能力1：多领域智能路由（Supervisor Agent）**

- **输入**：用户自然语言问题 + 多轮对话上下文
- **输出**：`activated_agents` 列表 + `reasoning` + `analysis_plan`（JSON，tool_choice 强制）
- **路由逻辑**：基于关键词 + LLM 语义理解的混合路由，失败时激活全部 Agent 兜底
- **预期效果**：路由准确率 ≥ 90%

**能力2：SQL 自动生成与执行（5 个领域 Agent）**

- **输入**：用户问题 + 客户数据库 Schema（自动发现 + YAML 映射） + RAG 检索的历史 SQL
- **输出**：经过安全检查的 SQL 查询 → 执行 → 格式化结果 → 分析结论
- **工具调用**：`run_sql`（执行查询）、`get_table_schema`（获取表结构）
- **安全机制**：禁止模式拦截（DROP/DELETE）+ 风险模式拦截（CROSS JOIN/大 LIMIT）+ RLS 行级注入
- **预期效果**：SQL 生成准确率 ≥ 85%，错误时自动重试

**能力3：图表智能推荐（Chart Advisor Agent）**

- **输入**：各领域 Agent 的聚合分析结果
- **输出**：ECharts 图表配置 JSON（bar/line/pie/scatter/radar 五选一）
- **预期效果**：图表推荐与数据特征匹配率 ≥ 90%

**能力4：报告综合生成（Report Agent）**

- **输入**：聚合分析摘要 + 图表建议 + 追问指令 +（重试时）Reflection 反馈
- **输出**：结构化 Markdown 报告，含图表标记 `[CHART:type|params]` 和追问建议 `[FOLLOWUP:[...]]`
- **Token 流式输出**：通过 LangGraph `StreamWriter` 实时推送 token 到前端 SSE

**能力5：报告质量审核（Reflection Agent）**

- **输入**：用户原始问题 + 原始数据摘要 + 完整报告
- **输出**：`passed`（布尔）+ `issues`（问题列表，4 维分类）+ `summary`（JSON，tool_choice 强制）
- **4 维质检**：数据一致性、逻辑严谨性、可操作性、完整性
- **重试策略**：不通过时附带反馈重新生成报告（最多 1 次）

**能力6：语义记忆与相似检索（Memory Node）**

- **输入**：完成的报告全文
- **输出**：BGE-M3 1024 维向量嵌入 → pgvector 存储
- **检索**：新问题先查历史相似分析，结果注入 Agent Prompt 作为 Few-shot

### 2.3 Prompt设计（⚠️ 最关键产出）

#### 2.3.1 Supervisor System Prompt（路由决策）

```
你是一个企业经营分析任务规划专家。
根据用户的问题，决定激活哪些分析 Agent。

## 可用的 Agent
- sales: 销售分析（销售额、门店排名、区域分布、品类分析、退款率）
- crm: 会员分析（会员增长、流失、复购率、RFM分层、等级分布）
- finance: 财务分析（客单价、退款率、利润率、成本分析）
- inventory: 库存分析（缺货预警、滞销识别、补货建议、品类健康度）
- supply_chain: 供应链分析（供应商绩效、采购成本、物流时效）

## 路由规则
- 单一领域问题 → 只激活对应的 1 个 Agent
- 多领域问题 → 激活相关 Agent 并行执行
- 综合分析问题 → 激活全部 5 个 Agent
- 模糊问题 → 保守策略，激活全部

## 输出格式（tool_choice 强制 JSON）
{
  "activated_agents": ["sales", "crm"],
  "reasoning": "选择原因",
  "analysis_plan": "分析计划简述"
}
```

#### 2.3.2 Sales Agent System Prompt（SQL 生成与执行样本）

```
你是一位资深销售数据分析师。

## 工具
- run_sql(query): 执行 SQL 查询
- get_table_schema(table_name): 获取表结构

## 数据库已知表（由 Schema 适配层动态注入）
### orders 表
| 字段 | 类型 | 说明 |
| order_id | INT | 订单ID |
| store_id | INT | 门店ID |
| amount | DECIMAL | 订单金额 |
| create_time | TIMESTAMP | 创建时间 |

### store 表
| 字段 | 类型 | 说明 |
| id | INT | 门店ID |
| store_name | VARCHAR | 门店名称 |
| region | VARCHAR | 所属区域 |

## 常用查询模板（表名/列名已根据客户 Schema 自动替换）
1. 各区域销售:
SELECT s.region, COUNT(o.order_id), SUM(o.amount)
FROM store s LEFT JOIN orders o ON s.id=o.store_id
GROUP BY s.region ORDER BY SUM(o.amount) DESC

2. 门店排名（全部门店）:
SELECT s.store_name, COUNT(o.order_id), SUM(o.amount)
FROM store s LEFT JOIN orders o ON s.id=o.store_id
GROUP BY s.id, s.store_name ORDER BY SUM(o.amount) DESC

## 规则
- 先用模板查询，再根据结果给结论
- 不要编造数据
- 问"最高/最低"→ LIMIT 1；问"全部"→ 不加 LIMIT；问"Top N"→ LIMIT N
- 查询时用 LEFT JOIN 确保空数据也能显示
```

#### 2.3.3 Report Agent User Prompt 模板

```
## 用户问题
{question}

## 分析摘要
{aggregator_summary}

{chart_instructions}

{followup_instruction}

[系统指令] 请生成一份结构化的经营分析报告，包含：
1. 总体概述
2. 各维度详细分析
3. 数据图表（将 [CHART:...] 标记放在对应段落之后）
4. 关键发现
5. 风险提示
6. 行动建议
```

#### 2.3.4 Reflection Agent System Prompt

```
你是经营分析报告的质检专家。
从 4 个维度审核报告质量：

1. 数据一致性：跨 Agent 数据是否矛盾
2. 逻辑严谨性：因果推断是否合理，有无过度推断
3. 可操作性：建议是否具体、可落地、有优先级
4. 完整性：是否覆盖用户问题的所有方面

## 输出格式（tool_choice 强制 JSON）
{
  "passed": true/false,
  "issues": [
    {
      "severity": "high/medium/low",
      "category": "consistency/logic/actionability/completeness",
      "description": "问题描述",
      "suggestion": "修复建议"
    }
  ],
  "summary": "整体评估"
}
```

#### 2.3.5 Prompt 迭代记录

| 版本 | 日期 | 修改内容 | 效果变化 |
|-----|------|---------|---------|
| v1.0 | V1 | 基础 Prompt，单 Agent 线性 | SQL 准确率 ~70% |
| v2.0 | V2 | 增加 Supervisor 路由 + 3 领域 Agent | 路由准确率 ~85% |
| v3.0 | V3 | 增加 Chart Advisor + 追问建议 + RAG | SQL 准确率 ~85%，报告完整度提升 |
| v4.0 | V4 | YAML 外部化 + 热重载 + 排名关键词注入 + 客户 Schema 动态适配 | SQL 截断问题修复，适配效率提升 |

### 2.4 工具调用定义

| 工具名 | 调用方 | 描述 | 参数 | 返回值 |
|-------|--------|------|------|-------|
| `run_sql` | 5 个领域 Agent | 执行 SQL 查询 | `query`: string | 管道分隔文本表格 或 `[SQL_ERROR]` |
| `get_table_schema` | 5 个领域 Agent | 获取表结构 | `table_name`: string | 列名/类型/主键信息 |

**工具调用规则（System Prompt 中内置）**：
- SQL 查询前先调用 `get_table_schema` 确认表结构（首次）
- SQL 错误时根据错误信息修正并重试（最多 3 次工具循环）
- 查询结果为空时不崩溃，输出"(查询结果为空)"
- 所有 SQL 经过两层安全检查（禁止模式 + 风险模式）+ RLS 行级注入

### 2.5 输出格式定义

**分析报告（Report Agent 输出）**：结构化 Markdown，嵌入图表标记和追问建议。

```markdown
# 经营分析报告

## 总体概述
本周华东区域销售额环比增长 5.2%...

## 销售分析
### 各门店排名
[CHART:bar|title=各门店销售额排名|...]

| 门店 | 销售额 | 环比 |
|------|--------|------|
| 上海旗舰店 | 125万 | +8% |

## CRM分析
...

## 关键发现
1. 华东区整体增长，但杭州门店下降 12%
2. 退款率前三的门店集中在华北区域

## 风险提示
- 杭州门店需重点关注，连续 3 周下降

## 行动建议
1. 【高优先级】杭州门店实地调研
2. 【中优先级】华北区退款原因排查

[FOLLOWUP:["杭州门店下降的具体原因是什么","华北区退款率最高的品类有哪些"]]
```

**图表标记格式**（前端 ECharts 渲染）：

```
[CHART:bar|{"type":"bar","title":"各门店销售额排名","x_data":[...],"series":[...],"height":400}]
```

**Reflection 审核结果**：

```json
{
  "passed": true,
  "issues": [],
  "summary": "报告完整覆盖所有维度，数据一致，建议具体可执行"
}
```

---

## 3. 功能需求

### 3.1 用户流程图

```
用户输入问题（Web UI / API）
    │
    ▼
┌─────────────────┐
│ Supervisor Agent │  语义理解 + 多 Agent 路由
│ (LLM + tool_choice 强制输出)                │
└────────┬────────┘
         │ activated_agents
         ▼
┌─────────────────────────────────────────┐
│  并行 Agent 执行（LangGraph Send 扇出）    │
│  ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ ┌──────┐ │
│  │Sales │ │ CRM  │ │Finance│ │ Inv  │ │ SC   │ │
│  │Agent │ │Agent │ │Agent  │ │Agent │ │Agent │ │
│  └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ └──┬───┘ │
│     │  run_sql / get_table_schema (最多3次重试) │
└─────┼────────┼────────┼────────┼────────┼─────┘
      │        │        │        │        │
      ▼        ▼        ▼        ▼        ▼
┌─────────────────┐
│   Aggregator    │  确定性聚合（纯 Python）
└────────┬────────┘
         │ aggregator_summary
         ▼
┌─────────────────┐
│ Chart Advisor   │  图表类型推荐 (LLM)
└────────┬────────┘
         │ chart_suggestions
         ▼
┌─────────────────┐
│  Report Agent   │  报告生成 (LLM + StreamWriter 流式输出)
└────────┬────────┘
         │ report (Markdown + 图表标记 + 追问)
         ▼
┌─────────────────┐
│Reflection Agent │  4 维质检 (LLM + tool_choice)
└────────┬────────┘
         ├─ 通过 → Memory Node (BGE-M3 → pgvector)
         └─ 不通过 → Report Agent 重试（最多 1 次）
                      │
                      ▼
              ┌─────────────┐
              │ Memory Node │  向量嵌入存储
              └─────────────┘
                      │
                      ▼
              返回报告给用户
```

### 3.2 功能点清单

| 编号 | 功能点 | 优先级 | 说明 |
|-----|--------|-------|------|
| FR-001 | 自然语言分析问题输入 | P0 | Web UI + REST API，支持最长 2000 字 |
| FR-002 | 多 Agent 智能路由 | P0 | Supervisor 根据语义自动激活 1-5 个领域 Agent |
| FR-003 | SQL 自动生成与执行 | P0 | 5 个 Agent 各自生成 SQL，经安全检查后执行 |
| FR-004 | 报告综合生成 | P0 | Markdown + ECharts 5 类图表自动推荐 + 追问建议 |
| FR-005 | 报告质量审核 | P0 | Reflection Agent 4 维质检，不通过自动重试 |
| FR-006 | SSE 流式推送 | P0 | Token 级别实时推送，前端进度条展示 |
| FR-007 | 多轮对话 | P1 | 会话管理 + 上下文注入 + 指代消解 |
| FR-008 | 数据来源追溯 | P1 | 每结论可展开原始 SQL 和执行结果 |
| FR-009 | 用户反馈闭环 | P1 | 👍/👎 + 原因填写 + 按 Agent 聚合分析 |
| FR-010 | RBAC 权限管理 | P0 | 5 级角色 + 权限码 + 门店行级安全 |
| FR-011 | 多租户数据隔离 | P0 | tenant_id 注入 + 3 种隔离模式 |
| FR-012 | API 操作审计 | P0 | 全量审计日志（用户/操作/IP/耗时），180 天保留 |
| FR-013 | PDF 报告导出 | P1 | Markdown → A4 PDF（WeasyPrint） |
| FR-014 | 客户 Schema 适配 | P0 | 3 层适配（自动发现 → YAML 映射 → Prompt 动态生成） |
| FR-015 | Docker 一键部署 | P0 | 含预打包 BGE-M3 模型 + 自动迁移 + 种子数据 |
| FR-016 | 周报自动生成 | P1 | n8n 定时触发 + 报告存储 |
| FR-017 | 异常检测与预警 | P1 | 可配置规则 + 阈值监控 |
| FR-018 | AI 质量仪表板 | P2 | 通过率/延迟/成本/错误率实时监控 |

### 3.3 边界情况处理

| 场景 | 处理方式 |
|-----|---------|
| 用户问题为空 | 返回错误提示"请输入分析问题" |
| 用户问题超长（>2000字） | Pydantic 校验拒绝，返回"问题长度不能超过2000字" |
| LLM API 超时 | 自动重试 2 次（指数退避），仍失败则降级为友好错误"AI 服务暂时不可用" |
| 所有 Agent 执行失败 | Report Agent 生成 Python 级别错误报告，列出失败原因和修复建议 |
| SQL 返回空结果 | Agent 输出"(查询结果为空)"，不崩溃 |
| SQL 安全检查不通过 | 返回 `[SQL_ERROR] Safety check failed: ...`，Agent 尝试修正 |
| Reflection 不通过 | 附带反馈重试报告生成 1 次，仍不通过则保存现有结果 |
| 客户数据库不存在某表 | 对应领域 Agent 自动禁用，Supervisor 不再路由到该 Agent |
| 多用户同时问相同问题 | 5 分钟 Redis 缓存（含 user_id + store_ids + tenant_id 维度） |
| Redis 不可用 | 降级跳过缓存，直接重新分析 |
| Ollama 不可用 | 嵌入向量降级为零向量，语义搜索功能不可用但不影响分析 |
| 非管理员访问管理功能 | RBAC 权限校验拒绝，返回 403 |

---

## 4. 非功能需求

### 4.1 性能要求

| 指标 | 目标值 | 测量方式 |
|-----|-------|---------|
| 端到端分析响应时间（P95） | ≤ 60 秒 | APM tracer 记录全链路耗时 |
| 流式首 Token 延迟（P95） | ≤ 5 秒 | SSE 首 token 到达时间 |
| 并发分析请求 | ≥ 10 | 压测 |
| API 可用性 | ≥ 99.5% | 月度 SLA |
| LLM API 调用成功率 | ≥ 99% | CostTracker 回调日志 |
| SQL 查询响应时间（P95） | ≤ 5 秒 | sql_runner 计时 |

### 4.2 效果要求（⚠️ AI产品特有）

| 指标 | 目标值 | 评估方法 | 验收标准 |
|-----|-------|---------|---------|
| **Supervisor 路由准确率** | ≥ 90% | 20 条标注测试集 | AC-001 |
| **SQL 生成准确率** | ≥ 85%（一次通过） | 离线评估脚本 `tests/run_eval.py` | AC-002 |
| **Reflection 通过率** | ≥ 85%（一次通过） | 质量仪表板统计 | AC-003 |
| **图表推荐匹配率** | ≥ 90% | 人工审查图表与数据特征匹配度 | AC-004 |
| **JSON 格式正确率** | = 100% | tool_choice 强制输出 + 解析兜底 | AC-005 |
| **用户反馈好评率** | ≥ 70% | feedback 统计 API | AC-006 |

### 4.3 安全与合规（⚠️ AI产品重点）

**数据安全**：
- [x] 支持私有化部署（数据不出企业）
- [x] JWT + bcrypt + Token 黑名单
- [x] RBAC 权限码 + 门店行级安全（SQL 注入 RLS 条件）
- [x] SQL 输入经两层安全检查（禁止模式 + 风险模式）
- [x] 前端 XSS 防御（marked HTML 转义 + jsEscape）
- [ ] 数据存储加密（AES-256）— 待实施
- [ ] PII 脱敏（手机号、身份证号）— 待实施

**内容安全**：
- [x] 输入内容长度限制（≤ 2000 字）
- [x] SQL 查询结果行数上限（max_sql_rows = 1000）
- [ ] 用户问题敏感词过滤 — 待实施

**审计要求**：
- [x] 全量 API 操作审计日志（用户/IP/操作/耗时/状态码）
- [x] 审计日志 180 天保留（audit_log 表）
- [x] 结构化日志（structlog + trace_id + session_id + user_id + tenant_id）
- [x] LLM 调用成本追踪（CostTracker 回调）

**合规**：
- [x] 多租户数据隔离（tenant_id 注入）
- [x] 管理员可模拟其他用户登录（安全审计）
- [ ] 符合《个人信息保护法》— 需客户法务评估
- [ ] GDPR 删除权 — 待实施

---

## 5. 成本模型（⚠️ AI产品特有）

### 5.1 Token成本估算

**单次调用成本（典型场景 — 3 Agent 激活，50 行 SQL 结果）**：

| 环节 | 输入 Token | 输出 Token | 总 Token | 成本 |
|------|-----------|-----------|---------|------|
| Supervisor | 600 | 150 | 750 | ¥0.0009 |
| 3 × 领域 Agent | 5,700 | 7,200 | 12,900 | ¥0.0201 |
| Chart Advisor | 1,000 | 200 | 1,200 | ¥0.0014 |
| Report Agent | 3,750 | 1,750 | 5,500 | ¥0.0073 |
| Reflection Agent | 3,500 | 250 | 3,750 | ¥0.0040 |
| **总计** | **14,550** | **9,550** | **24,100** | **¥0.0336** |

**日/月成本预估（中型连锁零售企业 — 100 家门店）**：

| 指标 | 数值 |
|-----|------|
| 日均分析次数 | 20 次（典型）+ 1 次周报（重量，5 Agent + 200 行 + 重试） |
| 日成本 | 20 × ¥0.034 + 1 × ¥0.19 ≈ **¥0.87** |
| 月成本（30 天） | ¥0.87 × 30 ≈ **¥26** |
| 年成本 | ¥26 × 12 ≈ **¥312** |

**对比：如果用 GPT-4o**：

| 指标 | DeepSeek | GPT-4o | Claude Sonnet |
|------|---------|--------|---------------|
| 单次典型成本 | ¥0.034 | ¥0.98 (29×) | ¥1.35 (40×) |
| 年成本 | ¥312 | ¥8,800 | ¥12,200 |

### 5.2 基础设施成本

| 项目 | 规格 | 月成本（自建服务器） |
|-----|------|-------------------|
| LLM API 调用（DeepSeek） | 按量计费 | ~¥26 |
| PostgreSQL 16 + pgvector | Docker 容器，2 vCPU, 1GB RAM | 共享服务器，0 |
| Redis 7 | Docker 容器，1 vCPU, 0.5GB RAM | 共享服务器，0 |
| Ollama + BGE-M3 | Docker 容器，2 vCPU, 2-4GB RAM | 共享服务器，0 |
| n8n | Docker 容器 | 共享服务器，0 |
| **月度基础设施总成本** | | **~¥26（仅 API 费用）** |

> 注：全部服务通过 Docker 容器运行在单台服务器上。最低配置 8GB RAM / 4 核 / 30GB 磁盘。

### 5.3 成本监控与告警

| 监控指标 | 阈值 | 告警方式 |
|-----|-------|---------|
| 单次调用成本 | > ¥0.50 | 日志异常标记 |
| Token 消耗异常增长 | 连续 3 天增长 > 50% | structlog 告警 |
| LLM API 调用失败率 | > 5% | Agent 错误日志 |

### 5.4 成本优化策略

| 策略 | 实现情况 | 预期效果 |
|-----|---------|---------|
| **分析结果缓存** | ✅ Redis 缓存相同问题（5 分钟 TTL，含 user/store/tenant 维度） | 减少重复分析 10-20% |
| **SQL 结果缓存** | ✅ Redis 缓存 SQL 查询结果（5 分钟 TTL） | 减少重复 SQL 执行 |
| **V4 单次图执行** | ✅ `stream_mode=["updates","custom","values"]` | LLM 调用减半（vs V3 双次执行） |
| **排名关键词注入** | ✅ 检测排名/列表类问题自动注入 LIMIT 指令 | 减少 SQL 返回行数 50-80% |
| **多模型降级** | ❌ 待实施 | 成本可再降 30%（简单查询用小模型） |
| **离线时段批量处理** | ❌ 待实施 | 减少实时调用 |

---

## 6. 效果评估方案（⚠️ AI产品特有）

### 6.1 评估数据集

**测试集构建**（`tests/eval_set.json`，102 条）：

| 类型 | 数量 | 说明 |
|-----|------|------|
| 查询型（单表/多表 JOIN） | 50 条 | 明确的数据查询问题 |
| 分析型（多 Agent 综合） | 38 条 | 需要跨领域分析的复杂问题 |
| 边界型（模糊/无匹配） | 14 条 | 异常短文本、不相关问题等 |
| **总计** | **102 条** | |

**标注方式**：
- 人工标注期望的 Agent 激活列表 + 期望的 SQL 模板类型
- 离线评估脚本 `tests/run_eval.py` 自动运行并计算指标

### 6.2 评估指标详解

**路由准确率（Routing Accuracy）**：
```
Routing Accuracy = (Supervisor 正确激活的 Agent 数) / (应激活的 Agent 数)
目标值：≥ 90%
```

**SQL 准确率（SQL Accuracy）**：
```
SQL Accuracy = (SQL 语法正确 + 语义正确的查询数) / (总查询数)
目标值：≥ 85%（一次通过，不含重试）
```

**Reflection 通过率**：
```
Pass Rate = (Reflection 判定通过的次数) / (总评审次数)
目标值：≥ 85%（一次通过），≥ 95%（含 1 次重试后）
```

**用户反馈好评率**：
```
Satisfaction = (👍 次数) / (👍 + 👎 次数)
目标值：≥ 70%
```

**幻觉率（Hallucination Rate）**：
```
幻觉率 = (报告中包含非查询结果信息的报告数) / (总报告数)
目标值：≤ 5%
```
测量方式：每周随机抽取 20 份报告，人工审查是否包含编造的数据。

### 6.3 评估频率与流程

| 阶段 | 评估频率 | 说明 |
|-----|---------|------|
| Prompt 迭代后 | 立即全量评估 | 使用 102 条测试集 |
| 每周 | 抽样评估 20 条线上数据 | 监控效果衰减 |
| 每月 | 全量回归评估 | 确保无效果回退 |
| 上线前 | 全量评估 + 边界测试 | 全部指标达标方可上线 |

### 6.4 上线标准（Go-Live Criteria）

- [x] **效果指标达标**：SQL 准确率 ≥ 85%，Reflection 一次通过率 ≥ 85%
- [x] **安全测试通过**：SQL 注入测试 100% 拦截，XSS 防御测试通过
- [ ] **性能测试通过**：P95 响应时间 ≤ 60s，10 并发通过 — 待压测
- [x] **成本在预算内**：单次典型成本 ¥0.034 ≤ ¥0.05
- [x] **多租户隔离验证通过**：跨租户数据不可访问
- [x] **审计日志完整**：所有 API 操作可追溯
- [x] **137 条测试通过**：`pytest tests/ -v` 115 passed + 22 skipped

---

## 7. 数据需求

### 7.1 数据字段定义

**系统数据库表（25 张）**：

**analysis_history 表（核心，含 pgvector 向量）**：

| 字段名 | 类型 | 说明 |
|-------|------|------|
| id | Integer | 主键，自增 |
| question | Text | 用户原始问题 |
| report | Text | 生成的完整报告 |
| sales_result | Text | 销售 Agent 中间结果 |
| crm_result | Text | CRM Agent 中间结果 |
| finance_result | Text | 财务 Agent 中间结果 |
| reflection_passed | Boolean | 是否通过质检 |
| create_time | DateTime | 创建时间 |
| user_id | Integer | 用户 FK |
| tenant_id | Integer | 🆕 租户 FK |
| embedding | Vector(1024) | BGE-M3 嵌入向量，用于语义搜索 |

**alert_rules 表（预警规则）**：

| 字段名 | 类型 | 说明 |
|-------|------|------|
| id | Integer | 主键 |
| name | String(200) | 规则名称 |
| metric | String(100) | 监控指标（refund_rate/sales_growth/member_churn） |
| threshold | Float | 阈值 |
| direction | String(10) | above 或 below |
| enabled | Boolean | 是否启用 |
| notify_channels | JSON | 通知渠道（["feishu","email"] 等） |

**audit_log 表（🆕 V4 审计日志）**：

| 字段名 | 类型 | 说明 |
|-------|------|------|
| id | Integer | 主键 |
| user_id | Integer | 操作人 FK |
| tenant_id | Integer | 租户 FK |
| action | String(10) | HTTP 方法 |
| resource | String(200) | 请求路径 |
| ip_address | String(45) | 客户端 IP |
| status_code | Integer | 响应状态码 |
| elapsed_ms | Integer | 耗时（毫秒） |
| created_at | DateTime | 操作时间（索引） |

**tenants 表（🆕 V4 多租户）**：

| 字段名 | 类型 | 说明 |
|-------|------|------|
| id | Integer | 主键 |
| name | String(200) | 租户名称 |
| slug | String(50) | 租户标识符 |
| db_schema | String(50) | Schema-per-tenant 模式 |
| db_url | String(500) | Database-per-tenant 模式 |
| is_active | Boolean | 是否启用 |
| max_users | Integer | 最大用户数 |
| plan | String(50) | 套餐（free/pro/enterprise） |

### 7.2 数据流转图

```
用户提交问题（Web UI / API）
    ↓
[输入校验] → Pydantic 长度/格式 → 不通过返回错误
    ↓ 通过
[多轮上下文注入] → Redis 读取会话历史、实体记忆
    ↓
[RAG 相似检索] → BGE-M3 embedding → pgvector 向量搜索
    ↓ 相似历史 SQL 注入 Agent Prompt
[Supervisor 路由] → LLM API → 激活 Agent 列表
    ↓
[5 Agent 并行] → 各 Agent 生成 SQL → SQL Checker → RLS 注入
    ↓
[执行 SQL] → 客户业务数据库（通过 customer_schema.yaml 配置连接）
    ↓ 返回结果
[Agent 分析] → LLM API → 业务分析结论
    ↓
[Aggregator 聚合] → 纯 Python 拼接
    ↓
[Chart Advisor] → LLM API → 图表类型推荐
    ↓
[Report Agent] → LLM API（流式）→ Markdown 报告
    ↓
[Reflection Agent] → LLM API → 4 维质检
    ↓ 通过
[Memory Node] → BGE-M3 embedding → pgvector 存储
    ↓
[存储到 analysis_history] → PostgreSQL
    ↓
[返回报告给前端] → SSE 推送 → ECharts 渲染
    ↓
[用户反馈] → 👍/👎 → user_feedback 表
    ↓
[审计记录] → audit_log 表（中间件自动捕获）
```

---

## 8. 迭代计划

| 阶段 | 目标 | 关键交付 |
|-----|------|---------|
| **V1** | MVP 验证 | 线性流水线，单轮 SQL 查询 + 一次 LLM 总结 |
| **V2** | Multi-Agent 重构 | LangGraph 编排 + RBAC + pgvector + n8n + 39 测试 |
| **V3.0** | 体验质变 | ECharts 图表 + 多轮对话 + 数据溯源 + 移动端 |
| **V3.1** | 领域扩展 | 库存/供应链 Agent + Schema 适配层 + RAG + 137 测试 |
| **V4.0** ✅ | 企业就绪 | 多租户 + 审计日志 + PDF 导出 + React 前端 + 通知服务 + 结构化日志 + 一键部署 |
| **V4.1** 🚧 | 通知集成 | 飞书/钉钉/企微 Webhook 接入（已计划，待实施） |
| **V5.0** 🔮 | 智能化升级 | LLM Provider 抽象层 + 多模型降级 + 数据脱敏 + 评测自动化 + 新手引导 |

---

## 9. 风险与应对

| 风险 | 影响 | 概率 | 应对措施 |
|-----|------|-------|---------|
| DeepSeek API 不可用 | 高：全部分析失败 | 低 | 🚧 LLM Provider 抽象层（多模型降级），V5 计划 |
| SQL 生成准确率不达预期 | 中：用户信任度下降 | 中 | ✅ 自动重试 + RAG 增强 + 错误降级报告 |
| 成本超预算（高频使用） | 中：影响 ROI | 低 | ✅ Redis 缓存 + V4 单次图执行 + 排名注入减少 SQL 行数 |
| 客户数据库 Schema 差异大 | 高：无法开箱即用 | 高 | ✅ 3 层适配（自动发现 → YAML 映射 → Prompt 动态生成） |
| 数据泄露/安全事故 | 高：法律风险 | 低 | ✅ 私有化部署 + SQL 注入防护 + XSS 防御 + 审计日志 |
| 效果随时间衰减（Prompt 漂移） | 中 | 中 | 🚧 评测自动化（V5），当前依赖人工定期检查 |
| 客户抵制 AI 分析（不信任） | 低 | 中 | ✅ 数据溯源面板（每结论可查原始 SQL）+ Reflection 质检 |
| Ollama/BGE-M3 不可用 | 低：语义搜索失效 | 低 | ✅ 降级为零向量，不影响核心分析功能 |

---

## 10. 附录

### 10.1 相关文档

| 文档 | 路径 | 说明 |
|------|------|------|
| 产品需求文档（传统PRD） | `docs/产品需求文档-PRD.md` | V4 完整功能规格 |
| CHANGELOG | `CHANGELOG.md` | V4 60 项修复记录 |
| 竞品分析 | `docs/竞品分析.md` | 竞争格局 + 壁垒分析 |
| 启动指南 | `docs/启动指南.md` | Docker/手动部署 |
| 升级指南 | `UPGRADE.md` | 版本升级与回滚 |
| 商业思考 | `docs/商业思考.md` | 定价/GTM/市场规模 |
| Prompt 迭代日志 | `docs/Prompt迭代日志.md` | 5 次 Prompt 迭代记录 |
| Bad Case 复盘 | `docs/BadCase复盘.md` | 3 个 AI 犯错复盘案例 |
| 离线评估脚本 | `tests/run_eval.py` | 102 条测试集自动评估 |

### 10.2 Prompt迭代记录表

| 版本 | 日期 | 修改内容 | 效果变化 |
|-----|------|---------|---------|
| v1.0 | V1 | 初始 Prompt，单 Agent 线性 | SQL 准确率 ~70% |
| v2.0 | V2 | 增加 Supervisor 路由 + 3 领域 Agent | 路由准确率 ~85% |
| v3.0 | V3 | 增加 Chart Advisor + 追问建议 + RAG | SQL 准确率 ~85% |
| v4.0 | V4 | YAML 外部化 + 热重载 + 排名关键词注入 + 客户 Schema 动态适配 | SQL 截断修复，适配效率提升 |

### 10.3 模型选型对比

| 模型 | 中文理解 | 成本（输入/输出 ¥/MTok）| 支持 tool_choice | 选型结论 |
|------|---------|----------------------|-----------------|---------|
| DeepSeek-Chat | ⭐⭐⭐⭐⭐ | 1/2 | ✅ | ✅ 选用 — 最佳性价比 |
| GPT-4o | ⭐⭐⭐⭐ | 18/54 | ✅ | 备选 — 成本过高 |
| Claude Sonnet | ⭐⭐⭐ | 22/79 | ✅ | 备选 — 中文弱 |
| Qwen-Max | ⭐⭐⭐⭐ | 2.5/6 | ❌ | 备选 — 缺 tool_choice |
| DeepSeek-R1 | ⭐⭐⭐⭐⭐ | 4/16 | ❌ | 不适合 — 思考模式不支持 tool_choice |

---

> **使用说明**：本 AI-PRD 基于 V4.0.0 代码基线编写。标注 ✅ 的功能已实现，标注 🚧 的功能已在计划中。实际投产后应根据用户反馈和评测结果持续迭代 Prompt 和效果指标。

*文档版本：v1.0 | 创建日期：2026-06-11 | 作者：高志远*
