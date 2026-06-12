# CHANGELOG — V4 修复与优化记录

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
