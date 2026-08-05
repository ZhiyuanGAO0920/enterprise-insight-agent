# CHANGELOG — V4 修复与优化记录

## V4.6.2 (2026-08-05)

### 🐛 修复：监控页重试率虚高（统计口径 bug）

| # | 文件 | 修复 |
|---|------|------|
| 1 | `app/api/routes/monitor.py` | 重试率 SQL 把 `report_agent` 和 `reflection_agent` 事件**一起**计入 `report_runs`，而正常会话固定有 2 条事件（report 1 + reflection 1）→ `report_runs>=2` 恒成立 → **所有会话都被误判为"重试过"**，重试率虚高（实测近30天显示 82.9%、上月 100% 均失真）。改为 `COUNT(*) FILTER (WHERE node_name='report_agent')` 只统计 report 事件（真实重试 = reflection 失败后 report_agent 重跑，见 `graph.py` `after_reflection`）；修复后近30天 60.0%、上月 74.1%（数据含测试/每日投喂 demo 会话，偏高属正常） |
| 2 | `app/api/routes/feedback.py` | 反馈三分类口径与提交端两按钮不一致：统计展示 有帮助/不准确/不相关，但前端只提交 `helpful`/`bad`，而 `bad` 不在后端 `^(helpful\|inaccurate\|not_relevant)$` 枚举内 → 点「没有帮助」提交必 422 失败（近一个多月 0 条 bad 入库）。修复：接受 `bad` 并归一化为 `inaccurate` 落库（对齐二分类决策「没有帮助≈不准确」，且不准确数据可驱动 `/analyze` 的 Agent 投诉分析）；历史 31 条 bad 一并 UPDATE 归入不准确 |

## V4.6.1 (2026-08-04)

### 🐛 修复：SSE 流式分析超时误杀（心跳保活）

| # | 文件 | 修复 |
|---|------|------|
| 1 | `app/api/routes/analysis.py` | SSE 流加心跳保活：节点内部非流式 LLM 调用期间（实测单步 40-75s）无任何事件推送，前端 45s 看门狗会误判连接挂死而 abort（报"分析超时（45 秒无响应）"）。新增 `_with_heartbeat` 每 20s 穿插 `{"type":"heartbeat"}` 事件，graph 结束/异常即终止（心跳从属于主数据流）；实测"整体经营状况分析"全链路 165-246s，修复前必超时，修复后最大静默 20s |
| 2 | `web/src/hooks/useSSE.ts` | 显式忽略 heartbeat 事件（仅用于重置 45s 看门狗，内容无业务意义）；看门狗语义不变，真死连接仍被兜住 |

### 🐛 修复：饼图空白圆环（React 端字段名不匹配）

| # | 文件 | 修复 |
|---|------|------|
| 3 | `web/src/lib/report.ts` | 后端图表契约字段为 `x_data`（下划线），React 版 `extractCharts` 未归一化导致 `config.xData` 为 undefined → pie 的 data 映射空数组 → ECharts 渲染灰色无数据占位环（#cccccc）。对齐原生版 `utils.js` 的 `xData: params.x_data` 转换；解析层修复，**历史报告自动恢复显示**，分享页共用管线同受益 |

### ✨ 优化：图表质量约束（排名类图型/数据量/数值列选择）

| # | 文件 | 优化 |
|---|------|------|
| 4 | `prompts/yaml/chart_advisor.yaml` (v1.1.0) | 硬约束：排名类必须 bar 禁止 pie（原 prompt 仅"推荐 bar"，LLM 常输出 pie）；数据 TOP 10（原 20 条挤爆）；多个数值列时优先业务金额列（销售额/收入/金额，避免选中订单数列） |
| 5 | `app/agents/chart_advisor_agent.py` | 新增 `_sanitize_charts` LLM 输出硬校验（prompt 是软约束）：标题含"排名/排行/TOP/前N"且为 pie → 强制 bar；截断 10 项；x_data/series 残缺丢弃；**占比 pie 不误伤**（判定仅靠标题关键词，占比数据天然递减）。规则兜底 `parse_tables_from_summary`：数值列按关键词优先级选择、排名判定改表头信号（"占比"信号优先于数据递减）、TOP 10、标题按图型语义生成 |

