# EIA V4 任务清单

> **单一事实源**：本文件是项目唯一任务清单（当前任务 + 历史归档）。开工前先读本文件，不依赖对话记忆。任务完成必须从"当前任务"移到"历史归档"并附验证数据与 commit。TASKS.md 变更随代码一起提交。

## 使用规则

1. **开工前**：读"当前任务"区，确认本次会话涉及的任务编号与边界；不在清单内的改动先登记再动手。
2. **任务五字段**：每个任务必须写明 目标 / 状态 / 修改范围 / 停止条件 / 验证数据。
3. **停止条件（防 Token 浪费）**：同一问题**连续 2 次修改后验证仍失败 → 立即停止**，在该任务下记录失败原因与尝试，不继续硬扛；涉及架构权衡的先与用户确认方案再动手。
4. **验证数据**：禁止用"已完成"代替验证——必须给出测试用例 / 断言 / 实测结果。
5. **归档**：完成的任务附验证结果与 commit hash 移入归档区，记录日期。

---

## 当前任务（按优先级）

### T-01 🔴 H3 会员 PII 越权：Member 表补租户/门店维度

- **目标**：Member 表增加租户/门店维度并纳入 RLS，任何登录用户不可查询其他租户会员手机号
- **状态**：待办（需 schema 迁移 + 数据回填，改动面大）
- **修改范围**：`app/database/models` + alembic 迁移 + RLS 策略 + `scripts/seed_data.py`。**禁止动** `app/tools/sql_runner.py`（注入器刚重写过）
- **停止条件**：迁移方案（加列 vs 拆表 vs 弱化展示）先与用户确认；连续 2 次失败停止记录
- **验证数据**：新增 pytest——租户 A 用户查会员返回 0 行/仅本租户；SQL 注入测试样本复核

### T-02 🔴 M4 向量检索跨租户隔离

- **目标**：`users.tenant_id` 非空约束（或默认租户回填），NULL 用户检索被拒而非跨租户命中
- **状态**：待办（需数据迁移 + 孤儿用户处理策略）
- **修改范围**：alembic 迁移 + `app/tools/memory.py` 检索前置校验 + 回填脚本。**禁止动** 向量索引与 Embedding 链路
- **停止条件**：孤儿用户回填策略先确认；连续 2 次失败停止记录
- **验证数据**：构造 NULL tenant_id 用户 → 检索报错且不返回跨租户结果；memory 相关单测回归

### T-03 ✅ 完成 P0 PII 脱敏（个保法合规）— 2026-08-12

- **目标**：报告输出与审计日志对手机号等脱敏（`138****8000`），数据库原样存储。与 T-01 相关联但独立：T-01 管访问控制，本项管输出脱敏
- **状态**：✅ 已完成并归档（见下方"历史归档"）
- **修改范围**：`app/services/masker.py`（新建）+ `app/tools/sql_runner.py`（run_sql 结果出口）+ `app/middleware/audit.py`（query_params）。**禁止动** 数据层与 SQL 生成
- **停止条件**：若脱敏点超 20 处，先出分层方案（输出层统一 vs 逐点）；连续 2 次失败停止记录
- **验证数据**：见"历史归档"T-03 条目

### T-04 🟡 P0 成本硬限额

- **目标**：单次分析 Token 上限（超限降级/截断）+ 租户月限额 + 超限预警（复用通知链路）
- **状态**：待办
- **修改范围**：`app/workflow/state.py`（Token 计数）+ `app/workflow/graph.py` + `services/notification.py` + 配置项。**禁止动** LLM 调用层封装
- **停止条件**：限额策略（截断 vs 拒绝 vs 降级简单模式）先确认；连续 2 次失败停止记录
- **验证数据**：压测触发超限 → 返回降级提示 + 预警通知发出；限额逻辑单测

### T-05 🟡 M3 Token 计数器跨请求竞态

- **目标**：全局 Token 计数器收进 AnalysisState（请求级），消除跨请求竞争
- **状态**：待办（改动小）
- **修改范围**：`app/workflow/state.py` + 引用全局计数器的 agent 节点
- **停止条件**：连续 2 次失败停止记录
- **验证数据**：`load_test_concurrency.py` 并发 2 请求计数不串；单测

### T-06 🟡 M8 并发同题 in-flight 锁

- **目标**：缓存击穿防护——并发同问题仅 1 次打 LLM，其余等待/复用
- **状态**：待办
- **修改范围**：`app/api/routes/analysis.py` / `app/tools/memory.py` 检索处加 SETNX 租约。**禁止动** 缓存读取链路
- **停止条件**：连续 2 次失败停止记录
- **验证数据**：并发同题 2 请求，日志仅 1 次 LLM 调用；load_test

