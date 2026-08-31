# EIA V5 任务清单（收官包）

> **单一事实源**：本文件是项目唯一任务清单（当前任务 + 历史归档）。开工前先读本文件，不依赖对话记忆。任务完成必须从"当前任务"移到"历史归档"并附验证数据与 commit。TASKS.md 变更随代码一起提交。

## 使用规则

1. **开工前**：读"当前任务"区，确认本次会话涉及的任务编号与边界；不在清单内的改动先登记再动手。
2. **任务五字段**：每个任务必须写明 目标 / 状态 / 修改范围 / 停止条件 / 验证数据。
3. **停止条件（防 Token 浪费）**：同一问题**连续 2 次修改后验证仍失败 → 立即停止**，在该任务下记录失败原因与尝试，不继续硬扛；涉及架构权衡的先与用户确认方案再动手。
4. **验证数据**：禁止用"已完成"代替验证——必须给出测试用例 / 断言 / 实测结果。
5. **归档**：完成的任务附验证结果与 commit hash 移入归档区，记录日期。

***

## 当前任务（按优先级）

### 📊 收官包基线（2026-08-31 实测，§1.2 基线先行）

* **Phase 1 开工基线**（log：`pytest_baseline_20260831.log`，耗时 80.90s）：N=213 / passed=209 / failed=4——均为既有环境问题，非代码缺陷

  * `tests/test_acceptance.py::test_deepseek_llm` — openai.APIConnectionError（DeepSeek API 连接失败）

  * `tests/test_e2e.py::test_graph_minimal` — TypeError: NoneType（LLM 连接失败的连带影响）

  * `tests/test_config.py::test_settings_load_from_env` — .env 真实 DEEPSEEK\_API\_KEY 污染测试（期望 `test-deepseek-key`，实际读到 `sk-4791...`）

  * `tests/test_config.py::test_settings_defaults` — .env 真实 Redis 端口污染测试（期望 `6379`，实际读到 Docker 端口 `6381`）

* **判据**：改后全量回归与基线对比——passed < 209 或新增非环境失败即回归

* **Phase 3 后最新基线**（log：`pytest_phase4_verify.log`，2026-08-31）：**242 collected / 238 passed / 4 failed**——4 失败与开工基线同根因（LLM 连接 ×2 + test\_config .env 污染 ×2），重跑可恢复

* **状态同步**：CLAUDE.md/AGENTS.md/README/面试素材文档测试数字已统一为 242/238/4（Phase 6 第 5 条完成，2026-08-31）

### T-01 ✅ 已完成（Phase 1，2026-08-31）→ 详见历史归档「T-01 会员 PII 越权」

### T-02 ✅ 已完成（Phase 1，2026-08-31）→ 详见历史归档「T-02 向量检索跨租户隔离」

### T-03 ✅ 已完成并归档（2026-08-12）→ 详见历史归档「T-03 PII 脱敏」

### T-04 🟡 P0 成本硬限额

* **目标**：单次分析 Token 上限（超限降级/截断）+ 租户月限额 + 超限预警（复用通知链路）

* **状态**：待办

* **修改范围**：`app/workflow/state.py`（Token 计数）+ `app/workflow/graph.py` + `services/notification.py` + 配置项。**禁止动** LLM 调用层封装

* **停止条件**：限额策略（截断 vs 拒绝 vs 降级简单模式）先确认；连续 2 次失败停止记录

* **验证数据**：压测触发超限 → 返回降级提示 + 预警通知发出；限额逻辑单测

### T-05 🟡 M3 Token 计数器跨请求竞态

* **目标**：全局 Token 计数器收进 AnalysisState（请求级），消除跨请求竞争

* **状态**：待办（改动小）

* **修改范围**：`app/workflow/state.py` + 引用全局计数器的 agent 节点

* **停止条件**：连续 2 次失败停止记录

* **验证数据**：`load_test_concurrency.py` 并发 2 请求计数不串；单测

### T-06 🟡 M8 并发同题 in-flight 锁

* **目标**：缓存击穿防护——并发同问题仅 1 次打 LLM，其余等待/复用

* **状态**：待办

* **修改范围**：`app/api/routes/analysis.py` / `app/tools/memory.py` 检索处加 SETNX 租约。**禁止动** 缓存读取链路

* **停止条件**：连续 2 次失败停止记录

* **验证数据**：并发同题 2 请求，日志仅 1 次 LLM 调用；load\_test

