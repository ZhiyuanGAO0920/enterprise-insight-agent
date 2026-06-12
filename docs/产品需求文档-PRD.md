# 产品需求文档（PRD）

## Enterprise Insight Agent V4 — 自然语言驱动的企业 Multi-Agent 经营分析平台

---

| 字段 | 内容 |
|------|------|
| **文档版本** | v4.0.0 |
| **文档状态** | ✅ 已定版（基于 v4.0.0 代码基线） |
| **产品版本** | Enterprise Insight Agent V4（4.0.0） |
| **产品负责人** | 高志远 |
| **技术栈** | Python 3.12 / LangGraph / DeepSeek / FastAPI / PostgreSQL 16+pgvector / Redis / n8n / React 18 + TypeScript + Ant Design 5 |
| **创建日期** | 2026-06-08 |
| **最后更新** | 2026-06-11 |

### 修订记录

| 版本 | 日期 | 作者 | 变更说明 |
|------|------|------|----------|
| v1.0.0 | 2025-01 | 高志远 | MVP 验证，线性流水线 |
| v2.0.0 | 2026-06 | 高志远 | Multi-Agent 重构：LangGraph 编排、RBAC、pgvector、n8n |
| v3.0.0 | 2026-06 | 高志远 | 体验质变：ECharts 可视化、多轮对话、数据溯源、移动端适配、用户反馈闭环、库存/供应链 Agent、客户 Schema 适配层、离线评估体系、AI 质量仪表板 |
| v4.0.0 | 2026-06 | 高志远 | 企业就绪：多租户、审计日志、PDF 导出、React 前端、结构化日志、通知服务、安全加固、图执行优化、60 项质量修复 |

---

## 目录

