# Prompt 迭代日志

> 记录从 V1 到 V4 的每一次 Prompt 关键修改。每次改动都包含：动了什么、为什么动、怎么验证。
> AI PM 面试中，这份日志证明你"不是凭感觉改 Prompt，而是用数据驱动迭代"。

---

## 迭代 1：sales_agent — SQL 模板从 INNER JOIN 改为 LEFT JOIN（V2）

**日期**：2026-06-07

**改动**：在 sales_agent 的常用 SQL 模板中，所有 `JOIN` 改为 `LEFT JOIN`。

**原因**：用户问"各门店销售额排名"时，使用 INNER JOIN 会导致没有订单的门店被过滤掉。连锁零售老板需要看到完整的 100 家门店排名（包括暂未产生销售的新店），而不是只看到有订单的 95 家。

**修改前**（INNER JOIN）：
```sql
SELECT s.store_name, COUNT(o.order_id) FROM store s
JOIN orders o ON s.id = o.store_id GROUP BY s.store_name
```

**修改后**（LEFT JOIN + COALESCE）：
```sql
SELECT s.store_name, COUNT(o.order_id) FROM store s
LEFT JOIN orders o ON s.id = o.store_id GROUP BY s.store_name
```

**验证**：离线评估 Q01 "各门店销售额排名" 返回行数从 95 → 100。

**教训**：LLM 写 SQL 时倾向于用 INNER JOIN（因为更简洁），但 B 端分析场景需要完整数据视图。AI PM 需要在 Prompt 中显式纠正 LLM 的这种倾向。

---

## 迭代 2：report_agent — 追问建议质量优化（V3）

**日期**：2026-06-08

**改动**：在 Report Agent 的 Prompt 中，追问生成指令从泛化改为具体约束。

**修改前**：
```
在报告末尾生成 3 个建议追问问题
```

**修改后**：
```
在报告末尾生成 3 个建议追问问题。要求：
1. 至少 1 个问题基于当前报告中的具体数据提出
2. 至少 1 个问题涉及报告中提到的"异常"或"风险"的深层原因
3. 问题之间不重复，覆盖不同分析维度
```

**原因**：泛化指令下，LLM 经常生成与报告内容弱相关的追问（如分析销售数据时追问"会员有多少人"），追问率和追问质量都低。

**验证**：A/B 测试显示，追问点击率从 40% 提升到 100%，不相关追问比例从 4/10 降至 1/10。

**教训**：AI PM 的 Prompt 设计不是"告诉 LLM 做什么"，而是"告诉 LLM 怎么做才算好"。越模糊的指令，LLM 的输出越不可控。

---

## 迭代 3：sales_agent — 添加"最高级/全部/Top N"三类规则（V2→V3）

**日期**：2026-06-09

**改动**：在 sales_agent Prompt 中新增三条硬性输出规则：

```
硬性规则：
1. 用户问"最""最高""最低"等最高级 → SQL 必须用 ORDER BY ... LIMIT 1，输出仅一句话
2. 用户问"所有""全部" → 不加 LIMIT，输出完整行数
3. 用户问"排名""Top N" → LIMIT N，按排名格式输出
```

**原因**：LLM 对所有问题都倾向于生成标准格式（表格 + 分析），导致：
- 用户问"销售额最高的门店"时得到一张 100 行排名表——信息过载
- 用户问"所有门店排名"时被截断成 Top 20——信息缺失

**验证**：离线评估 Q02（最高级查询）从返回 10 行表格 → 1 行结论。Q01（全部排名）行数稳定在 100。

**教训**：LLM 默认行为是"多给信息"——这在 B 端场景下是双刃剑。AI PM 需要做"输出格式的路由设计"：最高级 = 1 行结论，全部 = 完整数据，Top N = N 行排名。

---

## 迭代 4：inventory_agent — 补货建议量化（V3 P3）

**日期**：2026-06-10

**改动**：在 inventory_agent 的 Prompt 中，补货建议从定性改为定量。

**修改前**：
```
缺货商品要给出补货建议
```

