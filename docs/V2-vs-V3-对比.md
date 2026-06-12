# Enterprise Insight Agent — V2 vs V3 全面对比

---

| 字段 | 内容 |
|------|------|
| **文档版本** | v1.2 |
| **创建日期** | 2026-06-09 |
| **最后更新** | 2026-06-10 |
| **V2 基线** | v2.0.0 (commit `e861405`) |
| **V3 版本** | v3.0.0 |
| **V3 代码完成度** | P0+P1+P2：**10/10** ✅ + P3 部分完成（库存/供应链 Agent） |
| **测试状态** | V2: 39 → **V3: 137**（新增 98 条，含 7 个 Phase E2E + Prompt Loader） |

---

## 目录

1. [一句话总结](#一句话总结)
2. [产品体验对比](#产品体验对比)
3. [功能矩阵对比](#功能矩阵对比)
4. [架构变更对比](#架构变更对比)
5. [Agent 体系对比](#agent-体系对比)
6. [数据模型对比](#数据模型对比)
7. [API 端点对比](#api-端点对比)
8. [前端能力对比](#前端能力对比)
9. [工程质量对比](#工程质量对比)
10. [性能与监控对比](#性能与监控对比)
11. [迁移路径](#迁移路径)

---

## 一句话总结

| | V2 | V3 |
|------|-----|-----|
| **定位** | "能用"——AI 能分析经营数据 | "好用 + 让人信任"——AI 能说服用户 |
| **体验关键词** | 单次问答、纯文本、黑盒 | 持续对话、图文并茂、透明可追溯 |

---

## 产品体验对比

### 典型场景：用户问"华东区销售为什么下降"

| 维度 | V2 体验 | V3 体验 |
|------|---------|---------|
| **输出** | 纯 Markdown 文本报告 | 报告 + 趋势折线图 + 门店排名柱状图 |
| **信任** | 用户无法验证数据来源 | 每条数据主张可点击查看 SQL 和执行时间 |
| **追问** | 丢失上下文，无法追问 | 自动建议 3 个追问，支持指代消解 |
| **移动** | 桌面端专用，手机布局错乱 | 响应式布局，手机端完整可用 |
| **反馈** | 无反馈渠道 | 👍/👎 一键反馈，数据驱动优化 |
| **出错** | 显示 `column 'status' does not exist` | 显示 "已自动调整查询方式并重试 🔄" |

---

## 功能矩阵对比

| # | 功能 | V2 | V3 | 优先级 |
|---|------|:--:|:--:|:--:|
| 1 | 自然语言查询分析 | ✅ | ✅ | — |
| 2 | 双模式输出（查询型/分析型） | ✅ | ✅ | — |
| 3 | Supervisor 智能路由 | ✅ | ✅ | — |
| 4 | Reflection 质检 + 重试 | ✅ | ✅ | — |
| 5 | 向量记忆（pgvector） | ✅ | ✅ | — |
| 6 | RBAC 四级权限 | ✅ | ✅ | — |
| 7 | SQL 安全白名单 | ✅ | ✅ | — |
| 8 | n8n 定时周报 + 预警 | ✅ | ✅ | — |
| 9 | SSE 流式推送 | ✅ | ✅ | — |
| **10** | **ECharts 图表可视化** | ❌ | ✅ | P0 |
| **11** | **多轮对话上下文** | ❌ | ✅ | P0 |
| **12** | **数据来源可追溯** | ❌ | ✅ | P0 |
| **13** | **移动端响应式适配** | ❌ | ✅ | P1 |
| **14** | **用户反馈闭环** | ❌ | ✅ | P1 |
| **15** | **Agent 性能追踪 (APM)** | ❌ | ✅ | P2 |
| **16** | **用户友好错误消息** | ❌ | ✅ | P2 |
| **17** | **CI/CD 自动流水线** | ❌ | ✅ | P2 |
| 18 | Prompt 外部化管理 | ❌ | ✅ | P1-3 |
| 19 | 库存/供应链 Agent | ❌ | ⬜ | P3 |
| 20 | 多数据源支持 | ❌ | ⬜ | P3 |

> V2: 9 项 ✅ | V3: 18 项 ✅ + 2 项 ⬜ 待实施（P3 库存/供应链 Agent + 多数据源）

---

## 架构变更对比

### Agent 拓扑

```
V2:  supervisor → [sales ‖ crm ‖ finance] → aggregator → report → reflection ⇄ report → memory → END
      7 个节点

V3:  supervisor → [sales ‖ crm ‖ finance] → aggregator → chart_advisor 🆕 → report → reflection ⇄ report → memory → END
      8 个节点（新增 Chart Advisor）
```

### 数据流变更

```
V2:
  用户提问 → 分析 → Markdown 报告 → 前端纯文本渲染

V3:
  用户提问 → 多轮上下文注入 → 分析 + 数据溯源收集 → 图表推荐 → Markdown 报告(含[CHART:][FOLLOWUP:]标记)
    → 前端渲染(ECharts图表 + 溯源面板 + 追问按钮 + 反馈按钮)
```

### AnalysisState 字段

| 类别 | V2 字段 (12个) | V3 新增 (7个) |
|------|----------------|---------------|
| 输入 | question, user_id, store_ids | session_id, conversation_context, is_followup, resolved_question |
| 输出 | report, final_report | chart_suggestions, followup_questions |
| 溯源 | — | data_sources (Annotated[list, add]) |

---

## Agent 体系对比

| Agent | V2 | V3 | V3 变更 |
|-------|:--:|:--:|------|
| **Supervisor Agent** | ✅ | ✅ | 支持注入对话上下文 |
| **Sales Agent** | ✅ | ✅ | 支持 data_sources 收集（SQL/耗时/行数） |
| **CRM Agent** | ✅ | ✅ | 支持 data_sources 收集 |
| **Finance Agent** | ✅ | ✅ | 支持 data_sources 收集 |
| **Aggregator** | ✅ | ✅ | 无变化 |
| **Chart Advisor Agent** | — | 🆕 | 数据特征 → 图表类型推荐 → [CHART:...] 标记 |
| **Report Agent** | ✅ | ✅ | 嵌入图表标记 + 生成追问建议 |
| **Reflection Agent** | ✅ | ✅ | 无变化 |
| **Memory Node** | ✅ | ✅ | 无变化 |

---

## 数据模型对比

### 新增表 (V3)

| 表名 | 用途 | 对应功能 |
|------|------|----------|
| `user_feedback` | 用户反馈记录 | P1-2 反馈闭环 |
| `agent_trace_events` | Agent 执行性能追踪 | P2-1 APM 监控 |
| `conversation_sessions` | 对话会话备份 | P0-2 多轮对话 |
| `prompt_versions` | Prompt 版本管理 | P1-3 Prompt 外部化 |

> V2: 10 张表 → **V3: 14 张表**（含 4 张新增，0 张修改，0 风险迁移）

---

## API 端点对比

| 端点 | V2 | V3 | V3 变更 |
|------|:--:|:--:|------|
| `POST /api/analysis/analyze` | ✅ | ✅ | 支持 session_id；返回 data_sources + followup_questions |
| `POST /api/analysis/analyze-stream` | ✅ | ✅ | 支持多轮上下文注入 + 流式返回 V3 字段 |
| `GET /api/analysis/history` | ✅ | ✅ | 无变化 |
| `GET /api/analysis/similar` | ✅ | ✅ | 无变化 |
| `POST /api/auth/login` | ✅ | ✅ | 无变化 |
| `GET /api/weekly/*` | ✅ | ✅ | 无变化 |
| `GET /api/alerts/*` | ✅ | ✅ | 无变化 |
| `POST /api/session/create` | — | 🆕 | 创建对话会话 |
| `GET /api/session/{id}` | — | 🆕 | 获取会话状态+实体记忆 |
| `POST /api/feedback/submit` | — | 🆕 | 提交用户反馈 |
| `GET /api/feedback/stats` | — | 🆕 | 反馈统计（管理员） |
| `GET /api/prompts` | — | 🆕 | Prompt 列表（所有 Agent 版本） |
| `GET /api/prompts/{agent}` | — | 🆕 | 查看单个 Agent Prompt |
| `POST /api/prompts/reload` | — | 🆕 | 热重载 YAML（管理员） |

> V2: 7 个端点 → **V3: 14 个端点**（新增 7 个）

---

## 前端能力对比

| 能力 | V2 | V3 |
|------|:--:|:--:|
| Markdown 渲染 | ✅ 基础解析 | ✅ 增强解析 |
| 表格展示 | ✅ | ✅ |
| 流式进度 (8步) | ✅ | ✅（含图表推荐步骤） |
| 登录/角色切换 | ✅ | ✅ |
| ECharts 图表 (柱状/折线/饼图/散点/雷达) | ❌ | 🆕 |
| 数据溯源面板 (SQL/耗时/行数) | ❌ | 🆕 |
| 追问建议按钮 | ❌ | 🆕 |
| 👍/👎 反馈按钮 | ❌ | 🆕 |
| 会话管理 (新建/切换) | ❌ | 🆕 |
| 实体记忆显示 | ❌ | 🆕 |
| 响应式移动端布局 | ❌ | 🆕 |

> V2: 4 项 → **V3: 11 项**

---

## 工程质量对比

| 维度 | V2 | V3 |
|------|-----|-----|
| **测试数量** | 39 条 | **137 条** (+251%) |
| **测试分类** | 配置/导入/LLM/认证/SQL/E2E | V2 全部 + **V3 专项 98 条**（7 个 Phase + Prompt Loader） |
| **V3 测试覆盖** | — | Chart Advisor / ContextManager / 错误映射 / APM / API / State / Prompt YAML |
| **CI/CD** | ❌ 无 | ✅ GitHub Actions (Lint→Test→Build) |
| **Feature Flag** | ❌ 无 | ✅ 8 个灰度开关，默认关闭 |
| **错误处理** | 原始异常信息 | 14 类中文友好消息 + 图标 + 建议操作 |
| **性能可观测** | ❌ 无 | ✅ Agent 节点级耗时追踪 |
| **Prompt 管理** | 硬编码 Python 常量 | ✅ YAML 外部化 + 热重载 + 管理 API |

---

## 性能与监控对比

| 指标 | V2 | V3 |
|------|-----|-----|
| **Agent 节点耗时** | 不可知 | `agent_trace_events` 表记录 |
| **瓶颈定位** | 手动排查 | 按节点聚合 `avg_ms` / `p95_ms` |
| **用户反馈** | 不可知 | `user_feedback` 表 + 统计 API |
| **错误分类** | 原始错误字符串 | 14 类模式匹配 + 自动重试标记 |

---

## 迁移路径

### 从 V2 到 V3 — 零风险升级

```
V2 运行中
    │
    ├── 1. git pull V3 代码              ← 不影响 V2 运行
    ├── 2. alembic upgrade head           ← 仅 CREATE TABLE IF NOT EXISTS
    ├── 3. 所有 V3 Feature Flag 默认 OFF  ← V2 行为完全不变
    ├── 4. 逐个开启 Feature Flag 灰度     ← 按需启用
    │      FEATURE_FRIENDLY_ERRORS=true   → 错误消息改善
    │      FEATURE_DATA_TRACE=true        → 数据可追溯
    │      FEATURE_CHART=true             → 图表可视化
    │      FEATURE_MULTI_TURN=true        → 多轮对话
    │      ...
    └── 5. 全量开启 → V3 完整体验
```

### 回滚方案

- 所有 Feature Flag 设回 `false` → 立即回退到 V2 行为
- 不需要数据库降级（新增表仅追加，不影响现有表）

---

## 总结

| 维度 | V2 基线 | V3 目标 | 当前状态 |
|------|---------|---------|:--:|
| Agent 数量 | 7 | 10 | ✅ |
| 领域 Agent | 3 | 5 (销售/CRM/财务/库存/供应链) | ✅ |
| 测试数量 | 39 | 137 | ✅ |
| API 端点 | 7 | 14 | ✅ |
| 数据库表 | 10 | 18 | ✅ |
| 前端能力 | 4 项 | 11 项 | ✅ |
| P0 体验升级 | — | 3/3 | ✅ |
| P1 质量升级 | — | 3/3 | ✅ |
| P2 工程升级 | — | 3/3 | ✅ |
| P3 Agent 扩展 | — | 2 个新 Agent | ✅ |

> **V3 完成度：P0+P1+P2 全部 10/10 | P3 2/3（库存 Agent ✅ + 供应链 Agent ✅ + 多数据源 ⬜）**  
> **5 个领域分析 Agent 全部就位，覆盖销售/会员/财务/库存/供应链五大业务域**

---

*文档版本：v1.2 | 创建日期：2026-06-09 | 最后更新：2026-06-10*