**端到端验证**（真实全链路）：修复前"各门店销售额排名"生成 pie 圆环（20 项/订单数）；修复后 bar 柱状图（TOP 10/销售额（元）），浏览器 canvas 像素验证 97% 单色柱渲染正常。

### 🧹 清理

- 删除误入库的 `.playwright-mcp/` 调试快照（page-*.yml/png/pdf，Playwright MCP 自动产物）

## V4.6.0 (2026-07-31)

### ✨ 报告分享功能（分享链接 + 长图导出）

| # | 文件 | 说明 |
|---|------|------|
| 1 | `alembic/versions/011_add_report_share.py` | 迁移 011：`analysis_history` 新增 `share_token`/`share_expires_at` 列 + 索引 |
| 2 | `app/api/routes/analysis.py` | 新增 3 个分享接口：`POST /analysis/share`（生成链接，30 天有效）、`GET /analysis/share/{token}`（免登录只读）、`DELETE /analysis/share`（取消分享） |
| 3 | `app/api/main.py` | 新增 `GET /share/{token}` 只读分享页路由（免登录，no-cache） |
| 4 | `app/middleware/tenant.py` + `audit.py` | `SKIP_PATHS` 加入 `/share`（分享页免租户/审计中间件） |
| 5 | `app/api/static/share.html` | 新增只读分享页：免登录渲染报告 + 图表，失效/过期提示 |
| 6 | `app/api/static/views.js` | 报告按钮条新增「🔗 分享」「🖼️ 长图」；分享优先调起系统分享（Web Share API，恢复 V4.5 重构丢失的 `navigator.share`），降级打开链接弹窗；长图用 html2canvas 导出 PNG |
| 7 | `app/api/static/html2canvas.min.js` | 新增本地库（1.4.1，零 CDN 惯例） |
| 8 | `app/api/static/index.html` | 新增 `#shareModal` 分享弹窗 + html2canvas 引用；views.js 版本号 bump 至 v4.50 |
| 9 | `tests/phase7/test_report_share.py` | 新增 6 条分享接口测试（生成/免登录查看/失效/取消/跨用户 404） |

### 🐛 功能修复

| # | 文件 | 修复 |
|---|------|------|
| 10 | `app/api/static/views.js` | 修复流式报告路径缺失「📋 复制」按钮（历史回显路径有，V4.5 重构遗漏，现已两处一致） |
| 11 | `app/services/pdf_exporter.py` | 修复 PDF 导出在 Windows 不可用：weasyprint 缺系统库时降级到 reportlab 纯 Python 渲染（自动探测微软雅黑/宋体/Noto CJK 字体，带 ToUnicode 映射，中文可复制搜索；无字体时降级 CID 字体） |
| 12 | `app/api/routes/weekly.py` | 修复 PDF 中文文件名导致 `Content-Disposition` latin-1 编码 500：ASCII 文件名 + RFC 5987 `filename*` 编码 |
| 13 | `pyproject.toml` | `[pdf]` extra 追加 `reportlab>=4.0`（降级方案依赖） |

## V4.5.0 (2026-07-29)

### 🎨 前端架构重构

| # | 文件 | 说明 |
|---|------|------|
| 1 | `app/api/static/views.js` + `utils.js` | 前端全面重构：Tab 导航从 Header 移入侧边栏，账户操作移至 Header 右上角下拉菜单 |
| 2 | `app/api/static/index.html` | 侧边栏 5 导航（看板/对话/历史/监控/系统管理），Header 仅保留品牌+用户菜单 |
| 3 | `app/api/static/style.css` | 新增侧边栏导航样式、用户下拉菜单样式、历史记录卡片样式 |
| 4 | `app/api/static/style.css` | 颜色对比度修复：`--text-muted: #94a3b8` → `#b0c0d5` |

### 🔴 P0 安全与稳定性

| # | 文件 | 修复 |
|---|------|------|
| 5 | `app/api/routes/dashboard.py` | SQL 参数化：全部 10+ 查询从字符串拼接改为绑定参数 `ANY(:store_ids)` |
| 6 | `app/api/main.py` | 修复 catch-all 路由（`/api/{rest_of_path:path}`）与 v1_router 路由匹配冲突，改为中间件 |
| 7 | `app/api/routes/analysis.py` | SSE 流式端点增加 420s 超时保护（`asyncio.timeout`），防 LLM 挂起导致连接泄漏 |