### T-07 🟡 M11 评估参数权限控制

* **目标**：`skip_reflection` / `bypass_cache` 仅专用评估 token 可传；**金丝雀闭环不受影响**

* **状态**：待办

* **修改范围**：`app/api/routes/analysis.py` 参数校验 + auth 新权限。改前先确认 n8n 金丝雀工作流使用的 token

* **停止条件**：金丝雀工作流兼容性先验证，破坏金丝雀即回滚；连续 2 次失败停止记录

* **验证数据**：普通 token 传参被拒；金丝雀 token 正常跑分；n8n 工作流实测

### T-08 🟡 M10 CSP / 安全头

* **目标**：全站加 CSP + X-Frame-Options 等安全头，且不破坏现有内联脚本

* **状态**：待办（风险：ECharts/内联 onclick 兼容）

* **修改范围**：`app/api/main.py` 中间件 + 前端内联脚本改造（外链或 nonce）

* **停止条件**：若内联改造影响页面功能，先出兼容方案；连续 2 次失败停止记录

* **验证数据**：Playwright 走通核心流程 + curl 验证安全头存在

### T-09 ✅ 已完成（Phase 3，2026-08-31）→ 详见历史归档「T-09 Reflection 契约化」

### T-12 ✅ 已完成并归档（2026-08-13）→ 详见历史归档「T-12 应用内金丝雀定时兜底」

### T-11 ✅ 已完成并归档（2026-08-12）→ 详见历史归档「T-11 金丝雀监控面板」

### T-10 ✅ 已完成并决策（2026-08-31）→ 详见历史归档「T-10 data_sources 落库 + RAG 止损」

***

## 暂缓区（已确认暂缓，不做）

* 前端低优先级优化（边际收益递减）：长函数拆分、var→const、Design Token 清理、CSS @media 合并、骨架屏、ARIA/键盘导航

* Prompt 一键回滚 API（有 YAML + CHANGELOG + 热重载，回滚频次低）

* 测试隔离：`test_v3_features` 与 `test_wechat` 混跑互相污染（各自单独跑全过）

***

## 历史归档

### T-01 ✅ 会员 PII 越权：Member 表补租户/门店维度（2026-08-31 完成，Phase 1）

* **目标**：Member 表增加租户/门店维度并纳入 RLS，任何登录用户不可查询其他租户会员手机号

* **决策**：加列+RLS（§7 决策 2）；路径 B 真 PG RLS（§7 决策 8）；策略 FOR ALL（USING + WITH CHECK，FORCE RLS 下 INSERT/DELETE 也需策略）；应用运行时用 eia\_app 用户（admin 是 superuser+BYPASSRLS，FORCE 也绕过）

* **修改范围**：`app/database/models.py`（Member.tenant\_id 声明）+ 迁移 015（member 加列/回填 5000 条/共享回填 users 117 条/FK/NOT NULL/索引/RLS POLICY FOR ALL + ENABLE + FORCE）+ `app/database/connection.py`（contextvar + after\_begin 注入 SET LOCAL app.tenant\_id）+ `app/middleware/tenant.py` + `.env`（DATABASE\_URL 切 eia\_app）+ `tests/test_tenant_isolation.py`（5 场景套件）。**未动** `app/tools/sql_runner.py`（红线）

* **验证数据**（2026-08-31）：PG 层 eia\_app 无 tenant\_id → 0 行、设 tenant\_id=1 → 5000 行；隔离套件 5 场景全绿（A 查自己 5000 行 / B 查 A 只看自己 3 条 / 无 tenant\_id → 0 行 / int() 注入拦截 / memory.py 无 tenant\_id 拒绝检索）；全量回归 218/214/4（与基线同根因，无新增失败）

### T-02 ✅ 向量检索跨租户隔离（2026-08-31 完成，Phase 1）

* **目标**：`users.tenant_id` 非空约束（或默认租户回填），NULL 用户检索被拒而非跨租户命中

* **决策**：默认租户回填（NULL users → default tenant\_id）+ 非空约束（放弃拒绝检索/混合策略，见方案 §7 决策 7）

* **修改范围**：015 迁移共享回填 + `app/tools/memory.py` 检索前置校验。**未动** 向量索引与 Embedding 链路