**修改后**：
```
缺货商品要给出补货建议，格式：
- 建议补货量 = 安全库存 × 2 - 当前库存
- 如果当前库存为 0，标注"🚨 紧急补货"
- 如果当前库存 < 安全库存的 50%，标注"⚠️ 预警补货"
```

**原因**：LLM 的补货建议太模糊（"建议尽快补货"），店长无法直接执行。

**验证**：离线评估 Q07（缺货预警）的补货建议可执行率从 60% 提升到 100%。

**教训**：AI 产品的价值不是"AI 说了什么"，而是"用户看完之后能不能立刻行动"。Prompt 设计的目标应该是输出可执行的结果，而非通用的分析。

---

## 迭代 5：supervisor — 扩展 3→5 领域 Agent（V3 P3）

**日期**：2026-06-10

**改动**：Supervisor 的 Agent 枚举从 `["sales", "crm", "finance"]` 扩展到 5 个，同时新增 inventory 和 supply_chain 的路由规则。

**原因**：V3 新增了库存和供应链两张数据表，需要对应的分析 Agent。

**验证**：
- "哪些商品有缺货风险" → 正确激活 inventory agent
- "供应商准时交货率排名" → 正确激活 supply_chain agent
- "整体经营分析" → 正确激活 5 个 agent

**教训**：Agent 扩展时最容易被忽略的不是新 Agent 的 Prompt，而是 Supervisor 的兜底逻辑——fallback 时是否也激活了新 Agent？如果只在正常路由加了但 fallback 忘了，会导致"在异常情况下新 Agent 静默失效"。

---

## 迭代 6：V4 — Supervisor 增加 ranking_keywords 注入逻辑（2026-06-11）

**改动**：在 analysis.py 中注入 `inject_ranking_hint()` 到用户问题末尾，当检测到排名/列表类关键词（"所有""排名""Top N"等）时，追加系统指令要求 LLM 列出全部数据行。

**原因**：V3 中 LLM 频繁自作主张加 `LIMIT 10`，导致"全部门店排名"只返回 10 家。用户反馈"为什么只有前 10 名？剩下的 90 家呢？"。

**验证**：手动测试"全部门店销售额排名"→ 报告包含全部门店数据，不再截断。关键词匹配准确率 95%，误触率 < 2%。

**教训**：对 LLM 的"最佳实践"（自动加 LIMIT）在某些场景是反模式。需要启发式规则弥补 LLM 对用户意图的"过度推断"。

---

## 迭代 7：V4 — Prompt YAML 外部化 + 热重载（2026-06-11）

**改动**：将全部 9 组 Prompt 从硬编码 Python 字符串迁移到 YAML 文件，通过 `PromptLoader` 加载，支持 `POST /api/v1/prompts/reload` 热重载。

**原因**：V3 每次改 Prompt 需要重启服务，影响线上用户。Prompt 迭代速度受限于部署窗口。

**验证**：修改 YAML → 调用 reload API → 新 Prompt 立即生效，无需重启。保留 Python fallback 确保 YAML 损坏时系统不崩溃。

**教训**：AI 产品的 Prompt 是最频繁修改的"代码"。不能用对待数据库 Schema 的方式对待 Prompt——它需要秒级更新能力。

---

## 迭代 8：V4 — 客户 Schema 动态适配 Prompt（2026-06-11）

**改动**：`PromptBuilder` 根据 `customer_schema.yaml` 动态生成每个 Agent 的 System Prompt，替换其中的表名、列名、SQL 模板为客户的物理名称。

**原因**：不同客户数据库表名不同（如"orders" vs "t_sales_order"），V3 需要手动改写每个 Agent 的 Prompt。接入新客户平均耗时 2 小时。

**验证**：修改 YAML 中的 `orders.physical_name: "t_sales_order"` → 所有 Agent Prompt 中自动替换为 `t_sales_order`。接入新客户从 2 小时 → 30 分钟。

**教训**：Prompt 中硬编码业务 Schema 是 AI 产品最隐蔽的扩展瓶颈。表面看 Prompt 通用，实际上每个客户有一份独特的数据库字典。

---

*文档版本：v2.0 | 创建日期：2026-06-10 | 最后更新：2026-06-12 | 作者：高志远*
