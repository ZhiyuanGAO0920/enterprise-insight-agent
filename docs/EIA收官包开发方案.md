# EIA 收官包开发方案（V5 — Reliable Analytics Agent）

> 状态：待执行 ｜ 制定日期：2026-08-31 ｜ 预估：14-19 个工作日（压缩版 10-13 个工作日）
> 单一事实源：任务级跟踪以根目录 [TASKS.md](../TASKS.md) 为准，本文件为阶段排期 + 验收标准 + 时间盒的总纲。

---

## 0. 背景与总目标

### 背景

项目已完成核心功能、安全加固、评估闭环、面试资料（作战包 16 章 / 作品集 10 章），进入 **Stop Building / Start Packaging** 阶段。经 ChatGPT 两轮方案 + Claude Code 代码核查（2026-08-31），收敛为本次"收官包"。

### 总目标（验收一句话）

> 从"会分析数据的 Multi-Agent"升级为**"能够验证自己分析结果、可证明多租户安全、成本受控的 Enterprise Analytics Agent"**，打包为面试证据库，发布为 **V5 收官版**。

### 发布即冻结

V5 收官版发布日 = **功能开发冻结日**。之后仅做面试按需小修（演示问题、按 JD 定向补强）与素材同步。

---

## 1. 全局红线（每个阶段适用）

