# Prompt 版本变更日志

> 记录每次 Prompt 的修改内容、原因和效果。用于回溯分析和 A/B 测试参考。

---

## v1.1.0 — 2026-06-12

### report.yaml

**移除：报告末尾信任分级指令**

- 删除位置：`system_prompt` 末尾合规要求段 + `human_template` 强制要求段
- 原因：前端 `appendReportBubble()` 已硬编码信任分级 HTML（带样式和图标），LLM 同时输出导致重复显示
- 影响：报告末尾不再出现 LLM 生成的信任分级文字，由前端统一渲染
- 验证：admin 和 zhangsan 账号测试，信任分级只出现一次

### report_agent.py（Python 代码层）

**修复：FOLLOWUP 提取使用字符串感知括号计数**

- 问题：正则 `\[FOLLOWUP:(\[.*?\])\]` 的非贪婪匹配在 JSON 字符串内遇到 `]` 时提前截断
- 方案：改为括号计数法 + `in_string` 状态追踪，跳过字符串内的 `]`
- 影响：追问问题包含 `]` 字符时不再丢失

**修复：`encode_chart_markers` 兜底逻辑**

- 问题：`|height=` 锚点缺失时整个编码器崩溃
- 方案：未找到 `|height=` 时直接用 `]` 定位标记末尾
- 影响：LLM 截断或畸形输出不再导致报告内容丢失

---

## v1.0.0 — 2026-06-11（初始版本）

### 9 个 YAML 文件

| Agent | 文件 | 版本 | 说明 |
|-------|------|------|------|
| supervisor | `supervisor.yaml` | 1.0.0 | 路由决策：关键词 + 结构化 LLM 输出 |
| sales | `sales.yaml` | 1.0.0 | 销售分析：趋势/排名/品类/区域 |
| crm | `crm.yaml` | 1.0.0 | 会员分析：活跃度/流失/复购/RFM |
| finance | `finance.yaml` | 1.0.0 | 财务分析：退款率/客单价/利润率 |
| inventory | `inventory.yaml` | 1.0.0 | 库存分析：周转率/缺货/滞销 |
| supply_chain | `supply_chain.yaml` | 1.0.0 | 供应链分析：供应商绩效/采购成本 |
| chart_advisor | `chart_advisor.yaml` | 1.0.0 | 图表推荐：bar/line/pie/scatter/radar |
| report | `report.yaml` | 1.0.0 | 报告生成：查询型 vs 分析型双模式 |
| reflection | `reflection.yaml` | 1.0.0 | 质量审核：4 维度（一致性/逻辑/可操作/完整） |

### 设计原则

1. **查询型 vs 分析型分离**：用户问具体数据（如"Top 3"）只输出表格，不生成完整报告
2. **输出量控制**：最高级问题只输出一句话，排名问题按 Agent 返回内容输出
3. **数据诚实**：Agent 必须通过 `run_sql` 查真实数据，Prompt 禁止编造
4. **图表嵌入**：`[CHART:type|params]` 标记放在报告对应段落之后
5. **追问建议**：`[FOLLOWUP:["q1","q2","q3"]]` 放在报告末尾

---

## Prompt 管理机制

### 三级优先级

```
1. customer_schema.yaml → PromptBuilder 动态生成（客户定制）
2. prompts/yaml/*.yaml → YAML 外部化（热重载）
3. prompts/*.py → Python 硬编码（兜底）
```

### 热重载

```bash
# 无需重启服务
curl -X POST http://localhost:8002/api/v1/prompts/reload \
  -H "Authorization: Bearer $TOKEN"
```

### 版本规范

- 主版本号：Prompt 结构性变更（如新增/删除段落）
- 次版本号：措辞优化、输出格式调整
- 修订号：错别字修复、标点修正

---

*最后更新：2026-06-13*
