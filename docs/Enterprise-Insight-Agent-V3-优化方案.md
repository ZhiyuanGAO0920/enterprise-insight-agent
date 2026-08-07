# Enterprise Insight Agent V3 — 优化建议与详细实施方案

> ⚠️ **本文档为 V3 时期的优化建议，已于 2026-06-10 定版。**
> 
> **V4 实施状态（2026-06-12 更新）**：
> - ✅ P0+P1+P2：已在 V3.1 全部完成
> - ✅ P3（库存/供应链 Agent）：已在 V3.1 完成
> - 🆕 V4 在此基础上新增：多租户、审计日志、PDF 导出、React 前端、通知服务、结构化日志、一键部署、安全加固。详见 `CHANGELOG.md`

---

| 字段 | 内容 |
|------|------|
| **文档版本** | v1.3 |
| **文档状态** | ✅ P0+P1+P2 全部完成 + P3 部分完成（库存/供应链 Agent） |
| **目标版本** | Enterprise Insight Agent V3.0 |
| **当前基线** | V2.0.0 (commit `e861405`) |
| **作者** | 高志远 |
| **创建日期** | 2026-06-08 |
| **最后更新** | 2026-06-10 |

---

## 目录

1. [V3 总体愿景](#1-v3-总体愿景)
2. [优化优先级矩阵](#2-优化优先级矩阵)
3. [P0-1：ECharts 可视化图表集成](#3-p0-1echarts-可视化图表集成)
4. [P0-2：多轮对话与上下文感知](#4-p0-2多轮对话与上下文感知)
5. [P0-3：数据可追溯性与信任体系](#5-p0-3数据可追溯性与信任体系)
6. [P1-1：移动端适配](#6-p1-1移动端适配)
7. [P1-2：用户反馈闭环](#7-p1-2用户反馈闭环)
8. [P1-3：Prompt 管理外部化](#8-p1-3prompt-管理外部化)
9. [P2-1：APM 性能监控](#9-p2-1apm-性能监控)
10. [P2-2：错误恢复体验优化](#10-p2-2错误恢复体验优化)
11. [P2-3：CI/CD 自动化流水线](#11-p2-3cicd-自动化流水线)
12. [P3：Agent 生态扩展与多数据源](#12-p3agent-生态扩展与多数据源)
13. [V3 架构变更总览](#13-v3-架构变更总览)
14. [实施路线图与里程碑](#14-实施路线图与里程碑)
15. [资源估算与投入产出分析](#15-资源估算与投入产出分析)

---

## 实施状态追踪（2026-06-10 更新）

| 优先级 | 编号 | 优化项 | 状态 | 完成度 |
|:--:|------|------|:--:|:--:|
| **P0** | VIZ | ECharts 可视化图表 | ✅ 已完成 | 后端 Chart Advisor + 前端 ECharts 渲染 |
| **P0** | CTX | 多轮对话上下文 | ✅ 已完成 | ContextManager + Session API + 前端追问 |
| **P0** | TRUST | 数据可追溯性 | ✅ 已完成 | data_sources 收集 + 前端溯源面板 |
| **P1** | MOB | 移动端适配 | ✅ 已完成 | 响应式 CSS @media 适配 768px 以下 |
| **P1** | FB | 用户反馈闭环 | ✅ 已完成 | Feedback API + 前端 👍/👎 + 数据模型 |
| **P1** | PROMPT | Prompt 管理外部化 | ✅ 已完成 | 9 个 YAML 文件 + PromptLoader + 管理 API + 9 个 Agent 全部接入 |
| **P2** | APM | 性能监控 | ✅ 已完成 | AgentTracer + agent_trace_events 表 |
| **P2** | ERR | 错误恢复 UX | ✅ 已完成 | 14类中文友好错误映射 |
| **P2** | CICD | CI/CD 流水线 | ✅ 已完成 | GitHub Actions Lint → Test → Build |
| **P3** | AGENT | Agent 生态扩展 | ✅ 部分完成 | 库存 Agent + 供应链 Agent + 4 张新表（product/supplier/inventory/purchase_order） |
| **P3** | DATASRC | 多数据源支持 | ⬜ 规划中 | MySQL/MongoDB/CSV 抽象层 |

> **完成度：11/12 ✅** | **Agent 数量：5 个（销售/CRM/财务/库存/供应链）** | **详见 [V2 vs V3 对比](V2-vs-V3-对比.md)**

---

## 1. V3 总体愿景

### 1.1 V2 → V3 的产品演进逻辑

```
V2.0（当前）                     V3.0（目标）
─────────────────────────────────────────────────
"能用"                           "好用 + 让人信任"
AI 能分析数据                    AI 能"说服"用户
单次问答                         持续对话
纯文本输出                       图文并茂
黑盒报告                         透明可追溯
桌面 Web                         桌面 + 移动
单向输出                         双向反馈
```

### 1.2 V3 四个核心目标

| # | 目标 | 一句话描述 | 对应优化项 |
|---|------|-----------|-----------|
| 🎯 1 | **从"能看"到"好看"** | 数据以图表呈现，一眼看懂趋势 | P0-1 可视化 |
| 🎯 2 | **从"问答"到"对话"** | 支持自然追问，像分析师一样交流 | P0-2 多轮对话 |
| 🎯 3 | **从"黑盒"到"透明"** | 用户能看到数据来源，建立信任 | P0-3 可追溯性 |
| 🎯 4 | **从"桌面"到"随身"** | 老板在手机上也能随时查看 | P1-1 移动端 |

---

## 2. 优化优先级矩阵

| 优先级 | 编号 | 优化项 | 用户价值 | 实现难度 | 周期 | 依赖 |
|:--:|------|------|:--:|:--:|:--:|------|
| **P0** | VIZ | ECharts 可视化图表 | 🔴 极高 | 🟡 中 | 3 周 | 无 |
| **P0** | CTX | 多轮对话上下文 | 🔴 极高 | 🔴 高 | 4 周 | 无 |
| **P0** | TRUST | 数据可追溯性 | 🔴 极高 | 🟢 低 | 2 周 | 无 |
| **P1** | MOB | 移动端适配 | 🟡 高 | 🟡 中 | 3 周 | 无 |
| **P1** | FB | 用户反馈闭环 | 🟡 高 | 🟢 低 | 1.5 周 | 无 |
| **P1** | PROMPT | Prompt 管理外部化 | 🟡 高 | 🟢 低 | 1 周 | 无 |
| **P2** | APM | 性能监控 | 🟢 中 | 🟡 中 | 1.5 周 | 无 |
| **P2** | ERR | 错误恢复 UX | 🟢 中 | 🟢 低 | 1 周 | 无 |
| **P2** | CICD | CI/CD 流水线 | 🟢 中 | 🟡 中 | 1 周 | 无 |
| **P3** | AGENT | Agent 生态扩展 | 🟢 中 | 🔴 高 | 4 周 | CTX |
| **P3** | DATASRC | 多数据源支持 | 🟢 中 | 🔴 高 | 4 周 | 无 |

> **P0 = 必须在 V3 交付** | **P1 = 强烈建议** | **P2 = 有条件就做** | **P3 = V3.1 或后续**

---

## 3. P0-1：ECharts 可视化图表集成

### 3.1 问题分析

**当前状态（V2）**：
- 所有分析结果以 Markdown 表格展示
- 趋势分析、分布分析也只能用表格呈现
- 老板用户最需要的"一眼看出趋势"做不到

**用户痛点**：
> "各门店近一年销售额排名" → 100 行表格，老板不可能逐行看  
> "退款率变化趋势" → 用文字描述"先升后降"远不如一条折线图直观

**竞品对标**：
- 帆软 FineBI / 观远数据：图表是默认输出格式
- Metabase：查询结果自动推荐最佳图表类型
- ChatGPT Code Interpreter：可以生成 matplotlib 图表

### 3.2 方案设计

#### 3.2.1 总体思路

**分两层实现**：Agent 层负责判断"什么时候该出图"，前端层负责渲染图表。

```
Report Agent 输出                     前端渲染
─────────────────                    ─────────
Markdown 文本段落                     → 文本渲染（不变）
[CHART:bar|title=...|data=...]       → ECharts 图表
[CHART:line|title=...|data=...]      → ECharts 图表
[CHART:pie|title=...|data=...]       → ECharts 图表
Markdown 表格（图表的数据源）          → 可折叠表格（默认收起）
```

#### 3.2.2 新增组件

##### A. Chart Advisor Agent（新增节点）

在 Aggregator 和 Report Agent 之间插入一个轻量 Agent，负责：

```
输入：aggregator_summary（含各 Agent 的 SQL 查询结果）
输出：chart_suggestions（图表建议列表）

职责：
1. 分析数据特征 → 推荐图表类型
2. 从 SQL 结果中提取图表数据
3. 判断是否需要图表（不是所有查询都需要）
```

**图表类型推荐规则**：

| 数据特征 | 推荐图表 | 示例场景 |
|----------|----------|----------|
| 多实体排名（>5 项）+ 单数值列 | 横向柱状图 | "各门店销售额排名" |
| 时间序列 + 数值 | 折线图 | "近 30 天销售趋势" |
| 分类占比 + 百分比 | 饼图/环形图 | "各区域销售额占比" |
| 两个数值维度 | 散点图 | "客单价 vs 退款率（各门店）" |
| 多指标对比 | 雷达图 | "华东 vs 华北：4 维度对比" |

##### B. 前端 ECharts 渲染器

在 `index.html` 中集成 ECharts CDN，添加：

```javascript
// 图表标记解析器
function renderCharts(html) {
  return html.replace(/\[CHART:(\w+)\|(.+?)\]/g, (match, type, params) => {
    const config = parseChartParams(params);
    const chartId = 'chart_' + Math.random().toString(36).substr(2, 8);
    // 返回一个 div 容器，延迟初始化 ECharts
    setTimeout(() => initChart(chartId, type, config), 100);
    return `<div id="${chartId}" class="chart-container" style="width:100%;height:400px;"></div>`;
  });
}

function initChart(id, type, config) {
  const dom = document.getElementById(id);
  if (!dom) return;
  const chart = echarts.init(dom);
  chart.setOption(buildEChartsOption(type, config));
  // 响应式 resize
  window.addEventListener('resize', () => chart.resize());
}
```

#### 3.2.3 Chart Agent 提示词设计

```python
CHART_ADVISOR_SYSTEM_PROMPT = """你是一位数据可视化顾问。
你的任务是根据分析数据，判断是否需要生成图表，以及生成什么类型的图表。

## 图表类型选择
- bar（柱状图）：排名、对比类数据
- line（折线图）：时间趋势类数据
- pie（饼图）：占比、分布类数据
- scatter（散点图）：相关性分析
- radar（雷达图）：多维度对比

## 不需要图表的情况
- 数据行数 ≤ 3
- 纯文字结论（无数据表）
- 用户明确只要求"列表"且数据不超过 10 行

## 输出格式
请以 JSON 格式输出图表建议，每个图表包含：
{
  "charts": [
    {
      "type": "bar",
      "title": "各门店销售额排名",
      "x_data": ["门店A", "门店B", ...],
      "series": [{"name": "销售额", "data": [120000, 115000, ...]}],
      "height": "500px",
      "note": "数据来自销售分析"
    }
  ]
}
"""
```

#### 3.2.4 StateGraph 变更

```
V2:
  aggregator → report_agent → reflection_agent → ...

V3（插入 Chart Advisor）:
  aggregator → chart_advisor → report_agent → reflection_agent → ...
                                ↑
                   report_agent 使用 chart_suggestions
                   在报告中嵌入 [CHART:...] 标记
```

**AnalysisState 新增字段**：
```python
class AnalysisState(TypedDict):
    # ... 现有字段 ...
    chart_suggestions: Optional[list[dict]]  # Chart Advisor 的输出
```

#### 3.2.5 前端变更点

| 变更 | 文件 | 说明 |
|------|------|------|
| 引入 ECharts | `index.html` | CDN 引入 `echarts@5.5.0` |
| 新增 CSS | `index.html` | `.chart-container` 样式、`.chart-source-btn` 等 |
| 图表渲染器 | `index.html` | `renderCharts()` + `initChart()` + `buildEChartsOption()` |
| 数据源折叠 | `index.html` | 图表下方可展开的"查看原始数据"按钮 |
| 导出增强 | `index.html` | 下载报告时包含图表（转为 base64 图片嵌入 Markdown） |

#### 3.2.6 效果示例

```
用户：各门店近一年销售额排名

V2 输出：100 行 Markdown 表格

V3 输出：
┌────────────────────────────────────────────┐
│                                            │
│  📊 各门店销售额排名（柱状图 - TOP 20）     │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓ 门店A  120万       │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓   门店B  115万       │
│  ▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓     门店C  108万       │
│  ...                                       │
│                                            │
│  [📋 查看完整数据表格（100 行）]  ← 可折叠   │
│                                            │
│  简要分析：TOP 3 门店贡献了 11.5% 的总销售额。│
│  排名末位的 5 家门店均位于西南区域...        │
└────────────────────────────────────────────┘
```

---

## 4. P0-2：多轮对话与上下文感知

### 4.1 问题分析

**当前状态（V2）**：每次分析是独立的请求-响应，"一问一答，答完即忘"。

**真实场景模拟**：
```
用户：华东区销售为什么下降了？
V2：  [生成完整分析报告] ✅
用户：那退款率最高的那个门店呢？
V2：  ❌ 不知道"那个门店"指什么，当成独立问题重新分析
用户：它的会员流失情况呢？
V2：  ❌ 又丢失了上下文
```

**核心矛盾**：真实的经营分析是**追问驱动**的探索过程，不是独立的查询请求。

### 4.2 方案设计

#### 4.2.1 三层上下文架构

```
┌──────────────────────────────────────────────────────────┐
│                    Layer 1: 会话层                        │
│  session_id → 一次登录期间的完整对话历史                   │
│  存储：Redis (TTL = JWT 过期时间)                        │
│  内容：所有 Q&A 对的摘要                                 │
├──────────────────────────────────────────────────────────┤
│                    Layer 2: 分析层                        │
│  context_window → 最近 3 轮的详细上下文                   │
│  存储：AnalysisState 注入                                 │
│  内容：上一轮的 question、关键实体、数据结论               │
├──────────────────────────────────────────────────────────┤
│                    Layer 3: 实体层                        │
│  entity_memory → 当前对话中提到的具体实体                  │
│  存储：内存 dict                                         │
│  内容：门店名 → store_id、区域名、指标名                  │
└──────────────────────────────────────────────────────────┘
```

#### 4.2.2 新增组件

##### A. Context Manager（上下文管理器）

在 `app/tools/` 下新增 `context_manager.py`：

```python
class ContextManager:
    """管理多轮对话的上下文状态。

    三层设计：
    - Session: 完整对话历史（Redis）
    - Context Window: 当前上下文（注入 AnalysisState）
    - Entity Memory: 提到的实体（内存）
    """

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.conversation_history: list[dict] = []  # Q&A 摘要
        self.entity_memory: dict[str, dict] = {}    # 实体 → 属性
        self.current_topic: Optional[str] = None     # 当前讨论主题

    def add_turn(self, question: str, report: str,
                 entities: list[dict], summary: str):
        """记录一轮对话。"""

    def resolve_references(self, question: str) -> str:
        """解析指代：将"那个门店"替换为具体门店名。"""

    def get_context_for_llm(self) -> str:
        """生成注入到 Supervisor prompt 的上下文文本。"""

    def is_followup(self, question: str) -> bool:
        """判断是否追问。关键词：那/这个/它的/再/继续/呢"""
```

##### B. 交互优化

**方案**：每次分析完成后，系统自动生成 3 个"建议追问"按钮：

```
┌────────────────────────────────────────────────────────┐
│ [分析报告内容...]                                       │
│                                                        │
│ 💡 您可能还想问：                                       │
│ [这个门店的会员流失情况如何？] [它的退款率变化趋势？]    │
│ [对比华东其他门店的表现]                                 │
└────────────────────────────────────────────────────────┘
```

实现逻辑：在 Report Agent 的 prompt 末尾追加指令，让 LLM 同时输出 `followup_questions`。

#### 4.2.3 StateGraph 变更

```python
# AnalysisState 新增字段
class AnalysisState(TypedDict):
    # ... 现有字段 ...
    # 多轮对话
    session_id: Optional[str]              # 会话 ID
    conversation_context: Optional[str]    # 注入的上下文文本
    followup_questions: Optional[list[str]] # 建议追问
    is_followup: bool                      # 当前问题是追问
    resolved_question: Optional[str]       # 解析指代后的完整问题
```

**Supervisor Agent 增强**：在 System Prompt 开头注入上下文：

```python
# supervisor_agent 改造
if state.get("conversation_context"):
    system_prompt = (
        "## 对话上下文\n"
        f"{state['conversation_context']}\n\n"
        "---\n\n"
        + SUPERVISOR_SYSTEM_PROMPT
    )

# 如果检测到追问，将 resolved_question 作为主问题
question = state.get("resolved_question") or state["question"]
```

#### 4.2.4 API 变更

```python
# 新增 session 管理端点

@router.post("/session/create")
async def create_session(user = Depends(get_current_user)):
    """创建新的分析会话，返回 session_id。"""
    session_id = uuid.uuid4().hex
    await redis.setex(f"session:{session_id}", 28800, json.dumps({"user_id": user["user_id"], "history": []}))
    return {"session_id": session_id}

@router.get("/session/{session_id}")
async def get_session(session_id: str, user = Depends(get_current_user)):
    """获取会话历史和上下文摘要。"""
    ...

# analyze 接口加入 session_id
class AnalysisRequest(BaseModel):
    question: str
    session_id: Optional[str] = None  # 新增：会话 ID
```

#### 4.2.5 指代消解（关键难点）

这是多轮对话最核心的技术挑战。采用**LLM + 实体追踪**混合策略：

```python
async def resolve_references(question: str, entity_memory: dict, last_report: str) -> str:
    """使用轻量 LLM 调用消解指代。

    输入: "那退款最多那家的会员情况呢？"
    实体记忆: {"退款最多门店": "旗舰店040（ID=40）"}
    输出: "旗舰店040（ID=40）的会员情况如何？"
    """
    prompt = f"""将用户问题中的指代消解为具体实体。

对话中提及的实体：
{json.dumps(entity_memory, ensure_ascii=False, indent=2)}

上一轮分析摘要：
{last_report[:500]}

用户问题：{question}

请将指称不明的表述（如"那家""那个门店""它"）替换为具体实体名。
如果问题本身已经明确，原样返回。

消解后的问题："""

    response = await llm.ainvoke([HumanMessage(content=prompt)])
    return response.content.strip()
```

#### 4.2.6 前端变更

| 变更 | 说明 |
|------|------|
| 新建会话按钮 | 侧边栏增加"新建会话"按钮，清空上下文 |
| 会话历史列表 | 显示多个 session，可切换 |
| 建议追问按钮 | 报告下方渲染 3 个追问按钮 |
| 上下文指示器 | 侧边栏显示当前对话中"记住"的实体（如"已记住：旗舰店040、华东区"） |

---

## 5. P0-3：数据可追溯性与信任体系

### 5.1 问题分析

> **核心问题**：用户看到 AI 生成的经营报告，第一反应是——"这个数字对吗？"

当前 V2 的黑盒式输出让用户无法验证，这是 AI 产品在 B 端落地最大的障碍。信任不是靠"模型很强"建立的，而是靠"用户可以验证"建立的。

### 5.2 方案设计

#### 5.2.1 "来源追溯"三件套

```
报告中每个数据主张都应该有"来源"

V2（不可追溯）：
  "华东区近三个月销售额下降 15%，其中旗舰店040降幅最大"

V3（可追溯）：
  "华东区近三个月销售额下降 15%[📊 查看SQL]，其中旗舰店040降幅最大[🔍 查看明细]"

点击 [📊 查看SQL] → 展开该结论对应的 SQL 查询和数据来源
点击 [🔍 查看明细] → 展开该门店的详细数据表格
```

#### 5.2.2 实现方案

##### A. Report Agent 输出增强

不改变 Markdown 输出格式，而是在特定位置插入可点击的溯源标记：

```markdown
华东区近三个月销售额下降了 **15.2%** [^1]，
旗舰店040降幅最大（-23.5%）[^2]。

[^1]: 数据来源：`SELECT region, SUM(amount) ... WHERE create_time >= ...`（2024Q1 vs 2024Q2 对比）
[^2]: 数据来源：`SELECT store_name, SUM(amount) ... GROUP BY store_name ORDER BY ...`
```

**实现**：Report Agent 的 prompt 中增加指令，要求在关键数字后添加脚注标记 `[^N]`。前端解析后渲染为可点击的溯源链接。

##### B. 前端"数据溯源面板"

在每条 AI 回复右侧或下方增加一个可展开的溯源面板：

```
┌─────────────────────────────────────────────────────┐
│ 📊 数据溯源                                          │
│                                                     │
│ [1] "华东区销售额下降 15.2%"                          │
│     来源：销售 Agent                                │
│     SQL: SELECT region, SUM(amount)...              │
│     WHERE create_time >= '2025-01-01'               │
│     执行时间：2026-06-08 09:30:15 (0.23s)           │
│     返回行数：7 行                                   │
│     [📋 查看原始数据]                                │
│                                                     │
│ [2] "旗舰店040降幅最大（-23.5%）"                     │
│     来源：销售 Agent                                │
│     原始数据：旗舰店040 | 2024Q1: 120万 | 2024Q2: 92万│
└─────────────────────────────────────────────────────┘
```

##### C. 后端变更

**AnalysisState 新增字段**：
```python
class AnalysisState(TypedDict):
    # ... 现有字段 ...
    data_sources: Optional[list[dict]]  # 每个数据主张的来源信息
    # data_sources 结构：
    # [
    #   {
    #     "id": 1,
    #     "claim": "华东区销售额下降 15.2%",
    #     "agent": "sales",
    #     "sql": "SELECT ...",
    #     "execution_time_ms": 230,
    #     "row_count": 7,
    #     "raw_data": "表格文本"
    #   }
    # ]
```

**各 Agent 改造**：在 tool-calling 循环中，每当执行 SQL 查询后，将 SQL 文本和结果摘要追加到 `data_sources`。

```python
# sales_agent.py / crm_agent.py / finance_agent.py 中增加
if tc["name"] == "run_sql":
    data_sources.append({
        "id": len(data_sources) + 1,
        "agent": "sales",
        "sql": tc["args"]["query"],
        "execution_time_ms": ...,  # 记录执行时间
        "row_count": sql_row_count,
        "raw_data": str(result)[:5000],  # 截断存储
    })
```

---

## 6. P1-1：移动端适配

### 6.1 问题分析

连锁零售老板和区域经理的实际使用场景：
- 🕖 **周一早上 7:30**：开车到公司前，手机上看一眼上周经营周报
- 🍜 **午餐时间**：想起一个问题，手机打开看看
- 🏪 **巡店时**：在某门店发现问题，现场查询该门店数据

**桌面 Web 的局限**：这些场景都是移动端场景，桌面端占不到 30% 的使用时长。

### 6.2 方案设计

#### 6.2.1 渐进式适配策略

**第一阶段：响应式 Web（本阶段交付）**

在现有 `index.html` 基础上增加响应式 CSS，不改变架构，2-3 天工作量：

```css
/* 移动端适配 */
@media (max-width: 768px) {
  .app { flex-direction: column; }
  .sidebar { width: 100%; max-height: 200px; padding: 12px; }
  .chat { padding: 12px; }
  .msg { max-width: 100%; }
  .msg.assistant .bubble { padding: 14px; font-size: 13px; }
  .msg.assistant .bubble table { font-size: 11px; }
  .input-area form { max-width: 100%; }
  .chart-container { height: 280px !important; }
}
```

**第二阶段：企业微信/飞书 H5 内嵌**

将 Web UI 改造为可在企业微信/飞书内置浏览器中良好运行，增加 SSO 免密登录。

**第三阶段（V3.1+）**：微信小程序 / PWA

#### 6.2.2 移动端特有的交互优化

| 特性 | 桌面端 | 移动端优化 |
|------|--------|-----------|
| 输入方式 | 键盘输入 | 增加语音输入按钮（Web Speech API） |
| 快捷问题 | 无 | 首页提供 6 个高频问题快捷入口 |
| 数据表格 | 宽表格 | 横向滚动 + 冻结首列 |
| 图表 | 400px 高度 | 280px 高度，适配窄屏 |
| 下载导出 | 下载 .md | 分享按钮（生成分享图片/链接） |

#### 6.2.3 快捷入口设计

移动端首页（空状态）不再是简单的几行文字，而是：

```
┌──────────────────────────┐
│                          │
│  👋 早上好，张总          │
│                          │
│  📊 今日快报              │
│  昨日销售额：¥128,500    │
│  活跃门店：96/100        │
│  本周退款率：2.3%        │
│                          │
│  ⚡ 常用分析              │
│  ┌────────┐ ┌────────┐  │
│  │ 各门店  │ │ 近期销售│  │
│  │ 销售排名│ │ 趋势    │  │
│  └────────┘ └────────┘  │
│  ┌────────┐ ┌────────┐  │
│  │ 退款率  │ │ 会员    │  │
│  │ 排名    │ │ 流失    │  │
│  └────────┘ └────────┘  │
│  ┌────────┐ ┌────────┐  │
│  │ 整体经营│ │ 各区域  │  │
│  │ 分析    │ │ 对比    │  │
│  └────────┘ └────────┘  │
│                          │
│  [💬 自由提问...]        │
└──────────────────────────┘
```

**今日快报数据来源**：新增一个轻量 API `GET /api/dashboard/today-summary`，执行预定义的汇总查询（近 24h 销售额、活跃门店数、7 天退款率），缓存到 Redis（TTL 5 分钟）。

---

## 7. P1-2：用户反馈闭环

### 7.1 问题分析

当前 V2 没有任何用户反馈机制。你无法知道：
- 用户对分析结果满意吗？
- Agent 的回答帮助用户解决了问题吗？
- 哪个 Agent 最常出错？

### 7.2 方案设计

#### 7.2.1 反馈采集

每条 AI 回复下方增加反馈按钮：

```
┌────────────────────────────────────────────┐
│ [报告内容...]                               │
│                                            │
│ 👍 有帮助    👎 不准确    原因：___         │
│ 这个回答对你有帮助吗？                      │
└────────────────────────────────────────────┘
```

#### 7.2.2 反馈数据模型

```sql
-- 新增表
CREATE TABLE user_feedback (
    id SERIAL PRIMARY KEY,
    analysis_history_id INT REFERENCES analysis_history(id),
    user_id INT REFERENCES users(id),
    rating VARCHAR(10),          -- 'helpful' / 'inaccurate' / 'not_relevant'
    reason TEXT,                 -- 用户填写的原因（可选）
    agent_issues JSONB,          -- 用户标记的出错 Agent: {"sales": "数据错误", "report": "结论矛盾"}
    created_at TIMESTAMP DEFAULT NOW()
);
```

#### 7.2.3 反馈驱动的 Agent 优化

```
反馈数据流向：
用户点 👍/👎
    ↓
存入 user_feedback 表
    ↓
定时分析（每周汇总报告）
    ↓
识别高频问题 Agent / Prompt 缺陷
    ↓
针对性优化 Prompt / 增加 SQL 模板 / 修复边界情况
```

**反馈分析仪表板**（简单版）：新增 `GET /api/feedback/stats`，返回：

```json
{
  "total_feedback": 156,
  "helpful_rate": 0.82,
  "by_agent": {
    "sales": {"helpful": 50, "inaccurate": 8},
    "crm": {"helpful": 45, "inaccurate": 12},
    "finance": {"helpful": 33, "inaccurate": 5},
    "report": {"helpful": 28, "inaccurate": 15}
  },
  "top_issues": [
    {"reason": "数据与实际情况不符", "count": 5},
    {"reason": "遗漏了重要维度", "count": 3}
  ]
}
```

---

## 8. P1-3：Prompt 管理外部化

> ✅ **已于 2026-06-09 实施完成。** 实现方案与下方设计基本一致：7 个 YAML 文件（`prompts/yaml/*.yaml`）、`app/tools/prompt_loader.py`（PromptLoader + `get_prompt()` / `reload()`）、`app/api/routes/prompts.py`（3 个管理 API）、7 个 Agent 全部接入（通过 `fallback` 参数实现零风险兜底）。详见测试文件 `tests/test_prompt_loader.py`（11 条测试）。

### 8.1 问题分析

**当前状态（V2）**：
- 所有 6 个 Agent 的 System Prompt 硬编码在 `prompts/*.py` 中
- 修改 Prompt 需要改代码 → 重启服务
- 无法进行 A/B 测试（对比两个 Prompt 版本的效果）
- 非技术人员（运营/产品）无法调整 Prompt

### 8.2 方案设计

#### 8.2.1 Prompt 配置化

将 Prompt 迁移到 YAML 配置文件（或数据库），启动时加载，支持热更新：

```
prompts/
├── config.yaml          # Prompt 元数据配置
├── sales_v1.yaml        # Sales Agent Prompt v1
├── sales_v2.yaml        # Sales Agent Prompt v2（灰度测试）
├── crm_v1.yaml
├── finance_v1.yaml
├── report_v1.yaml
├── reflection_v1.yaml
└── supervisor_v1.yaml
```

**YAML 格式示例** (`sales_v1.yaml`)：

```yaml
agent: sales
version: 1
status: production          # production / staging / deprecated
created: 2026-06-01
updated: 2026-06-08
author: 高志远
description: 销售 Agent V1 — 含排名表格式输出规范

system_prompt: |
  你是一位资深销售数据分析师。
  你的任务是根据用户的问题，对销售数据进行分析。
  ...

  ## 规则
  - 先用上面的模板查询，再根据结果给结论
  - 不要编造数据，只根据查询结果分析
  ...

sql_templates:
  regional_sales: |
    SELECT s.region, COUNT(o.order_id) as orders,
           COALESCE(SUM(o.amount),0) as sales
    FROM store s LEFT JOIN orders o ON s.id=o.store_id
    GROUP BY s.region ORDER BY sales DESC

  store_ranking: |
    SELECT s.store_name, s.region, COUNT(o.order_id) as orders,
           COALESCE(SUM(o.amount),0) as sales
    FROM store s LEFT JOIN orders o ON s.id=o.store_id
    GROUP BY s.id, s.store_name, s.region ORDER BY sales DESC
  ...

ab_test:
  enabled: false
  variant: null
  traffic_split: {}
```

#### 8.2.2 Prompt Loader

```python
# app/prompts/loader.py
import yaml
from pathlib import Path
from functools import lru_cache

class PromptLoader:
    """加载和管理 Prompt 配置。"""

    def __init__(self, prompts_dir: str = "prompts"):
        self.prompts_dir = Path(prompts_dir)
        self._cache: dict[str, dict] = {}

    def load(self, agent: str, version: str = None) -> dict:
        """加载指定 Agent 的 Prompt 配置。"""
        version = version or self._get_production_version(agent)
        cache_key = f"{agent}:{version}"
        if cache_key not in self._cache:
            filepath = self.prompts_dir / f"{agent}_{version}.yaml"
            with open(filepath, "r", encoding="utf-8") as f:
                self._cache[cache_key] = yaml.safe_load(f)
        return self._cache[cache_key]

    def get_system_prompt(self, agent: str) -> str:
        """获取 Agent 的 System Prompt。"""
        return self.load(agent)["system_prompt"]

    def reload(self, agent: str):
        """热重载指定 Agent 的 Prompt（清除缓存）。"""
        for key in list(self._cache.keys()):
            if key.startswith(f"{agent}:"):
                del self._cache[key]
```

#### 8.2.3 A/B 测试支持

```python
# PromptRouter：根据用户 ID 哈希分流到不同 Prompt 版本
class PromptRouter:
    def get_prompt_version(self, agent: str, user_id: int) -> str:
        config = self.load(agent)
        ab = config.get("ab_test", {})
        if not ab.get("enabled"):
            return "v1"

        # 基于 user_id 的一致性哈希分流
        bucket = user_id % 100
        cumulative = 0
        for version, percentage in ab.get("traffic_split", {}).items():
            cumulative += percentage
            if bucket < cumulative:
                return version
        return "v1"  # fallback
```

#### 8.2.4 迁移策略

**零风险迁移**：不删除现有 `prompts/*.py` 文件，而是增加一个兼容层：

```python
# prompts/sales_prompt.py（保留兼容）
import os
if os.environ.get("PROMPT_MODE") == "yaml":
    from app.prompts.loader import PromptLoader
    _loader = PromptLoader()
    SALES_SYSTEM_PROMPT = _loader.get_system_prompt("sales")
else:
    SALES_SYSTEM_PROMPT = """你是一位资深销售数据分析师..."""  # 原有硬编码
```

这样 V3 初期可以继续使用硬编码 Prompt，配置化逐步灰度切换。

---

## 9. P2-1：APM 性能监控

### 9.1 问题分析

当前 V2 无法回答以下问题：
- 各 Agent 节点的平均耗时是多少？
- 哪个环节是瓶颈（SQL 执行？LLM 推理？向量检索？）？
- 一天有多少次分析？成功/失败率？

### 9.2 方案设计

#### 9.2.1 轻量 APM 实现

**不引入外部 APM 系统（如 Datadog/Grafana）**，而是在 LangGraph 的每个节点前后插入计时逻辑，写入数据库。

```python
# app/apm/tracer.py
import time
from contextlib import asynccontextmanager

class AgentTracer:
    """轻量级 Agent 执行追踪器。"""

    @asynccontextmanager
    async def trace_node(self, node_name: str, question: str, session_id: str):
        """追踪一个 Agent 节点的执行。"""
        start = time.monotonic()
        error = None
        try:
            yield
        except Exception as e:
            error = str(e)
            raise
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000
            await self._record(node_name, elapsed_ms, error, question, session_id)

    async def _record(self, node, elapsed_ms, error, question, session_id):
        """写入 trace_events 表（异步，不影响主流程）。"""
        ...
```

#### 9.2.2 监控数据模型

```sql
CREATE TABLE agent_trace_events (
    id BIGSERIAL PRIMARY KEY,
    session_id VARCHAR(64),
    node_name VARCHAR(50),        -- 'supervisor' / 'sales_agent' / 'report_agent' 等
    question_hash VARCHAR(32),    -- 用于聚合相同问题的耗时
    elapsed_ms INT,
    error TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_trace_node ON agent_trace_events(node_name, created_at);
CREATE INDEX idx_trace_session ON agent_trace_events(session_id);
```

#### 9.2.3 监控仪表板 API

```python
@router.get("/admin/monitor/stats")
async def get_monitor_stats(
    hours: int = 24,
    user: dict = Depends(require_permission("admin:access")),
):
    """返回过去 N 小时的性能统计。"""
    return {
        "total_analyses": 128,
        "success_rate": 0.94,
        "avg_total_time_ms": 32000,
        "p95_total_time_ms": 58000,
        "by_node": {
            "supervisor": {"avg_ms": 1200, "p95_ms": 2500},
            "sales_agent": {"avg_ms": 8000, "p95_ms": 15000},
            "crm_agent": {"avg_ms": 6500, "p95_ms": 12000},
            "finance_agent": {"avg_ms": 5500, "p95_ms": 10000},
            "aggregator": {"avg_ms": 50, "p95_ms": 100},
            "report_agent": {"avg_ms": 10000, "p95_ms": 20000},
            "reflection_agent": {"avg_ms": 3000, "p95_ms": 6000},
            "save_memory": {"avg_ms": 1500, "p95_ms": 3000},
        }
    }
```

---

## 10. P2-2：错误恢复体验优化

### 10.1 问题分析

当前 V2 的错误处理对用户极不友好：

```json
// 用户看到的是这样的
{ "agent_errors": [{"agent": "sales", "error": "Execution failed: column 'status' does not exist"}] }
```

用户不理解这是什么意思，也不知道该怎么办。

### 10.2 方案设计

#### 10.2.1 错误分级与用户友好消息

```python
# app/errors/user_friendly.py

ERROR_MAP = {
    "invalid username or password": {
        "user_message": "用户名或密码错误，请重试。",
        "action": "retry_login",
        "icon": "🔐"
    },
    "column.*does not exist": {
        "user_message": "数据库查询遇到技术问题，正在重新尝试...",
        "action": "auto_retry",  # Agent 层自动重试（改 SQL）
        "icon": "🔄"
    },
    "connection.*refused": {
        "user_message": "数据库暂时无法连接，请稍后重试。如果持续出现，请联系管理员。",
        "action": "notify_admin",
        "icon": "🔌"
    },
    "Rate limit exceeded": {
        "user_message": "请求太频繁了，请等待 {retry_after} 秒后再试。",
        "action": "wait",
        "icon": "⏱️"
    },
    "token.*expired": {
        "user_message": "登录已过期，请重新登录。",
        "action": "redirect_login",
        "icon": "🔑"
    },
}

def get_user_friendly_error(raw_error: str) -> dict:
    """将原始错误转为用户可理解的消息。"""
    for pattern, template in ERROR_MAP.items():
        if re.search(pattern, raw_error, re.IGNORECASE):
            return template
    # 兜底
    return {
        "user_message": "系统遇到一个意外问题，已自动记录。请尝试重新提问。",
        "action": "report_and_retry",
        "icon": "⚠️"
    }
```

#### 10.2.2 前端错误展示改进

从当前的单行错误文字，改为结构化的错误卡片：

```
┌──────────────────────────────────────────────────┐
│ 🔄 销售分析遇到暂时问题，已自动重试               │
│                                                  │
│ 自动调整了查询方式，分析结果如下。                │
│ 如果您希望了解技术细节：                          │
│ [🔧 查看详情] → 展开：数据库缺少 'status' 列，    │
│  Agent 已使用 'refund_amount > 0' 替代。         │
└──────────────────────────────────────────────────┘
```

---

## 11. P2-3：CI/CD 自动化流水线

### 11.1 问题分析

当前 V2 没有自动化 CI/CD，所有测试手动执行。缺少：
- 代码提交自动跑测试
- PR 自动检查代码质量
- 自动构建 Docker 镜像
- 自动部署

### 11.2 GitHub Actions 流水线设计

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [master, develop]
  pull_request:
    branches: [master]

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install ruff
      - run: ruff check app/ prompts/ tests/

  test:
    needs: lint
    runs-on: ubuntu-latest
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env: { POSTGRES_USER: admin, POSTGRES_PASSWORD: admin123, POSTGRES_DB: enterprise_db }
        ports: ['5432:5432']
      redis:
        image: redis:7-alpine
        ports: ['6379:6379']
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.12' }
      - run: pip install -e ".[dev]"
      - run: pytest tests/ -v --cov=app --cov-report=xml
        env:
          DATABASE_URL_TEST: postgresql+asyncpg://admin:admin123@localhost:5432/enterprise_db
          DEEPSEEK_API_KEY: ${{ secrets.DEEPSEEK_API_KEY }}
      - uses: codecov/codecov-action@v4
        with: { file: ./coverage.xml }

  build:
    needs: test
    if: github.ref == 'refs/heads/master'
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Build Docker image
        run: docker build -t enterprise-insight-agent:${{ github.sha }} .
      - name: Push to registry
        run: |
          docker tag enterprise-insight-agent:${{ github.sha }} ghcr.io/${{ github.repository }}:${{ github.sha }}
          docker push ghcr.io/${{ github.repository }}:${{ github.sha }}
```

---

## 12. P3：Agent 生态扩展与多数据源

### 12.1 新增 Agent

#### 12.1.1 库存分析 Agent（Inventory Agent）

```
职责：
- 库存周转率分析
- 滞销商品预警
- 补货建议
- 品类库存健康度

数据表（需新增）：
- inventory（库存记录）
- product（商品信息）
- category（品类）
```

#### 12.1.2 供应链 Agent（Supply Chain Agent）

```
职责：
- 供应商绩效分析
- 采购成本趋势
- 物流时效分析
```

### 12.2 多数据源支持

**当前**：仅支持 PostgreSQL（硬编码）。

**V3 目标**：通过抽象数据源层，支持多类型数据源：

```python
# app/datasources/base.py
class DataSource(ABC):
    """数据源抽象基类。"""

    @abstractmethod
    async def execute_query(self, query: str) -> list[dict]:
        """执行查询并返回结果。"""
        ...

    @abstractmethod
    async def get_schema(self, table: str = None) -> str:
        """获取数据库结构信息。"""
        ...

# app/datasources/postgres.py
class PostgresDataSource(DataSource):
    """PostgreSQL 数据源（已有）。"""
    ...

# app/datasources/mysql.py
class MySQLDataSource(DataSource):
    """MySQL 数据源。"""
    ...

# app/datasources/mongodb.py
class MongoDBDataSource(DataSource):
    """MongoDB 数据源。"""
    ...

# app/datasources/csv_files.py
class CSVDataSource(DataSource):
    """CSV 文件数据源（上传临时分析）。"""
    ...
```

**配置方式**（`.env` 扩展）：
```bash
# 多数据源配置
DATASOURCES=postgres_main,mysql_erp,csv_upload
DATASOURCE_POSTGRES_MAIN_URL=postgresql+asyncpg://...
DATASOURCE_MYSQL_ERP_URL=mysql+aiomysql://...
DATASOURCE_CSV_UPLOAD_DIR=./uploads/
```

---

## 13. V3 架构变更总览

### 13.1 新增模块

```
app/
├── agents/
│   ├── ...（7 个现有 Agent）
│   ├── chart_advisor_agent.py     # 🆕 图表推荐 Agent
│   └── inventory_agent.py         # 🆕 库存分析 Agent（P3）
├── tools/
│   ├── ...（6 个现有工具）
│   ├── context_manager.py         # ✅ 已实现 多轮对话上下文管理
│   ├── prompt_loader.py           # ✅ 已实现 Prompt YAML 加载器
│   └── datasources/               # ⬜ P3 多数据源抽象层
│       ├── base.py
│       ├── postgres.py
│       ├── mysql.py
│       └── csv_upload.py
├── prompts/
│   ├── *_prompt.py                # Python 硬编码版（兜底）
│   └── yaml/                      # ✅ 已实现 YAML 外部化 Prompt
│       ├── sales.yaml
│       ├── crm.yaml
│       ├── finance.yaml
│       ├── supervisor.yaml
│       ├── report.yaml
│       ├── reflection.yaml
│       └── chart_advisor.yaml
├── apm/
│   └── tracer.py                  # ✅ 已实现 Agent 执行追踪器
├── errors/
│   └── user_friendly.py           # ✅ 已实现 14 类中文友好错误
└── api/
    ├── static/
    │   └── index.html             # 🔧 重大更新（ECharts + 响应式）
    └── routes/
        ├── session.py             # ✅ 已实现 会话管理
        ├── feedback.py            # ✅ 已实现 反馈管理
        ├── prompts.py             # ✅ 已实现 Prompt 管理 API
        └── monitor.py             # ⬜ P3 监控仪表板
```

### 13.2 AnalysisState 完整定义（V3）

```python
class AnalysisState(TypedDict):
    # ==== V2 字段（不变）====
    question: str
    user_id: Optional[int]
    store_ids: Optional[list[str]]
    sales_result: Optional[str]
    crm_result: Optional[str]
    finance_result: Optional[str]
    agent_errors: Annotated[list[dict], add]
    aggregator_summary: Optional[str]
    report: Optional[str]
    final_report: Optional[str]
    reflection_passed: Optional[bool]
    reflection_feedback: Optional[str]
    reflection_retries: int
    supervisor_plan: Optional[str]
    activated_agents: Optional[list[str]]
    memory_record_id: Optional[int]

    # ==== V3 新增字段 ====
    # 图表
    chart_suggestions: Optional[list[dict]]

    # 多轮对话
    session_id: Optional[str]
    conversation_context: Optional[str]
    followup_questions: Optional[list[str]]
    is_followup: bool
    resolved_question: Optional[str]

    # 数据溯源
    data_sources: Optional[list[dict]]
```

### 13.3 LangGraph 拓扑（V3）

```
                        ┌──────────────┐
                        │  supervisor  │
                        └──────┬───────┘
                               │
              ┌────────────────┼────────────────┐
              ▼                ▼                ▼
        sales_agent      crm_agent      finance_agent
              │                │                │
              └────────────────┼────────────────┘
                               ▼
                         aggregator
                               │
                               ▼
                      ┌─ chart_advisor ─┐  ← 🆕
                      │  数据→图表推荐   │
                      └────────┬────────┘
                               ▼
                         report_agent
                      （嵌入图表标记）
                               │
                               ▼
                      reflection_agent
                               │
                               ▼
                         save_memory
                      （含图表+溯源）
```

---

## 14. 实施路线图与里程碑

### 14.1 总览

```
Week    1    2    3    4    5    6    7    8    9   10   11   12
────────────────────────────────────────────────────────────────
P0-3 TRUST  ████████
P0-1 VIZ           ██████████████
P0-2 CTX                          ████████████████████
P1-3 PROMPT                       ████
P1-2 FB                                 ████████
P2-2 ERR                                ████
P2-1 APM                                       ████████
P1-1 MOB                                            ██████████████
P2-3 CICD                                           ████
────────────────────────────────────────────────────────────────
          M1           M2           M3           M4
        (Week 2)     (Week 5)     (Week 8)    (Week 12)
```

### 14.2 里程碑定义

> 🎉 **实际进度**：P0+P1+P2 全部 10/10 已于 2026-06-09 完成，大幅超前于原计划。

| 里程碑 | 原计划 | 交付物 | 实际状态 |
|--------|------|--------|:--:|
| **M1** | Week 2 | 数据溯源（P0-3）完成 | ✅ |
| **M2** | Week 5 | 图表可视化（P0-1）+ Prompt 外部化（P1-3） | ✅ |
| **M3** | Week 8 | 多轮对话（P0-2）+ 反馈系统（P1-2） | ✅ |
| **M4** | Week 12 | 移动端（P1-1）+ APM（P2-1）+ CI/CD（P2-3） | ✅ |

### 14.3 快速胜利（已全部完成 ✅）

| 任务 | 原计划 | 说明 | 状态 |
|------|------|------|:--:|
| Prompt 外部化基础框架 | 2 天 | YAML Loader + 兼容层 + 管理 API | ✅ |
| 用户反馈数据模型 + API | 1 天 | 建表 + POST/GET 端点 | ✅ |
| 错误友好消息映射 | 1 天 | ERROR_MAP 字典 + 前端展示 | ✅ |
| 响应式 CSS 基础适配 | 1 天 | 移动端布局（不改架构） | ✅ |

---

## 15. 资源估算与投入产出分析

### 15.1 工作量估算

| 优先级 | 优化项 | 后端（人天） | 前端（人天） | 测试（人天） | 合计 |
|:--:|------|:--:|:--:|:--:|:--:|
| P0 | ECharts 可视化 | 8 | 7 | 3 | **18** |
| P0 | 多轮对话 | 12 | 5 | 4 | **21** |
| P0 | 数据可追溯性 | 5 | 4 | 2 | **11** |
| P1 | 移动端适配 | 3 | 8 | 3 | **14** |
| P1 | 用户反馈闭环 | 3 | 3 | 1 | **7** |
| P1 | Prompt 管理外部化 | 4 | 0 | 2 | **6** |
| P2 | APM 性能监控 | 5 | 2 | 2 | **9** |
| P2 | 错误恢复 UX | 2 | 3 | 1 | **6** |
| P2 | CI/CD 流水线 | 4 | 0 | 1 | **5** |
| P3 | Agent 生态扩展 | 15 | 2 | 5 | **22** |
| P3 | 多数据源 | 12 | 0 | 5 | **17** |

> **P0+P1 合计**：约 **77 人天**（≈ 3.5 人月，单人全职约 15 周）  
> **P0+P1+P2 合计**：约 **97 人天**（≈ 4.5 人月）

### 15.2 投入产出分析

| 优化项 | 投入（人天） | 预期效果 | ROI 评级 |
|------|:--:|------|:--:|
| **可视化图表** | 18 | 用户 NPS 预计提升 20+，核心差异化竞争壁垒 | ⭐⭐⭐⭐⭐ |
| **多轮对话** | 21 | 单次会话平均问题数从 1.0 → 3.0+，日活粘性提升 3x | ⭐⭐⭐⭐⭐ |
| **数据可追溯性** | 11 | 用户信任度质变，为企业付费转化铺路 | ⭐⭐⭐⭐ |
| **移动端适配** | 14 | 覆盖 70%+ 的实际使用场景（老板手机端） | ⭐⭐⭐⭐ |
| 用户反馈闭环 | 7 | 产品迭代从"拍脑袋"变为"数据驱动" | ⭐⭐⭐ |
| Prompt 外部化 | 6 | 运营效率提升 5x，支持 A/B 测试 | ⭐⭐⭐ |
| APM 监控 | 9 | 性能问题可视化的前提 | ⭐⭐ |
| CI/CD | 5 | 提升工程效率，减少手动操作 | ⭐⭐ |

---

> **建议**：如果资源有限，优先完成 **P0（可视化 + 多轮对话 + 数据溯源）**，这三项共计 50 人天。
> 这三项带来的体验提升 > 其余所有优化项之和，是从"能用"到"好用"最关键的一步。

---

*文档版本：v1.2 | 创建日期：2026-06-08 | 最后更新：2026-06-09 | 作者：高志远*