### 🐛 功能修复

| # | 文件 | 修复 |
|---|------|------|
| 8 | `app/api/static/views.js` | 修复 `showEditUser` 保存按钮（`window[onSave]()` 传参错误导致回调不执行） |
| 9 | `app/api/static/views.js` | 修复反馈历史弹窗关闭按钮（`ov.id` 未赋值导致 `cfh()` 找不到元素） |
| 10 | `app/api/static/views.js` | 修复 ECharts `var(--semantic-error)` CSS 变量在 Canvas 渐变中不生效（改为 `#ef4444`） |
| 11 | `app/api/static/views.js` | 修复 `[FOLLOWUP:]` 标记未从报告文本中剥离（缺少正则替换步骤） |
| 12 | `app/api/static/style.css` | 看板页面添加 `overflow-y:auto`，修复门店 Top 10 被视口裁剪 |
| 13 | `app/api/routes/dashboard.py` | 修复退款率 SQL：PostgreSQL `ROUND(double,1)` 不支持（改为 `CAST(... AS numeric(10,1))`） |

### 📊 产品功能新增

| # | 文件 | 说明 |
|---|------|------|
| 14 | `app/api/routes/feedback.py` + `views.js` | 反馈闭环：提交反馈后展示平台好评率，新增 `GET /feedback/history` 端点 |
| 15 | `app/api/static/views.js` | Supervisor 推理过程展示面板：折叠展示激活的 Agent 和推理原因 |
| 16 | `app/api/static/views.js` | 数据来源追溯面板恢复展示（原被 `traceHtml=''` 硬编码隐藏） |
| 17 | `app/api/static/views.js` | KPI 数字递增动画（从 0 到目标值 easeOut） |
| 18 | `app/api/static/views.js` | Dashboard 数据时效指示器（"数据更新于 HH:mm"） |
| 19 | `app/api/static/views.js` | 首次使用引导 toast |
| 20 | `app/api/routes/dashboard.py` + `views.js` | 退款率 Top 10 图表：替换冗余的门店排名表格 |
| 21 | `app/api/static/style.css` | 质量监控错误列表新增表头 + 行列间距优化（`gap:8px`→`14px`） |
| 22 | `app/api/static/views.js` | 流式报告工具栏补全（复制/打印/MD/PDF 按钮） |
| 23 | `app/agents/report_agent.py` | 修复报告重试时追问指令被跳过（`not state.get("reflection_feedback")` 条件移除） |

### 🧹 Prompt 优化

| # | 文件 | 说明 |
|---|------|------|
| 24 | `prompts/report_prompt.py` | 新增对比表格结构规则：禁止行列展示同一维度，行=主体、列=指标 |

### 📐 设计优化

| # | 说明 |
|---|------|
| 25 | 侧边栏精简：移除底部账户操作、"大模型"信息，释放垂直空间 |
| 26 | Dashboard 空状态增强：🤖 图标 + 功能描述文案 |
| 27 | 历史记录页面重设计：卡片布局 + 搜索 + 分页 + 状态徽标 |
| 28 | 图表标题统一标注时间范围（近30天/近7天） |
| 29 | 图表左边界从 80px 扩至 110px，适配长门店名 |

## V4.2.0 (2026-07-27)

### 🆕 报告质量升级

| # | 模块 | 说明 |
|---|------|------|
| 1 | `prompts/report_prompt.py` + `prompts/yaml/report.yaml` | 报告 Prompt 升级为"数据→洞察→根因→建议"四段式方法论，增加头部集中度分析、分布特征、异常标记、量化行动建议 |
| 2 | `prompts/reflection_prompt.py` + `prompts/yaml/reflection.yaml` | Reflection 质检区分"数据查询型"与"综合分析型"报告标准，移除过严的"责任部门/预期执行时间"要求 |
| 3 | `app/agents/report_agent.py` | 新增最终报告表格解析兜底：扫描 Markdown 表格自动注入 `[CHART:]` 图表标签，LLM 未生成图表时自动补充 |
| 4 | `app/agents/chart_advisor_agent.py` | 新增 `_parse_tables_from_summary` 规则兜底函数，从聚合摘要中解析 Markdown 表格生成图表配置 |
| 5 | `app/agents/reflection_agent.py` | `MAX_REPORT_CHARS` 10000→18000，适配更长报告；`MAX_SUMMARY_CHARS` 5000→8000 |
| 6 | `app/api/routes/analysis.py` | AnalysisResponse 增加 `reflection_feedback` 字段，暴露质检反馈详情 |