### T-07 🟡 M11 评估参数权限控制

- **目标**：`skip_reflection` / `bypass_cache` 仅专用评估 token 可传；**金丝雀闭环不受影响**
- **状态**：待办
- **修改范围**：`app/api/routes/analysis.py` 参数校验 + auth 新权限。改前先确认 n8n 金丝雀工作流使用的 token
- **停止条件**：金丝雀工作流兼容性先验证，破坏金丝雀即回滚；连续 2 次失败停止记录
- **验证数据**：普通 token 传参被拒；金丝雀 token 正常跑分；n8n 工作流实测

### T-08 🟡 M10 CSP / 安全头

- **目标**：全站加 CSP + X-Frame-Options 等安全头，且不破坏现有内联脚本
- **状态**：待办（风险：ECharts/内联 onclick 兼容）
- **修改范围**：`app/api/main.py` 中间件 + 前端内联脚本改造（外链或 nonce）
- **停止条件**：若内联改造影响页面功能，先出兼容方案；连续 2 次失败停止记录
- **验证数据**：Playwright 走通核心流程 + curl 验证安全头存在

### T-09 🟡 P1 Reflection 维度重构

- **目标**：质检维度与用户满意度挂钩——可操作性维度占比显著提升（当前 4%），修正"passed 28% vs failed 25% 不准确率"问题
- **状态**：待办
- **修改范围**：`app/agents/reflection_agent.py` + `prompts/yaml` + `tests/eval_set.json` 标注。**禁止动** 报告生成主链路
- **停止条件**：先用现有 eval 数据做相关性分析再改维度权重；连续 2 次失败停止记录
- **验证数据**：eval 重构前后对比 + 金丝雀 16 条子集对比；满意度相关性指标

### T-12 ✅ 完成 P1 应用内金丝雀定时兜底（每日 09:30 幂等触发）— 2026-08-13

- **目标**：金丝雀每日跑分不依赖 n8n（n8n 2.23 对 CLI 导入工作流的 cron 注册异常，6 次定时验证失败）。服务启动时注册 asyncio 定时任务：每天 09:30 检查 eval_runs 当天是否已有 canary 记录——没有则子进程跑 `run_eval --canary --save-db`，已有则跳过（与 n8n 触发幂等，n8n 修好后双保险）
- **状态**：✅ 已完成并归档（见"历史归档"）
- **修改范围**：新建 `app/scheduler.py` + `app/api/main.py` startup 注册（含 shutdown 取消）+ `app/config.py` 加 canary_hour/canary_minute + `tests/test_canary_scheduler.py`。**禁止动** `tests/run_eval.py`、`eval_metrics.py`、`app/api/routes/eval.py`
- **停止条件**：幂等判断在真实库上验证失败连续 2 次停止；连续 2 次失败停止记录
- **验证数据**：见"历史归档"T-12 条目

### T-11 ✅ 完成 P1 金丝雀监控面板（前端展示 eval_runs）— 2026-08-12

- **目标**：监控页加"金丝雀漂移"面板——最近 10 次跑分趋势线（通过率/覆盖率/延迟）+ drift 状态徽章 + 最新摘要。金丝雀数据此前仅 API/文件可看，前端零展示
- **状态**：✅ 已完成并归档（见"历史归档"）
- **修改范围**：`app/api/static/views.js`（监控页新增独立板块 + loadCanary 函数，局部降级：失败不影响主监控页）。**禁止动** `tests/run_eval.py` 评估引擎、`app/api/routes/eval.py` 端点、`eval_metrics.py` 指标口径、监控页现有板块逻辑
- **停止条件**：若面板改动影响现有监控页渲染（30s 缓存/序号竞态），先回退；连续 2 次失败停止记录
- **验证数据**：见"历史归档"T-11 条目

### T-10 🟡 P1 RAG SQL 存储修复

- **目标**：`analysis_history` 落 `data_sources` 字段，`search_similar_sql` 恢复可用（当前命中率 0%）
- **状态**：待办
- **修改范围**：`app/database/models` + `save_analysis_history` + `app/tools/memory.py` 检索。**禁止动** SQL 生成链路
- **停止条件**：连续 2 次失败停止记录
- **验证数据**：执行一次分析后查 history 有 data_sources；相似 SQL 检索命中 > 0

### D-02 🟡 文档：2026 RAG 知识库升级（手册入库 + 三件套 RAG 2026 化）— 2026-08-21