* **验证数据**（2026-08-31）：users.tenant\_id 回填 117 条全 = 1 + 非空约束 is\_nullable=NO；`find_similar_analyses` 无 user\_id → contextvar 兜底 → 仍无 → return \[]（拒绝，不跨租户命中）；隔离套件场景 5 验证通过

### T-09 ✅ Reflection 契约化（2026-08-31 完成，Phase 3，commit `b372aee0`）

* **目标**：Reflection 从"4 项主观自评"改为"4 项质量契约合规审查"——Numerical（30%）/ Grounding（35%）/ Reasoning（15%）/ Alignment（20%），加权 ≥70 且 Numerical/Grounding ≥50 双门槛

* **决策**：Step 0 相关性分析不可行（老 eval 无 4 维独立分/无满意度 ground truth）→ 次优替代证据拍板权重；471% 为新老口径混搭的合成数据自证，仅作叙事参考

* **修改范围**：`app/agents/reflection_agent.py`（4 项契约：2 确定性 + 2 LLM；双写老 feedback schema）+ 🆕 `app/tools/grounding.py`（零 LLM 确定性检查器，异 pct 同值 ±1e-9 严格阈值）+ `app/workflow/state.py` + `app/services/eval_metrics.py` + `tests/run_eval.py` + `prompts/yaml/reflection.yaml` + `prompts/reflection_prompt.py`。**未动** 报告生成主链路

* **验证数据**（2026-08-31，可复现）：Step 0 相关性 83.6%/88.9%；Step 1 单测 22/22；Step 2 合成 canary Alignment Share 22.83%（>4% 目标）+ 模板 `tests/eval_canary_v5_contract_TEMPLATE.json`；Step 3 全量回归 242/238/4，0 新增失败

* **遗留**：真实金丝雀重基线待 DeepSeek API 恢复后补做（真实 canary = 16 条，跑 `python -m tests.run_eval --canary --output <file>` 后重新聚合，勿直接替换 12 条模板）

### T-10 ✅ data_sources 落库 + RAG 止损（2026-08-31 完成，Phase 2 + Phase 4）

* **T-10a 落库**（随 `b372aee0` 提交）：`analysis_history.data_sources` 列 + 迁移 016 + `save_analysis_history` 写入 + 周报传递；`tests/test_t10a_data_sources_persistence.py` 通过

* **T-10b 止损实验：决策 = DELETE（砍掉 `search_similar_sql`）**

  * **理由**：SQL 复用链路真实数据有效复用率 ≈ 0%（决策线 20%），修复后价值池仅 0.8%，不值得 2-3 天修复

  * **数据**（phase4 脚本实测）：1022 条历史 data\_sources 落库仅 8 条（0.8%）；子结果 SQL 提取率 0.0%；端到端 100 query × Top-5 仅 4% 有 SQL 返回且 3/4 为同题自命中垃圾片段；对照语义检索层本身质量好（Top-1 中位相似度 1.0，判定样本 8/8 相关）——但同题复用由缓存+历史详情兜底，不需要 SQL Few-shot

  * **放弃的替代方案**：改提取源为 data\_sources（修复 2-3 天，价值池 8 条）；KEEP 死代码静默降级（白付 embedding 成本）

  * **结果**：`memory.py` 删函数（保留 find\_similar\_analyses / get\_history_detail）、`base.py` 删注入块、`eval_retrieval.py` 去 SQL 部分（加 set\_tenant\_id(1)，修复后召回率 83%）；语义检索保留；grep 无残留引用、py\_compile 通过

### D-01 ✅ 文档：V1/V1.5 版本资料整理（2026-08-13 完成）

* **背景**：用户需确认最初 V1 版本所在目录与资料位置。实勘定位：V1 = `D:\GaoZhiyuan\企业经营分析 Agent`（README 标注 v1.0，2026-05-29，Dify+n8n 低代码方案）；V1.5 = `D:\GaoZhiyuan\enterprise-agent`（首个代码化 Multi-Agent 流水线，LangGraph 雏形）

* **改动**：`docs/作品集-EIA-V4.md` 第 7 章演进表扩为 5 行（加"实现载体"列，新增 V1.5 行）+ 演进要点 3 条；`docs/AI产品经理面试作战包.md` 讲稿段（711 行）V1 描述校准为"Dify+n8n 低代码验证 → 代码化 → Multi-Agent"