### 🔴 安全修复

| # | 文件 | 修复 |
|---|------|------|
| 7 | `app/api/static/views.js` | XSS 修复：`deleteUser()`/`impersonateUser()` onclick 中 `esc()`→`jsEscape()` |
| 8 | 5 个领域 Agent | Prompt 注入防护：用户问题包裹在 `## 📋 用户问题\n\n{question}\n\n请按角色指令严格分析...` 模板中 |
| 9 | `app/tools/question_enhancer.py` | 移除 `[系统指令]` 标记防越狱，改为自然语气附加说明 |

### 🐛 功能 Bug 修复

| # | 文件 | 修复 |
|---|------|------|
| 10 | `app/api/static/style.css` | `#storeCheckboxes` 移除 `display:none`，管理员门店选择功能恢复正常 |
| 11 | `app/api/static/views.js` | `showLogin()` 直接显示登录弹窗而非欢迎页 |
| 12 | `app/api/static/index.html` | 测试账号密码提示逐用户标注（admin/admin123, zhangsan/123456, lisi/123456） |
| 13 | `app/api/static/views.js` | 看板合并 `loadDashboardOverview` 到 `loadDashboard`，消除重复 API 请求 |
| 14 | `app/api/static/views.js` | 切回分析标签页仅聊天区为空时显示 emptyState |
| 15 | `app/api/static/index.html` | 移除不存在的 `regional_director` 角色筛选选项 |
| 16 | `app/auth/rbac.py` | 系统用户 ID=0 返回 `None`（全部门店权限），修复周报定时任务无数据问题 |
| 17 | `app/api/static/views.js` | 用户消息正确右对齐（`.msg.user{text-align:right}`） |

### 🛠️ 稳定性与性能

| # | 文件 | 修复 |
|---|------|------|
| 18 | `app/database/redis.py` | 速率限制 TOCTOU 竞态修复：`zremrangebyscore+zcard+zadd` 改为 Redis Lua 脚本原子操作 |
| 19 | `app/middleware/audit.py` | 审计日志写入改为 `asyncio.create_task` 后台异步执行，不阻塞请求响应 |
| 20 | `app/apm/tracer.py` | APM tracer 全局变量改为 `contextvars.ContextVar`，消除并发竞态 |
| 21 | `app/tools/memory.py` | `save_analysis_history` 3 个独立 DB 会话合并为 1 个，降低连接池压力 |
| 22 | `app/tools/sql_runner.py` | RLS 表名检测和 LIMIT 替换改用 `sqlparse` AST 解析替代正则，正确跳过 CTE/子查询 |
| 23 | `app/api/main.py` + `app/tools/embedding.py` | 添加 `shutdown` 事件：关闭 httpx 连接池，防止服务重启连接泄漏 |
| 24 | `docker-compose.yml` / `.shared.yml` | 添加 `extra_hosts: host.docker.internal:host-gateway`，Linux 兼容 |
| 25 | `docker-compose.yml` | n8n 添加 `depends_on: app`，消除启动竞态 |

### 🧹 代码质量

| # | 文件 | 修复 |
|---|------|------|
| 26 | `app/agents/*.py`（9 个文件）| 统一 `logging.getLogger()` → `get_logger()`，Agent 日志注入 trace_id 全链路追踪 |
| 27 | `app/tools/stream_utils.py` | 新增 `safe_get_stream_writer()` 包装函数，单元测试中 LangGraph 上下文外返回 noop 降级 |
| 28 | `app/agents/supervisor_agent.py` | `__import__('re')`/`__import__('json')` 改为顶部正常 `import` |
| 29 | `app/api/static/chat.js` + `auth.js` | 删除死代码文件（未被 index.html 加载，含与 views.js 冲突的旧版本实现） |
| 30 | `docker-compose.yml` / `.shared.yml` | 移除已弃用 `version: '3.8'` 字段 |
| 31 | `pyproject.toml` | LangGraph/LangChain/OpenAI 依赖收紧上限（`<0.3.0` / `<2.0.0`） |
| 32 | `Dockerfile` | builder→production 阶段复用编译产物（`COPY --from=builder`），减少构建时间 |
| 33 | `pyproject.toml` | 添加 `sqlparse>=0.5.0` 依赖 |