- **目标**：响应第三方评估"EIA 还在 2024 基础 RAG"——将《AI产品经理核心知识手册》复制进 docs/ 作为新源，三件套补 2026 RAG 前沿（Agentic RAG / Hybrid + Reranker / GraphRAG / Context Engineering）。只改文档不动代码
- **状态**：待办
- **修改范围**：🆕 `docs/AI产品经理核心知识手册_v1.1.md`（以 Obsidian 侧 2026-08 版为基底，避免内容回退）；手册补 2.8 节 + 目录/术语表/版本说明（v1.1→v1.2）；`docs/AI产品经理面试作战包.md`「什么是 RAG」「如何设计 RAG」两题话术升级；`docs/作品集-EIA-V4.md` 第 4 章"为何不用 GraphRAG"决策 + 第 10 章甄别框架条目；`CLAUDE.md` 同步规则补手册镜像位置。**禁止动**代码、`.gitignore`（编码隐患另立任务）
- **停止条件**：Obsidian 覆盖后 diff 非 0 差异时停止并核对基底；2.8 锚点在 Obsidian 渲染跳转失败时停止；连续 2 次失败停止记录
- **验证数据**：三件套 md060 通过（新增内容部分）；Obsidian 备份 `D:\Obsidian备份\2026-08-21-GZY备份\` 后覆盖手册 + 作战包，diff 0 差异；git 提交 `docs: D-02 2026 RAG 知识库升级`；作品集 PDF/HTML 手工导出列入遗留

---

## 暂缓区（已确认暂缓，不做）

- 前端低优先级优化（边际收益递减）：长函数拆分、var→const、Design Token 清理、CSS @media 合并、骨架屏、ARIA/键盘导航
- Prompt 一键回滚 API（有 YAML + CHANGELOG + 热重载，回滚频次低）
- 测试隔离：`test_v3_features` 与 `test_wechat` 混跑互相污染（各自单独跑全过）

---

## 历史归档

### D-01 ✅ 文档：V1/V1.5 版本资料整理（2026-08-13 完成）

- **背景**：用户需确认最初 V1 版本所在目录与资料位置。实勘定位：V1 = `D:\GaoZhiyuan\企业经营分析 Agent`（README 标注 v1.0，2026-05-29，Dify+n8n 低代码方案）；V1.5 = `D:\GaoZhiyuan\enterprise-agent`（首个代码化 Multi-Agent 流水线，LangGraph 雏形）
- **改动**：`docs/作品集-EIA-V4.md` 第 7 章演进表扩为 5 行（加"实现载体"列，新增 V1.5 行）+ 演进要点 3 条；`docs/AI产品经理面试作战包.md` 讲稿段（711 行）V1 描述校准为"Dify+n8n 低代码验证 → 代码化 → Multi-Agent"
- **验证数据**：
  - 作品集第 7 章：表格 5 列对齐渲染正常，md060 lint 已修
  - 作战包：仅改讲稿 V1 段一处，其余版本叙事（70/158/220/959 行）无需联动
  - Obsidian 镜像：备份至 `D:\Obsidian备份\2026-08-13-GZY备份\`，覆盖后 diff 与 docs 一致（0 差异）
- **遗留**：Obsidian 侧作品集为 PDF（`高志远-AI产品作品集.pdf`），需手工重新导出。~~V2 README "7 个 Agent" vs 作品集 "3 Agent"~~（已解决 2026-08-13：两口径并存——"3 Agent"= Send 并行扇出的领域 Agent 数，"7 Agent"= 全量 LLM Agent 节点含 supervisor/report/reflection/memory；作品集演进要点已补口径说明）

### T-12 ✅ P1 应用内金丝雀定时兜底（2026-08-13 完成）

- **背景**：n8n 2.23 对 CLI 导入工作流的 cron 注册异常（Deregistered 无 Registered，6 次定时触发验证失败）；UI 创建的异常检测工作流 4 次定时成功证明机制正常、问题特定于 CLI 导入工作流
- **实现**：`app/scheduler.py`——`canary_scheduler_loop`（每日 canary_hour:minute，默认 09:30，asyncio 循环）+ `today_canary_ran`（幂等判据：当天 UTC 日期是否有 canary 记录）+ `run_canary_now`（子进程 `run_eval --canary --save-db --parallel 8`，30 分钟超时 kill，失败只记日志不重试）。main.py startup 注册 + shutdown 取消；config 加 canary_hour/canary_minute
- **踩坑**：REPO_ROOT 用 parents[2] 数深一层 → 子进程找不到 run_eval.py（exit 2）→ 修正 parents[1]
- **验证数据**：
  - `tests/test_canary_scheduler.py` 3 条全过（无记录→False/插记录→True/昨日不误判）
  - 启动日志确认："金丝雀定时任务已注册（每日 09:30，幂等）" + "金丝雀定时任务启动"
  - 手动 `run_canary_now()` 完整跑通并落库（见 T-12 收尾 commit）
  - 全量回归 208+ passed
- **与 n8n 关系**：金丝雀不再依赖 n8n（双保险：n8n 修好后触发了也会被幂等判断跳过）；n8n 继续承担异常检测/周报调度（各自独立工作流，本次未动）

### T-11 ✅ P1 金丝雀监控面板（2026-08-12 完成）

- **方案**：前端独立板块（不动后端评估引擎——`GET /eval/runs` 已存在）。独立异步加载 + 序号防竞态 + 失败降级为空态引导，不影响主监控页 30s 缓存逻辑
- **实现（双版本）**：
  - 原生版 `views.js`：renderMonitorView 末尾插入 `mqCanary` 板块 + loadCanary/renderCanary 两函数
  - React 版 `Monitor.tsx`：独立 useEffect 加载 + 状态行 + ReactECharts 三系列趋势线
  - 共同内容：最新状态行（drift 徽章/model_version/通过率/覆盖率/延迟/时间）+ drift_summary 告警文案 + 三系列趋势线（通过率/覆盖率左轴 %、延迟右轴 ms）+ drift 红 pin 标记
- **量纲处理**：pass_rate 已是 0-100；dimension_coverage 是 0-1 需 ×100；avg_latency_ms 毫秒走 fmtSec
- **验证数据**（Playwright 浏览器实测，8002 + 5173 dev server）：
  - 两版单条数据：✅ 稳定徽章 + 通过率 62.5% / 覆盖率 86.7% / 延迟 67.38s 全部正确
  - 两版临时插入 drift=True 记录（验证后已删除）：⚠️ 漂移告警徽章 + 摘要文案 + 趋势图三系列渲染 + markPoint 红 pin 位置正确
  - JS 语法 node --check + tsc --noEmit 通过；全量回归 208 passed（与基线一致）
- **⚠️ 排查修复（本任务附带发现）**：`GET /eval/runs` 原权限 `user:manage` 过严——React 版监控页对 regional_director 可见（AppLayout adminOnly 放行 admin+regional_director），而 director 无 user:manage → 打开监控页触发 401 → client interceptor 清登录态强制登出。**已改为 `alert:view`**（与 monitor 页其他端点一致），验证：admin 200 / regional_manager（zhangsan）200 / 无权限角色被拒。8002 无 --reload，重启后生效
- **⚠️ 原生版可见性对齐（同日完成）**：原生版监控菜单原 `adminOnly`，已对齐 React 版（admin + regional_director）。过程中发现并修复更深的问题——原生版角色信息依赖 `/admin/users`（需 user:manage），director 访问 401 导致菜单永不显示：改为登录响应 `role` 驱动（localStorage `eia_role`），`/admin/users` 仅作 scope 补充。另补 regional_director 角色中文名（下拉/用户管理 badge 均显示"区域总监"）。**bump views.js v4.55→v4.56**（static 改版必须 bump，浏览器缓存坑）。验证：director_huadong 登录 → 监控菜单可见 → 监控页 + 金丝雀面板正常，不再被 401 踢出
- **注意**：eval_runs 目前仅 1 条真实记录（2026-08-10），趋势图需 ≥2 条才显示——n8n 每日跑分持续积累后自然出现

- **方案**：集中式 2 拦截点——`sql_runner.run_sql` 结果格式化处（写 Redis 缓存**前**，缓存命中路径同安全）+ 审计中间件 query_params。报告/表格/图表全部下游因 LLM 上下文无明文而天然安全，无需逐点处理
- **实现**：新建 `app/services/masker.py`（手机号正则 `(?<!\d)(1[3-9]\d)(\d{4})(\d{4})(?!\d)`，前 3 后 4 保留；数字边界防误伤；带分隔符变体）。仅改 sql_runner 输出段与审计日志，**未动**注入器/数据层/SQL 生成
- **验证数据**：
  - `tests/test_masker.py` 18 条全过（标准/变体/边界不误伤/管道表格/query_params）
  - 真实 PG 执行：`SELECT supplier_name, phone FROM supplier` → 全列 `138****XXXX`；member.phone 同；orders 对照列无变化；缓存命中路径返回脱敏文本
  - 全量回归 **208 passed**（含新增 18 条）；2 失败为既有环境问题（LLM API 连接 + 混跑污染，单独跑通过）
- **已知残余**：改动前写入 Redis 的明文缓存最多残留 300s（TTL 自然过期），无需清库
