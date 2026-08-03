# Enterprise Insight Agent V4 — AI 功能交互流程

> 涵盖正常流程、异常处理、边界情况。适用于开发自测、QA 测试、Demo 演示参考。

---

## 目录

1. [页面加载与身份认证](#1-页面加载与身份认证)
2. [经营看板](#2-经营看板)
3. [分析对话（流式）](#3-分析对话流式)
4. [分析对话（非流式 / 缓存）](#4-分析对话非流式--缓存)
5. [Multi-Agent 分析链路](#5-multi-agent-分析链路)
6. [行级数据安全（RLS）](#6-行级数据安全rls)
7. [报告交互（导出 / 反馈 / 历史）](#7-报告交互导出--反馈--历史)
8. [异常与降级处理](#8-异常与降级处理)
9. [边界情况汇总](#9-边界情况汇总)

---

## 1. 页面加载与身份认证

### 正常流程

```
浏览器打开 http://localhost:8002/
  │
  ├─ [localStorage 无 token] → 展示欢迎页
  │   ├─ 网格背景动画 + 脉冲光晕 + 浮动粒子
  │   ├─ 渐变标题 "Enterprise Insight Agent" + 统计数字（10 Agent / 5 业务域 / SQL 全链路追溯 / 60s 报告）
  │   └─ 用户点击「进入系统」
  │       ├─ 登录弹窗出现（z-index 低于欢迎页，先出现在背后再淡出欢迎页）
  │       └─ 用户输入用户名 + 密码 → POST /api/v1/auth/login
  │           ├─ [200] → token 存入 localStorage → 隐藏登录 → 进入看板页
  │           └─ [401] → 显示"用户名或密码错误"
  │
  └─ [localStorage 有 token] → 跳过欢迎页，直接恢复会话
      ├─ 隐藏欢迎页和登录弹窗
      ├─ GET /api/v1/dashboard/today-summary（验证 token 有效性）
      │   ├─ [200] → token 有效 → 进入看板页
      │   └─ [非 200] → 清除 localStorage → 回退到欢迎页
      └─ 进入看板页（默认 Tab）
```

### 异常流程

| 场景 | 触发条件 | 系统行为 |
|------|---------|---------|
| 网络不可达 | `fetch` 抛出网络错误 | 显示"网络无法连接"，保持在登录页 |
| Token 过期 | JWT 超过 8 小时 | `/today-summary` 返回 401 → 清除 token → 回退欢迎页 |
| 账户被禁用 | `user.is_active = false` | 返回 403 "账户已被禁用" |
| 跨用户会话访问 | session_id 属于其他用户 | 返回 403 "无权访问此会话" |
| localStorage 被清空 | 用户手动清除浏览器数据 | 等同于首次访问，展示欢迎页 |

### 边界情况

| 情况 | 行为 |
|------|------|
| 刷新页面（已登录） | 自动恢复会话，直接进入看板页 |
| 刷新页面（未登录） | 展示欢迎页 |
| 多标签页同时登录 | 各自独立，token 共享（localStorage） |
| 退出登录 | POST /api/v1/auth/logout → 令牌加入黑名单 → 清除 localStorage → 刷新 |
| 切换账户 | 显示登录弹窗，重新登录后覆盖 token |
| 密码可见性切换 | 点击 👁 图标，切换 `input type="password"` ↔ `"text"` |

---

## 2. 经营看板

### 正常流程

```
登录成功 → 默认进入「📊 经营看板」页面
  │
  ├─ 侧边栏 5 个导航项：看板/对话/历史/监控/系统管理
  │   ├─ 账户操作移至 Header 右上角下拉菜单
  │   └─ 角色信息显示在用户菜单中
  │
  ├─ GET /api/v1/dashboard/overview
  │   ├─ 6 个 KPI 卡片：今日销售额（含环比↑↓）、昨日销售额、退款率、活跃门店、会员总数、区域覆盖
  │   │   └─ KPI 数字带递增动画（从 0 到目标值 easeOut）
  │   │   └─ 数据时效指示器「数据更新于 HH:mm」
  │   ├─ 近 30 天销售趋势折线图（渐变面积填充）
  │   ├─ 各区域销售占比环形图
  │   ├─ 门店销售额 Top 10（横向柱状图 + 排名表格）
  │   └─ 退款率 Top 10 柱状图（新增）
  │
  ├─ Redis 缓存 5 分钟，按 user_id + store_ids 分键
  │
  └─ 侧边栏图标切换页面视图
```

### 异常流程

| 场景 | 触发条件 | 系统行为 |
|------|---------|---------|
| API 返回 500 | 单个 SQL 查询失败 | `_safe_scalar` / `_safe_rows` 返回默认值（0 / []），其他模块不受影响 |
| Redis 不可用 | 缓存读写异常 | 跳过缓存，直接查数据库 |
| 所有查询失败 | 数据库完全不可达 | 所有 KPI 显示 0，图表为空 |
| 用户无数据权限 | store_ids = [] | 查询注入 `WHERE 1=0`，返回全 0 |
| ECharts 未加载 | CDN 不可达 | 图表区域空白，不报错 |

### 边界情况

| 情况 | 行为 |
|------|------|
| admin（全量） | 看到 7 个区域、100 家门店的全量数据 |
| zhangsan（华东经理） | 只看到华东区域、22 家门店的数据 |
| lisi（单店店长） | 只看到 1 家门店的数据 |
| 当天无订单 | 今日销售额 = ¥0，趋势图正常显示历史 |
| 新建会话（看板页） | 自动切换到聊天 Tab |

---

## 3. 分析对话（流式）

### 正常流程

```
用户在聊天 Tab 输入问题 → 点击「提问」或按 Enter
  │
  ├─ 前端验证
  │   ├─ 问题为空 → 不发送
  │   ├─ 正在分析中 → toast "请等待当前分析完成"
  │   └─ 未登录 → toast "请先登录"
  │
  ├─ 按钮变为红色「取消」
  │
  ├─ POST /api/v1/analysis/analyze-stream（SSE）
  │   │
  │   ├─ [并行] POST /api/v1/analysis/analyze?check_cache=true
  │   │   └─ 仅查 Redis，不触发 LLM（防止双倍 token 消耗）
  │   │
  │   └─ SSE 事件流（按顺序到达）：
  │       │
  │       ├─ phase(start): 进度步骤亮起（蓝色 active），标题更新
  │       │   "🧠 正在规划任务..."
  │       │   "🧠 推理过程"（V4.5 新增折叠面板，展示 Supervisor 激活的 Agent 和推理原因）
  │       │   "📊 正在查询销售数据..."
  │       │   "👥 正在查询会员数据..."
  │       │   ...
  │       │
  │       ├─ progress: 实时状态文字更新
  │       │   "→ 激活 销售 Agent（趋势 / 排名 / 品类）"
  │       │
  │       ├─ token: 报告正文流式缓冲（report_agent 流式输出）
  │       │   ├─ 首个 token 到达时：检查缓存是否已返回
  │       │   │   ├─ 缓存命中 → 取消 SSE，直接渲染缓存报告
  │       │   │   └─ 缓存未命中 → 继续接收，但**不实时渲染**
  │       │   ├─ 所有 token 在内存中缓冲（不展示到 DOM）
  │       │   └─ 质量审核（Reflection）通过前不展示任何内容，避免重试时报告闪烁
  │       │
  │       └─ done: 最终结果（审核已通过）
  │           ├─ report: 完整报告（含 [CHART:...] 标记）
  │           ├─ data_sources: SQL 溯源数据（V4.5 恢复展示，含展开/折叠）
  │           ├─ followup_questions: 追问建议（LLM 生成 + 规则兜底）
  │           ├─ reflection_feedback: 质检反馈详情（V4.2 新增）
  │           └─ record_id: 分析记录 ID（用于反馈）
  │
  ├─ 移除进度面板 → 渐进展示报告
  │   ├─ 报告内容按 40~50 块逐步渲染（约 2 秒渐入效果）
  │   ├─ 展示完成后自动滚动到报告顶部，方便从头阅读
  │   ├─ 操作栏：📋 复制 / 🖨️ 打印 / ⬇️ Markdown / 📄 PDF
  │   ├─ 💡 追问按钮（基于报告关键词规则生成，100% 展示，V4.4 规则兜底）
  │   └─ 👍👎 反馈按钮（点击后展示平台好评率）
  │
  └─ 按钮恢复为蓝色「提问」
```

### 异常流程

| 场景 | 触发条件 | 系统行为 |
|------|---------|---------|
| 用户点击取消 | `cancelAnalysis()` 调用 | AbortController 中止 fetch → 移除进度面板 → 流式气泡保留 "已取消" |
| SSE 连接中断 | 网络波动 / 服务重启 | 已接收的 token 保留，未接收的部分丢失。显示部分报告或"未生成报告内容" |
| 频控限制 | 超过速率限制 | 返回 429 → 显示错误提示 |
| 问题过长 | > 2000 字符 | 前端阻止发送 |
| 后端 500 | Agent 链路异常 | `done` 事件的 `errors` 数组包含各 Agent 错误信息 |

### 边界情况

| 情况 | 行为 |
|------|------|
| 缓存命中（5min 内重复问题） | 首个 token 到达时检测到缓存 → 秒返完整报告，跳过流式 |
| 多轮对话追问 | 带 session_id，注入历史上下文 |
| 中文排名查询 | 自动追加 "请列出全部结果" 指令，防止截断 |
| Agent 部分失败 | 失败的 Agent 返回 None，不影响其他 Agent。报告注明数据缺失 |
| 所有 Agent 失败 | 生成 Python 级错误报告（不依赖 LLM），说明失败原因和建议 |
| 反思未通过 | 自动重试 1 次报告生成 |

---

## 4. 分析对话（非流式 / 缓存）

### 正常流程

```
POST /api/v1/analysis/analyze
  │
  ├─ 构造缓存键：md5(user_id + tenant_id + store_ids + session_id + question)
  │
  ├─ [缓存命中] → 直接返回 AnalysisResponse
  │   ├─ Redis 读取耗时 < 10ms
  │   └─ 前端秒级显示完整报告（无流式效果）
  │
  └─ [缓存未命中] → 运行完整分析链路（graph.ainvoke）
      ├─ 阻塞等待 60-90s（用户无进度反馈）
      ├─ 返回 AnalysisResponse
      └─ 写入 Redis 缓存（TTL 5min）
```

> **当前策略**：前端优先使用流式端点（`/analyze-stream`），仅在首 token 时并行检查缓存。纯 `/analyze` 端点用于 n8n 定时任务调用和缓存回退。

---

## 5. Multi-Agent 分析链路

### 正常流程

```
Supervisor Agent（规划）
  │
  ├─ LLM 分析问题 → 决定激活哪些 Agent
  │   输入："华东区销售为什么下降？"
  │   输出：activated_agents = ["sales", "crm", "finance"]
  │
  ├─ [失败/无结构化输出] → 兜底激活全部 5 个 Agent
  │
  └─ 通过 LangGraph Send 并行扇出 ─────────────────────┐
      │                                                  │
      ├─ Sales Agent（销售分析）                          │
      │   ├─ get_table_schema() → 发现可用表和列          │
      │   ├─ run_sql() → 执行 SQL（自动注入 store_id 过滤）│
      │   └─ 工具调用循环（最多 5 轮）→ 生成分析文本      │
      │                                                  │
      ├─ CRM Agent（会员分析）       ← 并行执行，互不等待 →│
      │   └─ 同上流程                                     │
      │                                                  │
      └─ Finance Agent（财务分析）                        │
          └─ 同上流程                                     │
                                                         │
  Aggregator ←────────────────────────────────────────────┘
  │  聚合各 Agent 结果（Python 纯代码，不消耗 Token）
  │
  Chart Advisor
  │  根据数据特征推荐图表类型（bar/line/pie/scatter/radar）
  │  → 输出 [CHART:type|url_encoded_json] 标记
  │
  Report Agent（流式生成报告）
  │  ├─ 整合分析结果 + 图表标记 + 追问指令
  │  ├─ LLM 流式输出（token by token）
  │  └─ 后处理：编码图表标记、提取 [FOLLOWUP:...]
  │
  Reflection Agent（质量审核）
  │  ├─ 4 维度检查：数据一致性 / 逻辑严谨性 / 建议可操作性 / 问题覆盖完整性
  │  ├─ [通过] → 进入记忆存储
  │  └─ [未通过，重试次数 < 1] → 退回到 Report Agent 重写
  │      └─ [重试次数用尽] → 保存当前结果（不过滤）
  │
  Save Memory
      ├─ pgvector 向量嵌入（1024 维，BGE-M3）
      ├─ 保存完整分析记录到 analysis_history
      └─ 返回 record_id
```

### 异常流程

| 节点 | 异常 | 处理 |
|------|------|------|
| Supervisor | LLM 调用失败 / 无 tool_calls | 兜底激活全部 5 个 Agent |
| 任意 Agent | SQL 语法错误 | 工具返回错误消息，LLM 自行修正（最多 5 轮） |
| 任意 Agent | 工具调用 5 轮后仍有 tool_calls | 强制要求 LLM 生成最终文本 |
| 任意 Agent | SQL 返回超 10 行但 LLM 输出截断 | 检测截断并强制补全 |
| 任意 Agent | 全部异常 | 返回 `agent_errors: [{agent, error, user_message}]` |
| Aggregator | 所有 Agent 返回 None | `aggregator_summary = None` |
| Chart Advisor | FEATURE_CHART=false | 跳过，`chart_suggestions = []` |
| Report Agent | `aggregator_summary` 为空 | 生成 Python 级错误报告 |
| Reflection Agent | LLM 超时 | 超过 30s 视为通过（避免卡死） |
| Save Memory | pgvector 插入失败 | 记录日志，不影响报告返回 |

### 边界情况

| 情况 | 行为 |
|------|------|
| Supervisor 仅激活 1 个 Agent | 该 Agent 独占运行，Aggregator 直接透传 |
| 问题为纯查询（如"Top 3 门店"） | Report Agent 按查询模式只输出表格 + 简短总结（约 400 token） |
| 问题为综合分析 | Report Agent 按报告模式输出完整 4 段结构（约 2000-4000 token） |
| 反思反馈包含中文字符 | 正常注入 Prompt |
| FOLLOWUP 问题含 `]` 字符 | 括号计数法（字符串感知）正确处理 |

---

## 6. 行级数据安全（RLS）

### 正常流程

```
用户发起分析
  │
  ├─ get_user_store_ids(user_id)
  │   ├─ 查询 user_store_access 表
  │   │
  │   ├─ scope_type = "all" → 返回 None（完全不注入过滤条件）
  │   ├─ scope_type = "region" → 查询 store WHERE region = :r
  │   │   └─ 返回该区域所有门店 ID 列表
  │   ├─ scope_type = "store" → 返回指定的门店 ID 列表
  │   └─ 无 Access 记录 → 返回 []（默认拒绝）
  │
  ├─ SQL 注入（inject_store_filter）
  │   ├─ store_ids = None → 不修改 SQL（全量访问）
  │   ├─ store_ids = [1,2,3] → 在最外层 WHERE 注入 `store_id IN (1,2,3)`
  │   └─ store_ids = [] → 注入 `WHERE 1=0`（强制空结果）
  │
  └─ Agent System Prompt 注入
      ├─ store_ids = None → 不限制
      ├─ store_ids = [1,2,3] → 追加"你只能查询以下门店的数据"
      └─ store_ids = [] → 追加"你的账号没有可访问的门店数据"
```

### 边界情况

| 情况 | SQL 示例 | 注入结果 |
|------|---------|---------|
| 简单查询 | `SELECT * FROM orders` | `SELECT * FROM orders WHERE store_id IN (...) ` |
| 已有 WHERE | `SELECT * FROM orders WHERE status='active'` | `WHERE store_id IN (...) AND status='active'` |
| 子查询 | `SELECT ... FROM t1 WHERE x IN (SELECT ... FROM t2 WHERE y=1) AND z=2` | 注入最外层 WHERE（括号深度=0），不影响子查询 |
| member 表 | `SELECT COUNT(*) FROM member` | 不注入（member 无 store_id 列，_detect_store_column 返回 None） |
| 带 JOIN | `SELECT * FROM orders o JOIN store s ON o.store_id=s.id` | 注入 `store_id IN (...)`（检测到 JOIN 则使用默认列名） |

---

## 7. 报告交互（导出 / 反馈 / 历史）

### PDF 导出

```
用户点击「📄 PDF」
  │
  ├─ POST /api/v1/weekly/export { report, title, format: "pdf" }
  │   ├─ 后端 markdown_to_html() → 生成完整 HTML 文档
  │   ├─ WeasyPrint HTML → 渲染为 PDF
  │   └─ [WeasyPrint 未安装] → 返回 501
  │
  ├─ [200] → 浏览器下载 .pdf 文件
  └─ [非 200] → 前端 toast "PDF 服务不可用，已降级为 Markdown 下载"
      └─ 自动调用 downloadMD() 下载 .md 文件
```

### 反馈提交

```
用户点击 👍/👎 → 弹出反馈弹窗
  │
  ├─ 输入反馈原因（可选）
  ├─ POST /api/v1/feedback/submit
  │   └─ { analysis_history_id, rating, reason }
  └─ 提交成功后展示当前平台好评率（V4.5 新增）
  
查看反馈历史：POST /api/v1/feedback/history（V4.5 新增）
  └─ 弹窗展示过往反馈记录列表
```

### 历史记录

```
GET /api/v1/analysis/history
  ├─ 返回最近 20 条（按时间倒序）
  ├─ 每条：问题摘要 + 报告前 300 字
  └─ 点击某条 → GET /api/v1/analysis/history/{id}
      └─ 完整报告 + 各 Agent 中间结果
```

---

## 8. 异常与降级处理

### 系统降级层级

```
Level 1: 全功能正常
  ├─ LLM 可用、DB 可用、Redis 可用、Ollama 可用
  └─ 全部功能正常

Level 2: Redis 不可用
  ├─ 缓存降级：直接查 DB
  ├─ 频控降级：跳过 Redis 频控（框架容错）
  └─ 会话降级：会话上下文丢失（单次分析模式）

Level 3: Ollama 不可用
  ├─ 嵌入向量降级：语义搜索返回空
  ├─ 历史相似分析：跳过 RAG 增强
  └─ 核心分析功能不受影响（LLM 独立运行）

Level 4: LLM API 不可用
  ├─ 全部 Agent 返回错误
  ├─ Report Agent 生成 Python 级错误报告
  └─ 返回 500 + 错误详情

Level 5: DB 不可用
  └─ 所有查询失败 → 500
```

### 超时策略

| 组件 | 超时 | 策略 |
|------|------|------|
| LLM API 连接 | 30s | httpx connect timeout |
| LLM API 整体 | 120s | httpx read timeout |
| SQL 执行 | 30s | SQLAlchemy 默认 |
| SSE 流 | 无上限 | 持续推送直到 done |
| Redis 操作 | 5s | 失败跳过 |
| 反思 Agent 审核 | 30s | 超时视为通过 |

### 重试策略

| 组件 | 重试次数 | 策略 |
|------|---------|------|
| LLM API（瞬时错误） | 2 | OpenAI SDK 内置 |
| SQL（Agent 工具调用） | 最多 5 轮 | LLM 自行修正 SQL |
| 反思 → 报告（未通过） | 1 | 带反馈重写报告 |
| Redis 缓存 | 0 | 失败跳过 |

---

## 9. 边界情况汇总

### 输入边界

| 输入 | 行为 |
|------|------|
| 空问题 | 前端阻止，不发送 |
| 1 个字符 | 正常发送（满足 min_length=1） |
| 2000 个字符 | 正常发送 |
| 2001 个字符 | 前端阻止，不发送 |
| 纯英文问题 | 正常处理 |
| 中英混合 | 正常处理 |
| 含 SQL 关键词的问题（如 "SELECT 门店"） | `_detect_store_column` 可能误判，但注入逻辑有保护 |
| 含 `]` 字符的追问 | FOLLOWUP 提取正确（字符串感知括号计数） |

### 数据边界

| 数据情况 | 行为 |
|------|------|
| 数据库完全为空 | 各 Agent 返回 "(查询结果为空)"，报告如实说明 |
| 单日 0 笔订单 | KPI 显示 ¥0 |
| 全部门店高退款 | 告警触发（退款率 > 10%） |
| 会员数为 0 | 会员 KPI 显示 0 |
| 库存全部为 0 | 库存预警图表为空 |
| 供应商准时率全部 100% | 供应链排名正常显示 |

### 并发与状态

| 场景 | 行为 |
|------|------|
| 分析进行中再次点击提问 | toast "请等待当前分析完成" |
| 分析进行中点击取消 | `AbortController.abort()` → 终止 fetch |
| 分析进行中切换 Tab | 正常（进度面板在 chat 区域，切到看板后隐藏） |
| 分析进行中刷新页面 | 请求中止，回退到恢复会话流程 |
| 同时打开 2 个标签页提问 | 各自独立，共享 DB/Redis |

### 权限边界

| 用户 | 能做什么 | 不能做什么 |
|------|---------|-----------|
| admin | 全部门店、全部区域、管理用户、查看审计日志 | — |
| zhangsan | 华东 22 店分析/看板/历史/周报/预警查看 | 管理用户、查看其他区域数据 |
| lisi | 1 店分析/看板/历史 | 管理用户、查看其他门店数据 |
| 无 Access 记录 | — | 什么都看不到（`WHERE 1=0`） |

---

## 附录：关键 API 速查

| 端点 | 方法 | 认证 | 说明 |
|------|------|------|------|
| `/api/v1/auth/login` | POST | 无 | 登录 |
| `/api/v1/auth/logout` | POST | Bearer | 退出（令牌黑名单） |
| `/api/v1/dashboard/overview` | GET | Bearer | 看板数据 |
| `/api/v1/dashboard/today-summary` | GET | Bearer | 今日快报（轻量） |
| `/api/v1/analysis/analyze` | POST | Bearer | 分析（非流式 + 缓存） |
| `/api/v1/analysis/analyze-stream` | POST | Bearer | 分析（SSE 流式） |
| `/api/v1/analysis/history` | GET | Bearer | 历史记录 |
| `/api/v1/analysis/history/{id}` | GET | Bearer | 历史详情 |
| `/api/v1/dashboard/overview` | GET | Bearer | 看板概览（趋势/区域/排名）|
| `/api/v1/weekly/export` | POST | Bearer | PDF 导出 |
| `/api/v1/alerts/check` | POST | Webhook Secret | 异常检测 |
| `/api/v1/admin/users` | GET/POST | Bearer | 用户管理 CRUD |
| `/api/v1/feedback/history` | POST | Bearer | 反馈历史 |

---

*最后更新：2026-07-30 | V4.5*