### 🧪 测试

| # | 说明 |
|---|------|
| 34 | `tests/test_sql_checker.py` 新增 11 个 RLS 表名检测和注入测试（含 CTE/子查询/空门店降级/ORDER BY 场景） |
| 35 | `tests/conftest.py` 异步引擎清理 + TestClient 关闭，减少 Windows asyncpg 事件循环残留 |
| 36 | `tests/test_v3_features.py` 修复 2 个 `get_stream_writer` LangGraph 上下文外调用崩溃 |

### 🐳 部署

| # | 文件 | 修复 |
|---|------|------|
| 37 | `docker-compose.prod.yml` | Docker Secrets 机制修复：entrypoint 从 `/run/secrets/` 读取密钥并注入环境变量 |
| 38 | `重启服务.bat` / `启动V4服务.bat` | `taskkill /F /IM python.exe` → `netstat` 定位 + `taskkill /F /PID` 精确杀端口 |
| 39 | `deploy.bat` | 添加 `setlocal enabledelayedexpansion`，修复 `!ERRORLEVEL!` 健康检查条件 |
| 40 | `scripts/enrich_demo_data.py` / `daily_demo_feed.py` / `seed_monitor_data.py` | 硬编码 `localhost:15432` → 从 `DATABASE_URL` 环境变量读取（默认 5434） |
| 41 | `scripts/enable_wake.ps1` | 添加 try-catch 错误处理 |

## V4.1.0 (2026-07-16)

### 🆕 新功能

| # | 模块 | 说明 |
|---|------|------|
| 1 | `app/api/static/` — 质量监控面板 | 第三 Tab「📋 质量监控」全屏展示 5 大核心指标（Reflection 通过率、P50 延迟、好评率、日均/月均成本、离线评估通过率）+ Agent 错误率排行 + 每日分析趋势图 + 错误详情列表 + 导航锚点 |
| 2 | `app/llm.py` — 真实成本追踪 | CostTracker 改用 `ContextVar` 做 per-task 累计，分析完成后写入 `analysis_history.llm_cost`，监控面板展示真实 Token 消耗而非 ¥0.04 固定值 |
| 3 | `tests/eval_set.json` — 评估测试集扩充 | 测试集从 20 条扩充至 102 条（50 lookup + 38 analysis + 14 edge），覆盖全部 5 个领域 Agent |
| 4 | `app/api/routes/monitor.py` — 失败原因分布 | 新增 `reflection_issue_dist` 按 `consistency/logic/actionability/completeness` 四维度统计 Reflection 失败原因 |
| 5 | `tests/run_eval.py` — 评估脚本增强 | 支持并发执行（`--parallel`）、基线对比（`--compare`）、自动同步结果到监控面板 |

### 🔴 严重修复

| # | 文件 | 修复 |
|---|------|------|
| 1 | `app/api/routes/monitor.py` | SQL 注入加固：`_time_filter.col` 参数加入白名单 `_ALLOWED_TIME_COLS` |
| 2 | `app/api/routes/monitor.py` | `:days::INTERVAL` 语法与 SQLAlchemy 参数解析冲突 → 改为 `(:d || ' days')::INTERVAL` |
| 3 | `app/api/routes/monitor.py` | 列名不一致：`analysis_history` 用 `create_time`，`agent_trace_events` 用 `created_at` → 分表指定列名 |

### 🟠 高优先级修复

| # | 文件 | 修复 |
|---|------|------|
| 4 | `app/api/static/app.js` | `dailyAvg` 变量使用在定义之前 → JS hoisting 导致 `undefined` |
| 5 | `app/api/static/app.js` | 导航锚点用 `href="#id"` 无法滚动 `overflow-y:auto` 容器 → 改为 `scrollIntoView()` |
| 6 | `app/api/routes/monitor.py` | `start_date` 字符串传给 asyncpg 报类型错误 → 改为 Python `date` 对象 |
| 7 | `app/api/routes/monitor.py` | `_calc_period_days` 中多余 `col` 检查导致 NameError → 清理 |
| 8 | `app/api/static/app.js` | `newSession()` 不切 Tab → 末尾加 `switchTab('chat')` |

### 🟢 低优先级