1. **禁止动** `app/tools/sql_runner.py`（注入器刚重写过）；**禁止动** LLM 调用层封装
2. **防回归纪律**：每阶段 改前跑全量 pytest 实测基线 N → 修改 → 改后全量回归 → 与基线对比（基线先行；2026-08-31 实测 N=213 collected，收官包开发中测试数会增长，一律以实测为准，不写死）
3. **两套基线独立判据**：功能基线（pytest 全量）与质量基线（eval 金丝雀 16 条）口径不同，不混用、不互相对比
4. **停止条件**：同一问题连续 2 次修改后验证仍失败 → 立即停止，记录原因，向用户汇报等待决策
5. **完成标准**：每阶段验证数据**不达标不 commit**；达标后 commit 并移入 TASKS.md 历史归档
6. **前端 static 改版必须 bump `?v=` 版本号**（浏览器缓存坑）
7. **文档同步**：阶段 1-5 涉及的 docs 更新，完成当天同步 Obsidian（先备份到 `D:\Obsidian备份\YYYY-MM-DD-GZY备份\`，覆盖后 diff 校验 0 差异）

---

## 2. 阶段排期总览

| 序 | 阶段 | 对应 TASKS | 时间盒 | 完成标志 |
|----|------|-----------|--------|---------|
| 0 | 决策门：T-01 迁移方案拍板 | T-01 | 当天 | 方案确认 + 决策记录 |
| 1 | 🔴 安全收官：多租户隔离 | T-01 + T-02 | **5 个工作日**（超时降级） | 隔离套件全绿 + 全量回归（实测 N）无新增失败 |
| 2 | 🟡 证据链闭环：落库 + Claim Grounding | T-10a + 新增 | 4 个工作日 | Evidence Coverage 指标有数 |
| 3 | 🟡 Reflection 契约化 | T-09 | 2 个工作日 | 契约 4 项生效 + 金丝雀重基线 |
| 4 | 🟡 T-10 止损实验 | T-10b | 1 个工作日 | KEEP / DELETE 决策 + 记录 |
| 5 | 🟡 成本治理：Budget-aware | T-04 | 3 个工作日 | 超限降级 + 预警实测 |
| 6 | 打包：V5 收官版发布 | 新增 | 3 个工作日 | 命名升级 + 素材同步 + 演示 |
| **合计** | | | **14-19 个工作日 ≈ 3.5-4.5 周** | |

**并行空间（校准后）**：阶段 2 的落库（T-10a）先行；阶段 3 的契约设计与 Reflection 改造可与其并行（运行时 data_sources 已存在，契约的 Grounding 检查不依赖落库），但阶段 3 的**完整验收**（Evidence Coverage 维度变化 + 金丝雀重基线）依赖阶段 2 指标落地；阶段 4 实验可与阶段 3 同天进行。

---

## 3. 各阶段详细方案（五字段）

### Step 0：决策门 —— T-01 迁移方案拍板

- **目标**：确认 Member 表隔离方案，T-01 才能开工
- **推荐**：**加列（tenant_id + store_id）+ RLS 策略**
  - T-03 已做输出脱敏（`138****8000`），"弱化展示"是重复建设——残余风险在 RLS 层（绕过脱敏直接读库），不在展示层
  - Demo 数据仅 5,000 会员，回填成本可忽略；拆表属过度设计
- **产出**：决策记录（理由/放弃方案），写入本文件 §7 决策记录
- **验证数据**：用户确认 + 记录入库

### Phase 1 🔴 P0-1：多租户安全收官（T-01 + T-02 + 隔离测试套件）

- **目标**：① Member 表补租户/门店维度并纳入 RLS，任何登录用户不可查询其他租户会员手机号；② `users.tenant_id` 非空约束（或默认租户回填），NULL 用户检索被拒而非跨租户命中
- **修改范围**：`app/database/models` + alembic 迁移 + RLS 策略 + `scripts/seed_data.py`（T-01）；迁移 + `app/tools/memory.py` 检索前置校验 + 回填脚本（T-02）；新增 `tests/test_tenant_isolation.py`
- **禁止动**：`sql_runner.py`、向量索引与 Embedding 链路
- **执行顺序（固定）**：
  1. 全量 pytest 基线（实测 N）→ 记录结果
  2. T-01：Member 表加列 + 数据回填 + RLS
  3. T-02：users.tenant_id 约束 + 孤儿用户处理 + memory 检索校验
  4. Cross-Tenant Isolation Test Suite
  5. 全量回归（实测 N）→ 与基线对比
- **停止条件**：Step 0 方案未确认不开始；连续 2 次失败停止记录；**5 个工作日时间盒**。**"最小可讲版本"前置定义**（超时前定好，不临时定义）：必须达标项 = 隔离套件 5 场景全绿 + 全量回归无新增失败；可让路项 = 迁移文档完善、回填脚本健壮性打磨、孤儿用户策略文档
- **验证数据**（隔离套件至少 5 场景）：
  - Tenant A 查自己数据 → PASS
  - Tenant A 查 Tenant B 数据 → 0 rows
  - Tenant A 向量检索 Tenant B → 0 results
  - 伪造 tenant_id → DENY
  - 伪造 user_id → DENY
  - 全量回归（实测 N）：无新增失败（既有环境失败除外）
- **面试转化**："多租户 AI SaaS 安全隔离 = Application → SQL → DB → Vector 全链路验证；安全修复必须通过完整 Regression（不是只验证漏洞被修，而是验证没破坏原有分析能力）"

### Phase 2 🟡 P0-2：证据链闭环（T-10a 落库 + Claim-level Grounding）

- **目标**：① `data_sources` 持久化到 `analysis_history`（历史分析可回查"结论当时依据什么数据"）；② 报告数字级 grounding 校验；③ 新增 **Evidence Coverage** 指标
- **前置决策（先定口径再算数）**：定义"关键结论"口径——起点定为**报告中含数字的陈述句**；口径未定不开始（防 T-09"可操作性 4%"式口径陷阱重演）
- **修改范围**：`app/database/models` + `save_analysis_history`（T-10a）；报告生成后置校验（数字 ↔ `data_sources.raw_data` 比对，确定性、零 LLM 成本）+ eval 指标；前端报告证据块展示（static 改版须 bump `?v=`）
- **禁止动**：SQL 生成链路；`search_similar_sql` 检索（属 Phase 4 决策范围）
- **停止条件**：口径未定不开始；连续 2 次失败停止记录
- **验证数据**：
  - 执行一次分析后查 `analysis_history` 有 `data_sources`
  - 抽样 5 条报告数字 ↔ raw_data 比对，一致率记录
  - Evidence Coverage 首次出数（有证据支撑的关键结论 / 关键结论总数）
  - 前端证据块渲染正常（Playwright 或浏览器实测）
- **面试转化**：证据链截图 + "每个结论可回查依据 SQL/字段/时间范围"；Evidence Coverage 替代泛泛的 pass rate 成为核心质量指标

### Phase 3 🟡 P0-3：Reflection 契约化（T-09）

- **目标**：Reflection 从"这份报告写得好不好"改为**"是否违反质量契约"**，4 项检查：
  | 契约项 | 检查 |
  |--------|------|
  | Numerical Consistency | 报告数字与 SQL 结果一致 |
  | Evidence Grounding | 关键结论存在 data_sources 支撑 |
  | Reasoning Validity | 因果判断有数据支持 |
  | Recommendation Alignment | 建议与 Finding 对应 |
- **修改范围**：`app/agents/reflection_agent.py` + `prompts/yaml` + eval 标注（`tests/eval_set.json`）；**禁止动**报告生成主链路
- **执行顺序**：先用现有 eval 数据做相关性分析（维度 vs 满意度）→ 再改契约与权重 → 契约生效后**金丝雀重打基线**（改 Reflection 会使 16 条子集分数偏移，旧基线对比会误报模型漂移）
- **停止条件**：相关性分析未出不做权重变更；连续 2 次失败停止记录
- **验证数据**：契约化前后 eval 对比；金丝雀重基线记录；"可操作性/Recommendation Alignment"维度占比变化（目标：显著高于 4%）
- **面试转化**："Reflection 从自评改质检契约"决策案例（0 次→25% 报告有问题；1 次→修复 60%；自评维度不可量化 → 契约化）

### Phase 4 🟡 P1-4：T-10 止损实验（相似 SQL 检索去留）

- **目标**：判断 `search_similar_sql` 是否有实际复用价值，产出 KEEP / DELETE 决策
- **方法**（预算 1-2 小时）：100 个历史问题 → Top-K 相似检索 → 人工判定"真正有复用价值"比例
- **决策规则**：Top-5 有效复用率 < 20% → **砍掉**，写止损记录；若确实降低 SQL generation token / 延迟 / SQL 错误率 → 再修（另排期 2-3 天）
- **产出**：实验记录 + 决策 + 作品集止损案例文案
- **验证数据**：实验样本、判定比例、决策理由入库
- **面试转化**："主动砍功能"案例："我原本实现了 SQL 历史复用，但实测任务分布下命中价值很低，没有为了保留 RAG 而保留 RAG"——比"我用了 RAG"有价值得多

### Phase 5 🟡 P1-5：成本治理（T-04 Budget-aware Agent）

- **目标**：最小版成本限额——单请求 Token 上限 + 超限降级 + 租户月限额 + 超限预警（复用通知链路）
- **前置决策**：限额策略三选一确认（超限→截断 vs 拒绝 vs 降级简单模式，推荐降级）
- **修改范围**：`app/workflow/state.py`（Token 计数，顺带评估 T-05 竞态是否顺手修复）+ `app/workflow/graph.py` + `app/config.py` + `services/notification.py`
- **禁止动**：LLM 调用层封装
- **停止条件**：限额策略未确认不开始；连续 2 次失败停止记录
- **验证数据**：压测触发超限 → 降级提示 + 预警通知发出；限额逻辑单测
- **面试转化**："Budget-aware Agent"叙事，与既有 DeepSeek 分时定价 + 13:05 错峰金丝雀连成完整成本治理故事（模型选择 → Token Budget → 任务级控制 → 错峰调度 → Canary 成本控制）

### Phase 6 🎬 打包：V5 收官版发布

- **目标**：项目从"开发项目"切换为"面试证据库"
- **内容**：
  1. 命名升级：README / CLAUDE.md / 作品集标题 → **EIA V5 — Reliable Analytics Agent（收官版）**
  2. 演示视频：新增"可靠性"一段（证据面板 + 隔离测试套件演示；录制前跑 `warmup_demo_cache.py` 预热，查询 30-60s → ~8s）
  3. 作品集 10 章更新：证据面板/隔离套件截图 + 演进表加 V5 行 + 质量指标表
  4. README 站外视角自查（GitHub 公开项目，陌生人 30 秒能看懂做什么）
  5. **测试数字与状态同步**：作战包/作品集/简历/面试叙事方案/AGENTS.md 中"192 条"→ 实测 N；AGENTS.md 状态对齐 CLAUDE.md（V4.8 → V5.0）
  6. 作战包同步 + Obsidian 镜像（备份 → 覆盖 → diff 校验 0 差异）
- **验证数据**：视频可完整播放；Obsidian diff 0 差异；作品集 md060 lint 通过
- **发布动作**：打 tag `v5.0`，TASKS.md 归档收官包全部条目，发布日 = 冻结功能开发日

---

## 4. 总验收标准（收官完成判据）

1. Cross-Tenant Isolation Test Suite 全绿，全量回归（实测 N）与基线对比无新增失败
2. `analysis_history` 可回查 data_sources；Evidence Coverage 首次出数且口径有文档
3. Reflection 契约 4 项生效，金丝雀基线已重置
4. T-10 实验决策记录在案（KEEP 或 DELETE 都有理由）
5. 成本限额压测通过（降级 + 预警）
6. 版本命名 V5 收官版，作品集/作战包/README/Obsidian 同步完毕
7. **功能开发冻结**——后续仅按需小修

---

## 5. 风险与降级路径

| 风险 | 应对 |
|------|------|
| Phase 1 超时（最可能的超时点） | 5 个工作日硬时间盒，超时回退"最小可讲版本"（§3 Phase 1 已前置定义必须达标项） |
| 代码已动但验证不达标 | 验证数据不达标不 commit（§1.5）——比时间盒超时更早止损 |
| 金丝雀误报模型漂移 | Reflection 契约化当天重基线并记录 |
| "关键结论"口径含糊 → 指标无解释力 | 先定口径（含数字的陈述句）再算数 |
| 安全修复引入回归 | 基线先行纪律（§1.2），禁止动 sql_runner |
| 求职时间被挤压 | 压缩版：砍演示视频、T-04 只做单请求上限、Claim Grounding 只做数值级 → 10-13 个工作日 |

---

## 6. 与 TASKS.md 的关系

- Phase 1/3/5 对应现有 T-01/T-02/T-09/T-04，按各自 TASKS 条目的边界执行
- **T-10 拆分为 T-10a（落库，随 Phase 2 做）与 T-10b（检索实验，随 Phase 4 做）**——执行时更新 TASKS.md 条目
- 新增任务（隔离测试套件、Claim Grounding、Evidence Coverage、Packaging）开工前登记入 TASKS.md（单一事实源，不在清单内的改动先登记再动手）
- **D-02 归档收尾**：D-02（2026 RAG 知识库升级）工作已提交（commit 50fded68），但 TASKS.md 状态仍为"待办"——开工前先补归档（状态 + 验证数据 + commit hash），不占收官包开发时间
- 每阶段完成：验证数据 + commit hash 移入 TASKS.md 历史归档

---

## 7. 决策记录（本方案关键决策）

| # | 决策 | 理由 | 数据支撑 | 放弃的方案 | 结果 |
|---|------|------|---------|-----------|------|
| 1 | 收官包完成后命名 **V5 收官版**，冻结功能开发 | 求职杠杆边际递减；能力已齐，缺的是"何时停"的证据 | 8 月以来暂缓区判断 + 外部方案两轮收敛 | 继续开 V5 开发周期 / 停留在 V4.8 命名 | 待执行 |
| 2 | T-01 采用**加列 + RLS** | 输出层已脱敏（T-03），弱化展示重复建设；风险在 RLS 层 | 5,000 会员回填成本可忽略 | 拆表（过度设计）/ 弱化展示（重复建设） | ✅ 已确认 2026-08-31（用户拍板） |
| 7 | T-02 孤儿用户采用**默认租户回填** | 兼容现有数据不阻塞登录；安全性由 RLS 兜底（回填后无 NULL） | users.tenant_id NULL 用户回填到 default tenant + 非空约束 | 拒绝检索（可能误伤历史用户）/ 混合策略（分角色处理逻辑复杂） | ✅ 已确认 2026-08-31（用户拍板） |
| 3 | T-10 **实验先行**，Top-5 复用率 <20% 即砍 | 命中率当前 0%，修之前先验证价值 | 2026-08 实测命中率 0% | 直接修复（可能白投入 2-3 天） | 待执行 |
| 4 | Eval 不扩 100 条，维持 10-15 确定性 + 16 LLM Judge + Evidence Coverage | 人工 ground truth 成本高；现有评估体系粒度缺"数据正确性"与"证据覆盖"两维 | 16 条金丝雀已覆盖漂移检测 | 100 条 Benchmark（维护成本大） | 待执行 |
| 5 | Evidence Chain 定位为**补全而非新增** | 代码已存在 data_sources 全链路（state/base/SSE/前端追溯面板） | state.py:62 / base.py:149 / views.js:853 | 新建证据链架构（重复建设） | 已核实 |
| 6 | 版本跨度 **V4.8 → V5.0**（跳过 V4.9） | 收官里程碑用版本号标记叙事收束，而非开发周期；能力已跨 V5 叙事门槛（证据/隔离/成本/漂移） | 起点 V4.8 出处：CLAUDE.md 状态行（与 2026-08-31 实测 213 collected 一致）；AGENTS.md 的 V4.6.0 为过时值，已列入 Phase 6 同步 | 命名为 V4.9（显得仍在迭代中） | 待执行 |
| 8 | T-01 RLS 实施**路径 B：真 PG RLS**（非应用层 SQL 改写） | 现状探明：项目无 PG RLS，sql_runner.py 自称的"RLS"是 SQL 字符串注入；PII 漏洞在 _detect_store_column 显式跳过 Member 表；§1.1 禁止动 sql_runner | 用户拍板 2026-08-31；Member.tenant_id 列已存在（不需加列） | 路径 A（改 sql_runner，违反 §1.1）/ 路径 C（双保险，超时风险） | ✅ 已确认 |
| 9 | RLS 策略从 **FOR SELECT** 改为 **FOR ALL**（USING + WITH CHECK） | FORCE RLS 下 INSERT/DELETE 也需策略通过；FOR SELECT 无 WITH CHECK → eia_app INSERT 被拒 `InsufficientPrivilegeError` | 隔离测试场景 2 暴露：fixture 插入 B 数据被 RLS 拒；改 FOR ALL 后 INSERT/DELETE 均需 tenant_id 匹配 | FOR SELECT + 单独 INSERT 策略（策略碎片化）/ 给 eia_app BYPASSRLS（破坏隔离） | ✅ 已确认 2026-08-31（测试驱动发现） |
| 10 | 应用层 DB 用户从 **admin** 切换为 **eia_app**（NOSUPERUSER+NOBYPASSRLS） | admin 是 superuser+BYPASSRLS，FORCE 也绕过；RLS 对 admin 形同虚设 | `SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname='admin'` → rolsuper=t, rolbypassrls=t | 给 admin 去 BYPASSRLS（影响 alembic 迁移）/ 不用 FORCE（owner 绕过） | ✅ 已确认 2026-08-31 |

---

## 8. 执行提示

- **开工第一天**：① 跑全量 pytest 实测基线并记录 N（2026-08-31 实测 213 collected；此后全文以实测 N 为准）；② 确认 Step 0 决策；③ 归档 D-02（见 §6）
- **测试数字全量同步**（Trae 审查发现）：面试素材文档（作战包/作品集/简历/面试叙事方案）与 AGENTS.md 仍写"192 条"（V4.6.0 时期数字）——并入 Phase 6 统一更新为实测 N；AGENTS.md 状态同步对齐 CLAUDE.md
- 每个阶段结束当天：commit + TASKS.md 归档 + 面试转化点文案落进作战包（不攒到最后）
- 全部完成后：打 tag `v5.0`，更新 CLAUDE.md 状态描述，正式进入面试期