1. [产品概述](#1-产品概述)
2. [功能全景](#2-功能全景)
3. [Agent 体系](#3-agent-体系)
4. [权限与安全](#4-权限与安全)
5. [数据模型](#5-数据模型)
6. [API 设计](#6-api-设计)
7. [前端能力](#7-前端能力)
8. [AI 质量体系](#8-ai-质量体系)
9. [适配与扩展](#9-适配与扩展)
10. [产品路线图](#10-产品路线图)

---

## 1. 产品概述

### 1.1 产品定位

面向连锁零售企业的 AI 经营决策平台。**5 个领域 Agent 覆盖销售、会员、财务、库存、供应链五大业务域**，通过 10 节点 LangGraph 编排实现全链路自动化分析。**V4 已具备多租户、审计日志、PDF 导出、React 前端等企业级能力**，可直接交付生产环境使用。

版本演进：V1 线性流水线 → V2 Multi-Agent 并行 → V3 体验质变 → **V4 企业就绪**。

### 1.2 V3 → V4 核心升级

| 升级项 | V3 | V4 |
|--------|-----|-----|
| 多租户 | 无 | **租户表 + tenant_id 数据隔离 + JWT 注入** |
| 审计日志 | 无 | **全量 API 操作审计（用户/操作/IP/耗时）** |
| 前端 | 静态 HTML/JS | **React 18 + TypeScript + Ant Design 5** |
| PDF 导出 | 无 | **Markdown → A4 PDF（WeasyPrint）** |
| 通知服务 | 无 | **邮件 + 企微/钉钉/飞书 Webhook** |
| 日志系统 | 标准 logging | **structlog + trace_id + JSON 格式** |
| 安全防护 | 基础 JWT + RLS | **SQL 注入防护 + XSS 防御 + 会话鉴权** |
| 图执行 | 流式 2 次图执行 | **单次执行（LLM 成本减半）** |
| 部署方案 | 手动启动 | **Docker 一键部署 + 预打包模型 + 种子数据** |
| 代码质量 | — | **60 项修复（见 CHANGELOG）** |
| 测试 | 137 条 | **137 条（115 passed + 22 DB/API 跳过）** |
| 数据库表 | 23 | **25（+ tenants, + audit_log）** |
| API | 26 | **31（+ 模拟登录 / 审计查询 / Schema 管理）** |

### 1.3 关键指标

| 指标 | 数值 |
|------|:--:|
| 领域 Agent | 5（Sales / CRM / Finance / Inventory / Supply Chain） |
| Agent 节点总数 | 10 |
| 测试条数 | 137（115 passed + 22 skipped） |
| 数据库表 | 25 |
| API 端点 | 31 |
| 中间件 | 4（CORS → 审计 → 多租户 → API 版本头） |
| 部署容器 | 5（App + PostgreSQL + Redis + Ollama + n8n） |
| 默认角色 | 3（admin / analyst / viewer） |
| 演示门店 | 5（华东/华北/华南/华中/西南各 1） |

---

## 2. 功能全景

### V4 功能矩阵

```
┌──────────────────────────────────────────────────────────────────────────┐
│                    Enterprise Insight Agent V4                             │
├──────────────┬──────────────┬──────────────┬──────────────────────────────┤
│   分析引擎    │   交互体验    │   安全底座    │      AI 质量体系              │
├──────────────┼──────────────┼──────────────┼──────────────────────────────┤
│ 10 Agent 节点 │ React 前端    │ RBAC 5 级角色 │ 离线评估集（102 条）          │
│ 5 领域并行    │ ECharts 图表  │ scope_type 权限│ AI 质量仪表板                │
│ Supervisor 路由│ 多轮对话      │ 行级 SQL 注入  │ Prompt 迭代日志              │
│ Reflection 质检│ 数据溯源面板  │ SQL 白名单     │ Bad Case 复盘                │
│ RAG SQL 增强  │ 追问建议按钮  │ JWT + 黑名单   │ 成本追踪                     │
│ Chart Advisor │ 移动端适配    │ 会话所有权鉴权  │ 反馈闭环                     │
│ 客户 Schema 适配│ Dashboard 快报│ 🆕 审计日志    │ APM 性能追踪                │
│ 🆕 PDF 导出   │ 🆕 企微/钉钉通知│ 🆕 多租户隔离  │ 🆕 structlog 结构化日志     │
├──────────────┼──────────────┼──────────────┼──────────────────────────────┤
│   自动化       │   前端管理     │   工程基础     │      部署运维                │
├──────────────┼──────────────┼──────────────┼──────────────────────────────┤
│ n8n 定时周报   │ 用户管理面板   │ CI/CD 流水线   │ 🆕 Docker 一键部署            │
│ 异常实时预警   │ 门店分配       │ Feature Flag   │ 🆕 预打包 BGE-M3 模型         │
│ 🆕 邮件/飞书推送│ 批量导入       │ 14 类友好错误   │ 🆕 自动迁移 + 种子数据        │
│              │              │                │ 🆕 数据库备份 + 离线镜像       │
└──────────────┴──────────────┴──────────────┴──────────────────────────────┘
```

---

## 3. Agent 体系

### 3.1 10 节点 LangGraph 拓扑

```
Supervisor（智能路由 5 领域）
  ├── Sales Agent          → sales_result
  ├── CRM Agent            → crm_result
  ├── Finance Agent        → finance_result
  ├── Inventory Agent 🆕   → inventory_result
  └── Supply Chain Agent 🆕 → supply_chain_result
       ↓
  Aggregator（确定性聚合）
       ↓
  Chart Advisor 🆕（图表类型推荐）
       ↓
  Report Agent（含图表标记 + 追问生成）
       ↓
  Reflection Agent（4 维质检 / 最多 1 次重试）
       ↓
  Memory Node（BGE-M3 → pgvector）
```

### 3.2 5 个领域 Agent 能力矩阵

| Agent | 核心能力 | 关键词触发 |
|-------|---------|-----------|
| **Sales** | 销售趋势、区域分布、门店排名、品类分析、退款率 | 销售、门店、区域、品类、排名 |
| **CRM** | 会员增长、流失、复购率、RFM 分层、活跃度 | 会员、复购、流失、活跃、等级 |
| **Finance** | 客单价、退款率、利润率、成本分析 | 财务、利润、成本、退款、客单价 |
| **Inventory** 🆕 | 缺货预警、滞销识别、补货建议、品类健康度 | 库存、缺货、滞销、补货、安全库存 |
| **Supply Chain** 🆕 | 供应商绩效排名、采购成本趋势、物流时效、依赖度 | 供应商、采购、供应链、交货、准时率 |

### 3.3 Supervisor 路由规则

| 问题类型 | 激活策略 | 示例 |
|---------|---------|------|
| 单一领域 | 仅激活对应 Agent | "退款率最高的门店" → Finance |
| 多领域 | 激活多个 Agent 并行 | "华东区销售和会员分析" → Sales + CRM |
| 综合分析 | 全部 5 Agent 并行 | "整体经营分析" → 全部 |
| 模糊问题 | 全部并行（保守兜底） | "最近怎么样" → 全部 |

### 3.4 Reflection 质检维度

| 维度 | 检查内容 |
|------|---------|
| 一致性 | 跨 Agent 数据是否矛盾 |
| 逻辑性 | 因果推断是否合理 |
| 可执行性 | 建议是否具体可落地 |
| 完整性 | 是否覆盖问题所有方面 |

通过率约 85%，1 次重试后提升至 95%。

---

## 4. 权限与安全

### 4.1 五级角色体系

| 角色 | 数据范围 | scope_type | 管理面板 |
|------|---------|:--:|:--:|
| 总部管理员 (admin) | 全部门店 | `all` | ✅ |
| 大区总监 (regional_director) 🆕 | 所辖大区自动继承 | `region` | ❌ |
| 区域经理 (regional_manager) | 所辖区域 | `region` | ❌ |
| 店长 (store_manager) | 指定门店 | `store` | ❌ |
| 店员 (store_operator) 🆕 | 所属门店 | `store` | ❌ |

### 4.2 门店访问范围（scope_type）

| scope_type | 机制 | 示例 |
|:--:|------|------|
| `all` | 无限制 | admin → 全部门店 |
| `region` | 按区域动态查询门店列表 | director_huadong → 华东区全部 25 家 |
| `store` | 指定门店 ID 列表 | store_042 → 仅 42 号门店 |

### 4.3 安全层次

```
Layer 6: 🆕 审计追踪（全量 API 操作记录：用户/操作/IP/耗时/状态码）
Layer 5: 输入验证（Pydantic 长度/格式校验 + 🆕 XSS 防御）
Layer 4: 认证（JWT + bcrypt + Token 黑名单 + 🆕 会话所有权验证）
Layer 3: 授权（RBAC 权限码 + 声明式 Depends + 🆕 模拟登录）
Layer 2: 行级安全（SQL 注入 store_id IN (...) 双保险 + 🆕 单引号转义）
Layer 1: SQL 安全（白名单审查 + 字符串剥离反绕过 + 行数上限）
```

### 4.4 行级安全自动适配

`inject_store_filter` 自动检测 SQL 中的表名选择正确过滤列：
- `FROM store` → 用 `id`
- `FROM orders/inventory` → 用 `store_id`
- `FROM member/supplier` → 不注入（无门店列）

---

## 5. 数据模型

### 5.1 数据库规模

| 类别 | 表名 | 说明 | V4 变更 |
|------|------|------|:--:|
| **业务** | store | 门店 | — |
| | orders | 订单 | — |
| | member | 会员 | — |
| | employee_performance | 员工绩效 | + UniqueConstraint |
| **库存/供应链** | product / supplier / inventory / purchase_order | 库存供应链 | — |
| **权限** | users / roles / permissions | RBAC 基础 | — |
| | user_roles / role_permissions | 多对多关联 | — |
| | user_store_access | 行级安全（含 scope_type） | — |
| **多租户** 🆕 | tenants | 租户信息 + 套餐/容量限制 | V4 新增 |
| **审计** 🆕 | audit_log | 操作审计日志（180 天保留） | V4 新增 |
| **分析** | analysis_history | 分析历史（pgvector 向量） | + tenant_id |
| | agent_trace_events | APM 追踪 | — |
| | conversation_sessions | 多轮对话会话 | — |
| **运营** | user_feedback | 用户反馈 | — |
| | alert_rules / alerts | 预警 | — |
| | weekly_reports | 周报 | — |
| | prompt_versions | Prompt 版本 | — |

**总计：25 张表**（V3: 23 → V4: +2）

---

## 6. API 设计

### 6.1 端点清单（31 个）

| 分组 | 端点 | 说明 | V4 |
|------|------|------|:--:|
| **认证** | `POST /api/v1/auth/login` | 登录 | — |
| | `POST /api/v1/auth/logout` | 登出 | — |
| **分析** | `POST /api/v1/analysis/analyze` | 提交分析（同步） | — |
| | `POST /api/v1/analysis/analyze-stream` | 提交分析（SSE 流式） | 🆕 单次图执行 |
| | `GET /api/v1/analysis/history` | 历史记录 | — |
| | `GET /api/v1/analysis/history/{id}` | 历史详情 | — |
| | `GET /api/v1/analysis/similar` | 向量相似搜索 | — |
| **Dashboard** | `GET /api/v1/dashboard/today-summary` | 今日经营快报 | — |
| **会话** | `POST /api/v1/session/create` | 创建会话 | — |
| | `GET /api/v1/session/{id}` | 获取会话 | + 所有权验证 |
| **反馈** | `POST /api/v1/feedback/submit` | 提交反馈 | — |
| | `GET /api/v1/feedback/stats` | 反馈统计 | — |
| | `GET /api/v1/feedback/analyze` | 按 Agent 聚合分析 | — |
| **Prompt** | `GET /api/v1/prompts` | Agent 列表 | — |
| | `GET /api/v1/prompts/{agent}` | 查看 Prompt | — |
| | `POST /api/v1/prompts/reload` | 热重载 | — |
| **管理** | `GET /api/v1/admin/users` | 用户列表 | — |
| | `POST /api/v1/admin/users` | 创建用户 | — |
| | `PUT /api/v1/admin/users/{id}` | 编辑用户 | — |
| | `DELETE /api/v1/admin/users/{id}` | 删除用户 | — |
| | `POST /api/v1/admin/users/{id}/reset-password` | 重置密码 | — |
| | `POST /api/v1/admin/users/batch-import` | 批量导入 | — |
| | `GET /api/v1/admin/stores` | 门店列表 | — |
| | `POST /api/v1/admin/impersonate/{id}` 🆕 | 模拟其他用户登录 | V4 新增 |
| | `GET /api/v1/admin/audit-logs` 🆕 | 审计日志查询 | V4 新增 |
| | `GET /api/v1/admin/schema/discover` | Schema 自动发现 | — |
| | `POST /api/v1/admin/schema/preview-yaml` | 预览 YAML 映射 | — |
| | `GET /api/v1/admin/schema/test-connection` | 测试 DB 连接 | — |
| **监控** | `GET /api/v1/monitor/overview` | AI 质量仪表板 | — |
| **周报** | `POST /api/v1/weekly/generate` | 生成周报 | — |
| | `GET /api/v1/weekly/reports` | 周报列表 | — |
| **预警** | `POST /api/v1/alerts/check` | 触发预警 | — |
| | `GET /api/v1/alerts/rules` | 预警规则 | — |
| **系统** | `GET /health` | 存活检查 | — |
| | `GET /health/ready` | 就绪检查（DB + Redis） | — |

> V4 统一路由前缀为 `/api/v1/`，旧版 `/api/` 返回 308 重定向。

---

## 7. 前端能力

| 能力 | V3 | V4 |
|------|:--:|:--:|
| 技术栈 | 静态 HTML/JS | **React 18 + TypeScript + Ant Design 5 + Vite** |
| 聊天界面 | ✅ | ✅（组件化重构） |
| Markdown 渲染 | ✅ | ✅ |
| ECharts 图表 | ✅ 5 类 | ✅ 5 类 |
| SSE 流式进度 | ✅ 10 步 | ✅ 单次图执行 Token 流式 |
| 数据溯源面板 | ✅ | ✅ |
| 追问建议按钮 | ✅ | ✅ |
| 反馈 👍/👎 | ✅ | ✅ |
| 移动端响应式 | ✅ | ✅ |
| 语音输入 | ✅ | ✅ |
| Dashboard 快报 | ✅ | ✅ |
| 会话管理 | ✅ | ✅ |
| 系统管理面板 | ✅ 用户 CRUD | ✅ 用户 CRUD + 🆕 模拟登录 + 🆕 Schema 配置 |
| 管理员按钮权限控制 | ❌ | ✅ 仅 admin 可见 |
| XSS 防御 | ❌ | ✅ HTML 转义 + jsEscape |
| 重入保护 | ❌ | ✅ _isAnalyzing 互斥锁 |

---

## 8. AI 质量体系

### 8.1 离线评估

- 20 条评估问题（10 查询型 + 8 分析型 + 2 边界型）
- 自动化评估脚本 `tests/run_eval.py`
- 每次 Prompt 修改后跑一轮，量化准确率变化

### 8.2 AI 质量仪表板（`GET /api/monitor/overview`）

| 指标 | 说明 |
|------|------|
| SQL 准确率 | Reflection 通过率近似衡量 |
| Reflection 通过率 | 质检通过比例 |
| 各 Agent 错误率排行 | 按节点聚合 |
| P50/P95 延迟 | 从 agent_trace_events 计算 |
| 日均/月均成本 | LLM Token 消耗估算 |

### 8.3 Prompt 迭代管理

- 9 组 Prompt（Python + YAML 双格式）
- `resolve_agent_prompt()` 三级解析：客户适配 → YAML → Python fallback
- 5 次迭代日志（`docs/Prompt迭代日志.md`），每次记录改动→原因→验证→教训

### 8.4 Bad Case 复盘

3 个完整闭环案例（`docs/BadCase复盘.md`）：LLM 截断问题、RLS 注入错列、追问不相关——每个涵盖现象→诊断→修复→验证→教训。

---

## 9. 适配与扩展

### 9.1 客户 Schema 适配层

```
第一层：Schema 自动发现 → 读取客户数据库所有表和列
第二层：语义映射配置 → customer_schema.yaml 建立逻辑概念→物理表/列映射
第三层：Prompt 动态生成 → 根据映射自动替换 Agent Prompt 中的表名/列名/SQL 模板
```

效果：客户表名不同（如 `t_sales_records` 替代 `orders`）→ 30 分钟填一份 YAML → 零代码适配。

### 9.2 RAG 增强

在 3 个领域 Agent 的工具调用循环前，用 BGE-M3 + pgvector 检索历史相似 SQL 作为 Few-shot 示例注入 Prompt。

### 9.3 扩展点

- 新增 Agent：注册节点 + 添加字段 + Supervisor Prompt 增加路由规则
- 多数据源：DataSource 抽象基类（PostgreSQL/MySQL/MongoDB/CSV）
- 模型替换：LLM 工厂模式，改 `.env` 即可

---

## 10. 产品路线图

### 已完成

| 版本 | 里程碑 |
|:--:|------|
| V1 | 线性流水线验证（Planner → SQL Generator → Analyzer → Reflection） |
| V2 | Multi-Agent + LangGraph + RBAC + pgvector + n8n + 39 测试 |
| V3.0 | ECharts + 多轮对话 + 数据溯源 + 移动端 + 反馈 + Feature Flag + 137 测试 |
| V3.1 | 库存/供应链 Agent + 客户 Schema 适配层 + RAG 增强 + 离线评估 + AI 仪表板 + RBAC 五级 + 管理面板 |
| V4.0 | 多租户 + 审计日志 + PDF 导出 + React 前端 + 通知服务 + 结构化日志 + 安全加固 + 一键部署 + 60 项质量修复 |

### 后续规划

| 优先级 | 内容 |
|:--:|------|
| P0 | LLM Provider 抽象层（多模型降级） + 数据脱敏/PII 遮蔽 |
| P1 | 企业微信/钉钉集成、HTTPS/nginx 生产部署模板 |
| P2 | 智能预警规则引擎升级（LLM 动态阈值）、评测体系自动化 |
| P3 | PWA 离线模式、前端 onboarding 新手引导 |

---

## 附录：文档索引

| 文档 | 说明 |
|------|------|
| `README.md` | 项目总览 |
| `CHANGELOG.md` | V4 完整修复记录（60 项） |
| `UPGRADE.md` | 版本升级指南 |
| `启动指南.md` | Docker/手动部署 + 首次引导 |
| `docs/V1-V2-V3-V4-四版对比.md` | 四版本完整演化对比 |
| `docs/V1-V2-V3-三版对比.md` | V1→V3 演化 |
| `docs/产品需求文档-PRD.md` | 本文档 |
| `docs/AI产品设计原则.md` | 7 条方法论 + AI 产品指标体系 |
| `docs/竞品分析.md` | 竞品对比 + 30 秒电梯演讲 |
| `docs/A-B测试记录.md` | 4 组对比实验 |
| `docs/商业思考.md` | 定价/GTM/市场规模/单位经济 |
| `docs/关键产品决策记录.md` | 10 条关键决策（含模型选型对比） |
| `docs/Prompt迭代日志.md` | 5 次 Prompt 迭代全记录 |
| `docs/BadCase复盘.md` | 3 个 AI 犯错复盘案例 |

---

*文档版本：v4.0.0 | 创建日期：2026-06-08 | 最后更新：2026-06-11 | 作者：高志远*