| # | 文件 | 说明 |
|---|------|------|
| 9 | `app/api/static/style.css` | Toast 提示从 `right:16px` 改为 `left:50%` 居中显示 |

## V4.0.0 (2026-06-11)

### 🔴 严重修复 (6)

| # | 文件 | 修复 |
|---|------|------|
| 1 | `app/config.py` + `app/logging_config.py` | 添加 `log_format` 字段，JSON 日志恢复可用 |
| 2 | `app/agents/reflection_agent.py` | `reflection_retries` 正确递增，修复无限递归循环 |
| 3 | `app/api/routes/analysis.py` | 流式端点改为 `stream_mode=["updates","values"]` 单次图执行，LLM token 消耗减半 |
| 4 | `app/api/routes/session.py` + `app/tools/context_manager.py` | 添加 `get_session_user_id()` + 会话所有权验证 |
| 5 | `app/auth/rbac.py` | `build_store_filter_sql` 添加单引号 SQL 转义 + `store_column` 白名单 |
| 6 | `app/tools/memory.py` | `save_analysis_history` 自动填充 `tenant_id`（修复 NOT NULL 约束违反） |

### 🟠 高优先级修复 (12)

| # | 文件 | 修复 |
|---|------|------|
| 7 | `app/middleware/audit.py` | 改为纯 ASGI 中间件 + FastAPI `@app.middleware("http")`；JWT 解析 `user_id` + 读取 `request.state.tenant_id` |
| 8 | `app/agents/sales_agent.py` | 三元运算符 `final = ... if retry.content else ""` 改为 `if` 语句 |
| 9 | `app/api/routes/feedback.py` | `CROSS JOIN LATERAL` → `LEFT JOIN LATERAL` 修复空 `agent_issues` 丢弃记录 |
| 10 | `app/config.py` + `app/api/routes/weekly.py` | 添加 `system_user_id`，周报使用系统用户 |
| 11 | `app/agents/chart_advisor_agent.py` | 正则提取 JSON，处理代码块末尾额外文本 |
| 12 | `app/tools/sql_checker.py` | 预处理 PostgreSQL `''` 转义，避免误报 |
| 13 | `app/agents/supervisor_agent.py` | `state["question"]` → `state.get("question", "")` 防 KeyError |
| 14 | `app/agents/report_agent.py` | `encode_chart_markers` 遇 LLM 畸形标记不崩溃 |
| 15 | 5 个领域 Agent | 工具循环耗尽后追加最终 LLM 调用；`inventory`/`supply_chain` 添加多轮上下文 + RAG |
| 16 | `app/services/pdf_exporter.py` | `<tr>` 行用 `<table>` 包裹 + `<th>` 表头 + 按 `|` 分割多列 |
| 17 | `app/tools/sql_runner.py` | RLS 注入匹配最后一个（最外层）WHERE；移除冗余 `import re`；返回类型改为 `Optional[str]` |
| 18 | `app/tools/embedding.py` | 添加 try/except 降级零向量 + 未知 provider 明确报错 |

### 🟡 中等优先级修复 (24)

| # | 文件 | 修复 |
|---|------|------|
| 19 | `app/api/dependencies.py` | IP 限流 key 改用 `hashlib.md5` |
| 20 | `app/auth/jwt.py` | 保留时区感知 datetime；移除 `timezone` 冗余导入；JWT 嵌入 `tenant_id` |
| 21 | `app/database/models.py` | `EmployeePerformance` 添加 `UniqueConstraint` |
| 22 | `app/database/connection.py` | 类型标注 `AsyncEngine` / `async_sessionmaker[AsyncSession]` |
| 23 | `app/auth/rbac.py` | 空 `UserStoreAccess` 默认行为文档化 |
| 24 | `app/api/routes/admin.py` | `update_user` 验证 `scope_type="store"/"region"` 参数；`delete_user` 先检查用户存在；`test_connection` 权限改为 `user:manage`；移除多余 `await` |
| 25 | `app/api/routes/feedback.py` | `submit_feedback` feature-gate 改为一致返回格式 |
| 26 | `app/api/routes/alerts.py` + `weekly.py` | `authorization` 类型标注 `str \| None` |
| 27 | `app/tools/context_manager.py` | `其` 代词匹配增加负向前瞻排除复合词 |
| 28 | `app/adapters/schema_mapping.py` | YAML `columns: null` 时使用 `or {}` |
| 29 | `app/api/routes/analysis.py` | 分析端点添加会话所有权验证；私有 API 重命名为公共 API |
| 30 | `app/agents/report_agent.py` | `_build_*` / `_encode_*` 函数提升为公共 API |
| 31 | `app/api/static/app.js` | 7 项 XSS/UX 修复（见前端修复清单） |
| 32 | `app/middleware/tenant.py` | 注释说明死代码路径的实际执行流 |
| 33 | `app/services/notification.py` | `get_event_loop()` → `get_running_loop()` |
| 34 | `app/apm/tracer.py` | `hash()` → `hashlib.md5` |