* **验证数据**：

  * 作品集第 7 章：表格 5 列对齐渲染正常，md060 lint 已修

  * 作战包：仅改讲稿 V1 段一处，其余版本叙事（70/158/220/959 行）无需联动

  * Obsidian 镜像：备份至 `D:\Obsidian备份\2026-08-13-GZY备份\`，覆盖后 diff 与 docs 一致（0 差异）

* **遗留**：Obsidian 侧作品集为 PDF（`高志远-AI产品作品集.pdf`），需手工重新导出。~~V2 README "7 个 Agent" vs 作品集 "3 Agent"~~（已解决 2026-08-13：两口径并存——"3 Agent"= Send 并行扇出的领域 Agent 数，"7 Agent"= 全量 LLM Agent 节点含 supervisor/report/reflection/memory；作品集演进要点已补口径说明）

### D-02 ✅ 文档：2026 RAG 知识库升级（手册入库 + 三件套 RAG 2026 化）— 2026-08-21

* **背景**：响应第三方评估"EIA 还在 2024 基础 RAG"——将《AI产品经理核心知识手册》复制进 docs/ 作为新源，三件套补 2026 RAG 前沿（Agentic RAG / Hybrid + Reranker / GraphRAG / Context Engineering）。只改文档不动代码

* **改动**：🆕 `docs/AI产品经理核心知识手册_v1.1.md`（以 Obsidian 侧 2026-08 版为基底，手册补 2.8 节 + 目录/术语表/版本说明 v1.1→v1.2）；`docs/AI产品经理面试作战包.md`「什么是 RAG」「如何设计 RAG」两题话术升级；`docs/作品集-EIA-V4.md` 第 4 章"为何不用 GraphRAG"决策 + 第 10 章甄别框架条目；`CLAUDE.md` 同步规则补手册镜像位置；`CHANGELOG.md` 记录

* **验证数据**：

  * commit `50fded68`（2026-08-21 18:00 提交）：6 文件改动，+2811/-6

    * `CHANGELOG.md` +13 / `CLAUDE.md` +5 / `TASKS.md` +8

    * 🆕 `docs/AI产品经理核心知识手册_v1.1.md` +2772（2.8 节 2026 RAG 前沿 Agentic/Hybrid+Reranker/GraphRAG/Context Engineering）

    * `docs/AI产品经理面试作战包.md` ±8（RAG 两题话术 2026 化）

    * `docs/作品集-EIA-V4.md` +11（GraphRAG 甄别决策 + 第 10 章条目）

  * Obsidian 备份 `D:\Obsidian备份\2026-08-21-GZY备份\` 后覆盖手册 + 作战包，diff 0 差异

  * 三件套新增内容 md060 lint 通过

* **遗留**：作品集 PDF/HTML 手工导出（Obsidian 侧为 PDF，需重新导出）；TASKS.md 当时未同步归档（本条 2026-08-31 补归档）

* **归档说明**：commit 已落但 TASKS.md 状态停留在「待办」——收官包开工第一天（2026-08-31）按 §8 ③ 补归档，不占开发时间

### T-12 ✅ P1 应用内金丝雀定时兜底（2026-08-13 完成）

* **背景**：n8n 2.23 对 CLI 导入工作流的 cron 注册异常（Deregistered 无 Registered，6 次定时触发验证失败）；UI 创建的异常检测工作流 4 次定时成功证明机制正常、问题特定于 CLI 导入工作流

* **实现**：`app/scheduler.py`——`canary_scheduler_loop`（每日 canary\_hour:minute，默认 09:30，asyncio 循环）+ `today_canary_ran`（幂等判据：当天 UTC 日期是否有 canary 记录）+ `run_canary_now`（子进程 `run_eval --canary --save-db --parallel 8`，30 分钟超时 kill，失败只记日志不重试）。main.py startup 注册 + shutdown 取消；config 加 canary\_hour/canary\_minute

* **踩坑**：REPO\_ROOT 用 parents\[2] 数深一层 → 子进程找不到 run\_eval.py（exit 2）→ 修正 parents\[1]

* **验证数据**：

  * `tests/test_canary_scheduler.py` 3 条全过（无记录→False/插记录→True/昨日不误判）

  * 启动日志确认："金丝雀定时任务已注册（每日 09:30，幂等）" + "金丝雀定时任务启动"

  * 手动 `run_canary_now()` 完整跑通并落库（见 T-12 收尾 commit）

  * 全量回归 208+ passed

* **与 n8n 关系**：金丝雀不再依赖 n8n（双保险：n8n 修好后触发了也会被幂等判断跳过）；n8n 继续承担异常检测/周报调度（各自独立工作流，本次未动）

### T-11 ✅ P1 金丝雀监控面板（2026-08-12 完成）

* **方案**：前端独立板块（不动后端评估引擎——`GET /eval/runs` 已存在）。独立异步加载 + 序号防竞态 + 失败降级为空态引导，不影响主监控页 30s 缓存逻辑

* **实现（双版本）**：

  * 原生版 `views.js`：renderMonitorView 末尾插入 `mqCanary` 板块 + loadCanary/renderCanary 两函数

  * React 版 `Monitor.tsx`：独立 useEffect 加载 + 状态行 + ReactECharts 三系列趋势线

  * 共同内容：最新状态行（drift 徽章/model\_version/通过率/覆盖率/延迟/时间）+ drift\_summary 告警文案 + 三系列趋势线（通过率/覆盖率左轴 %、延迟右轴 ms）+ drift 红 pin 标记

* **量纲处理**：pass\_rate 已是 0-100；dimension\_coverage 是 0-1 需 ×100；avg\_latency\_ms 毫秒走 fmtSec

* **验证数据**（Playwright 浏览器实测，8002 + 5173 dev server）：

  * 两版单条数据：✅ 稳定徽章 + 通过率 62.5% / 覆盖率 86.7% / 延迟 67.38s 全部正确

  * 两版临时插入 drift=True 记录（验证后已删除）：⚠️ 漂移告警徽章 + 摘要文案 + 趋势图三系列渲染 + markPoint 红 pin 位置正确

  * JS 语法 node --check + tsc --noEmit 通过；全量回归 208 passed（与基线一致）

* **⚠️ 排查修复（本任务附带发现）**：`GET /eval/runs` 原权限 `user:manage` 过严——React 版监控页对 regional\_director 可见（AppLayout adminOnly 放行 admin+regional\_director），而 director 无 user:manage → 打开监控页触发 401 → client interceptor 清登录态强制登出。**已改为** **`alert:view`**（与 monitor 页其他端点一致），验证：admin 200 / regional\_manager（zhangsan）200 / 无权限角色被拒。8002 无 --reload，重启后生效

* **⚠️ 原生版可见性对齐（同日完成）**：原生版监控菜单原 `adminOnly`，已对齐 React 版（admin + regional\_director）。过程中发现并修复更深的问题——原生版角色信息依赖 `/admin/users`（需 user:manage），director 访问 401 导致菜单永不显示：改为登录响应 `role` 驱动（localStorage `eia_role`），`/admin/users` 仅作 scope 补充。另补 regional\_director 角色中文名（下拉/用户管理 badge 均显示"区域总监"）。**bump views.js v4.55→v4.56**（static 改版必须 bump，浏览器缓存坑）。验证：director\_huadong 登录 → 监控菜单可见 → 监控页 + 金丝雀面板正常，不再被 401 踢出

* **注意**：eval\_runs 目前仅 1 条真实记录（2026-08-10），趋势图需 ≥2 条才显示——n8n 每日跑分持续积累后自然出现

### T-03 ✅ P0 PII 脱敏（2026-08-12 完成）

* **方案**：集中式 2 拦截点——`sql_runner.run_sql` 结果格式化处（写 Redis 缓存**前**，缓存命中路径同安全）+ 审计中间件 query\_params。报告/表格/图表全部下游因 LLM 上下文无明文而天然安全，无需逐点处理

* **实现**：新建 `app/services/masker.py`（手机号正则 `(?<!\d)(1[3-9]\d)(\d{4})(\d{4})(?!\d)`，前 3 后 4 保留；数字边界防误伤；带分隔符变体）。仅改 sql\_runner 输出段与审计日志，**未动**注入器/数据层/SQL 生成

* **验证数据**：

  * `tests/test_masker.py` 18 条全过（标准/变体/边界不误伤/管道表格/query\_params）

  * 真实 PG 执行：`SELECT supplier_name, phone FROM supplier` → 全列 `138****XXXX`；member.phone 同；orders 对照列无变化；缓存命中路径返回脱敏文本

  * 全量回归 **208 passed**（含新增 18 条）；2 失败为既有环境问题（LLM API 连接 + 混跑污染，单独跑通过）

* **已知残余**：改动前写入 Redis 的明文缓存最多残留 300s（TTL 自然过期），无需清库