### 🔵 低优先级修复 (12)

| # | 文件 | 修复 |
|---|------|------|
| 35 | `app/api/main.py` | 旧版重定向检测 `v1/` 前缀防双写；`HTTPException` handler 处理非字符串 detail；`mkdir` 包 try/except |
| 36 | `app/api/routes/admin.py` | POST 端点 `question` 参数说明 |
| 37 | `app/tools/sql_runner.py` | 移除冗余 `re.IGNORECASE`（sql已 upper） |
| 38 | `app/agents/report_agent.py` | 错误报告中移除硬编码 DeepSeek URL |
| 39 | 多处 | 日志规范化（结构化日志 + 统一 logger） |
| 40 | `app/agents/__init__.py` | 补充 `inventory_agent_node` / `supply_chain_agent_node` 导出 |

### 🧪 测试基础设施 (8)

| # | 修复 |
|---|------|
| 41 | `tests/conftest.py` — 添加 `Base.metadata.create_all()` 自动创建 SQLite 表 |
| 42 | `tests/conftest.py` — `_use_test_db` 禁用 `FEATURE_MULTI_TURN` + `cache_clear()` |
| 43 | 12 个测试用例 — `asyncio.run()` → `@pytest.mark.asyncio` + `await` |
| 44 | 8 个测试用例 — V3→V4 路由前缀 / 状态字段 / feature flag 默认值更新 |
| 45 | 5 个测试用例 — chart 函数名引用更新 (`_build_*` → `build_*`) |
| 46 | `tests/test_prompt_loader.py` — 适配 V4 默认 feature flag |
| 47 | `tests/test_v3_features.py` — APM tracer 测试适配 V4 默认值 |
| 48 | 测试结果：**115 passed / 0 failed / 22 skipped** |

### 🗄️ 数据库迁移

| # | 迁移 | 内容 |
|---|------|------|
| 49 | `005_audit_log.py` | 创建 `audit_log` 表 |
| 50 | `006_multi_tenant.py` | 创建 `tenants` 表 + `users`/`analysis_history` 添加 `tenant_id` |
| 51 | `007_fix_constraints.py` 🆕 | 回填 `analysis_history.tenant_id` + FK 约束 + `audit_log.action` 扩容 + NOT NULL |

### 🖥️ 前端修复清单 (app.js)

| # | 修复 |
|---|------|
| 52 | `marked.parse()` 添加 HTML 转义防止 XSS |
| 53 | onclick 处理器改用 `jsEscape()` 防注入 |
| 54 | 复制/分享改为使用原始文本（非转义后） |
| 55 | `status.innerHTML` → `textContent` |
| 56 | 管理员按钮仅对 admin 用户显示 |
| 57 | `ask()` 添加 `_isAnalyzing` 重入保护 |
| 58 | 流式请求前检查 `resp.ok` |
| 59 | 反馈按钮调用 `showFeedback()` 而非错误的 `submitFeedback()` |
| 60 | `lastRecordId` 在流式响应中正确赋值 |

---

## 配置迁移 (V3 → V4)

`.env` 中需更新：

| 配置项 | V3 值 | V4 值 |
|--------|-------|-------|
| `LOG_FORMAT` | 无 | `console`（新增） |
| `SYSTEM_USER_ID` | 无 | `0`（新增） |
| `SERVER_PORT` | `8001` | `8002` |
| `JWT_SECRET_KEY` | V3 密钥 | 沿用 V3 密钥 |
| `DATABASE_URL` | V3 连接 | 沿用 V3 连接（共享数据库） |

数据库迁移：`alembic upgrade head`（新增 3 个迁移文件）
