"""核心分析路由 — 用户主要使用的 API。

POST /api/analysis/analyze        — 提交经营分析问题，运行完整 Agent 链路
POST /api/analysis/analyze-stream — 流式分析（SSE 推送进度）
GET  /api/analysis/history        — 查看用户历史分析记录
GET  /api/analysis/similar        — 向量相似度搜索历史分析
"""

import json
import asyncio
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.dependencies import get_current_user, rate_limit, require_permission
from app.apm.tracer import AgentTracer, set_tracer
from app.auth.rbac import get_user_store_ids
from app.errors.user_friendly import format_agent_errors
from app.logging_config import bind_context, get_logger, new_trace_id
from app.tools.context_manager import ContextManager, extract_entities_from_report
from app.tools.memory import find_similar_analyses, get_history_by_user, get_history_detail
from app.workflow.graph import graph
from app.workflow.state import AnalysisState

router = APIRouter(prefix="/analysis", tags=["经营分析"])
logger = get_logger("eia.api.analysis")


# ---------------------------------------------------------------------------
# 请求 / 响应模型
# ---------------------------------------------------------------------------


class AnalysisRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=1,
        max_length=2000,
        description="自然语言经营分析问题",
        examples=["分析华东区域销售下降原因", "退款率最高门店是哪些"],
    )
    session_id: str | None = Field(
        default=None,
        description="V3 多轮对话会话 ID。不传则为单次分析（无上下文记忆）。",
    )


class AnalysisResponse(BaseModel):
    record_id: int | None = Field(default=None, description="分析记录 ID，用于反馈提交")
    report: str | None = Field(default=None, description="分析报告正文（Markdown 格式，可能含图表标记）")
    reflection_passed: bool = Field(default=False, description="是否通过 Reflection Agent 质量审核")
    similar_histories: list[dict] = Field(default=[], description="相似历史分析记录")
    agent_errors: list[dict] = Field(default=[], description="各 Agent 错误信息（含用户友好提示）")
    data_sources: list[dict] = Field(default=[], description="数据来源追溯（SQL、执行时间、返回行数）")
    followup_questions: list[str] = Field(default=[], description="建议追问问题列表")


class HistoryResponse(BaseModel):
    records: list[dict] = Field(description="历史分析记录列表")
    page: int = Field(description="当前页码")
    page_size: int = Field(description="每页条数")


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@router.post("/analyze", response_model=AnalysisResponse, summary="提交经营分析问题")
async def analyze(
    req: AnalysisRequest,
    user: dict = Depends(require_permission("analysis:create")),
    _: None = Depends(rate_limit),
    check_cache: bool = Query(False, description="仅检查缓存，不执行完整分析。用于流式优先模式下的秒返优化。"),
):
    """提交自然语言经营分析问题，运行完整的 Multi-Agent 分析链路。

    分析链路：Supervisor 规划 → 销售/CRM/财务 Agent 并行分析 → 聚合 → 图表推荐 → 报告生成 → 质检 → 记忆存储。

    V3 增强：支持多轮对话上下文（传入 session_id）、数据来源可追溯、图表自动生成、追问建议。

    check_cache=true：仅查询 Redis 缓存，命中则秒返，未命中返回空报告（不触发 LLM 调用）。
    """
    # ── V3.1: 分析结果缓存 ──
    # 缓存键包含 user_id + tenant_id + store_ids + session_id + question
    # 确保不同用户/门店权限/会话上下文的相同提问不会被错误命中
    import hashlib
    store_ids = await get_user_store_ids(user["user_id"])
    store_ids_key = ",".join(sorted(store_ids)) if store_ids else ""
    cache_raw = "|".join([
        str(user["user_id"]),
        str(user.get("tenant_id", "")),
        store_ids_key,
        req.session_id or "",
        req.question,
    ])
    cache_key = "analysis:" + hashlib.md5(cache_raw.encode()).hexdigest()[:16]
    redis = None
    try:
        from app.database.redis import get_redis
        redis = get_redis()
        cached = await redis.get(cache_key)
        if cached:
            import json as _json
            # decode_responses=True 已返回 str，无需 .decode()
            return AnalysisResponse(**_json.loads(cached))
    except Exception:
        pass  # 缓存读取失败不影响主流程（降级为重新分析）

    # V4 流式优先模式：check_cache=true 仅查缓存，不执行完整分析
    if check_cache:
        return AnalysisResponse(
            report=None,
            reflection_passed=False,
            agent_errors=[],
        )

    # --- V4: trace_id 与结构化日志 ---
    trace_id = new_trace_id()
    bind_context(trace_id=trace_id, session_id=req.session_id or "", user_id=user["user_id"])
    logger.info("分析请求开始", question=req.question[:80])

    # Check for similar historical analyses first
    try:
        similar = await find_similar_analyses(req.question)
    except Exception as e:
        logger.warning("相似历史检索失败（降级处理）", exc_info=True)
        similar = []

    # --- V3: Multi-turn context handling ---
    ctx = ContextManager(req.session_id) if req.session_id else None
    conversation_context = ""
    is_followup = False
    resolved_question = req.question

    if ctx:
        # V4: 验证会话所有权，防止跨用户读取
        session_user_id = await ctx.get_session_user_id()
        if session_user_id is not None and session_user_id != user["user_id"]:
            raise HTTPException(status_code=403, detail="无权访问此会话")
        is_followup = await ctx.is_followup(req.question)
        conversation_context = await ctx.get_context_for_llm()
        resolved_question = await ctx.resolve_references(req.question)

    # Inject explicit instruction for ranking/list queries to prevent truncation
    question = resolved_question
    from app.tools.question_enhancer import inject_ranking_hint
    question = inject_ranking_hint(question)

    # --- V4: APM tracer setup ---
    tracer = AgentTracer(session_id=req.session_id or "", question=req.question, trace_id=trace_id)
    set_tracer(tracer)

    # Run the full graph (with V4 trace_id)
    state = await graph.ainvoke({
        "question": question,
        "user_id": user["user_id"],
        "store_ids": store_ids,
        "session_id": req.session_id,
        "trace_id": trace_id,
        "conversation_context": conversation_context,
        "is_followup": is_followup,
        "resolved_question": resolved_question if is_followup else None,
    })

    logger.info("分析链路完成", reflection_passed=state.get("reflection_passed", False))

    # Flush APM traces (non-blocking)
    await tracer.flush()

    # Extract results
    report = state.get("report", "")
    reflection_passed = state.get("reflection_passed", False)
    raw_errors = state.get("agent_errors", [])
    agent_errors = format_agent_errors(raw_errors)

    # --- V3: Save conversation turn ---
    if ctx and report:
        entities = extract_entities_from_report(report)
        await ctx.add_turn(
            question=req.question,
            report=report,
            entities=entities,
            summary=report[:300],
        )

    response = AnalysisResponse(
        record_id=state.get("memory_record_id"),
        report=report,
        reflection_passed=reflection_passed,
        similar_histories=similar,
        agent_errors=agent_errors,
        data_sources=state.get("data_sources", []),
        followup_questions=state.get("followup_questions", []),
    )

    # ── V3.1: 写入分析结果缓存（5 分钟 TTL）──
    if redis is not None:
        try:
            await redis.setex(cache_key, 300, response.model_dump_json())
        except Exception:
            pass  # 缓存写入失败不影响主流程

    return response


@router.get("/history", response_model=HistoryResponse, summary="获取历史分析记录")
async def get_history(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页条数"),
    user: dict = Depends(require_permission("history:view")),
):
    """获取当前用户的历史分析记录，按时间倒序分页返回。"""
    offset = (page - 1) * page_size
    records = await get_history_by_user(user["user_id"], limit=page_size, offset=offset)
    return HistoryResponse(records=records, page=page, page_size=page_size)


@router.get("/history/{record_id}", summary="查看历史分析详情")
async def get_history_record(
    record_id: int,
    user: dict = Depends(require_permission("history:view")),
):
    """获取单条历史分析的完整内容，包括报告正文和各 Agent 的中间结果。"""
    detail = await get_history_detail(record_id, user_id=user["user_id"])
    if detail is None:
        raise HTTPException(status_code=404, detail="历史记录不存在")
    return detail


@router.get("/similar", summary="搜索相似历史分析")
async def search_similar(
    query: str = Query(..., min_length=1, description="搜索关键词"),
    limit: int = Query(5, ge=1, le=20, description="最大返回条数"),
    user: dict = Depends(require_permission("history:view")),
):
    """使用向量相似度搜索历史分析记录。基于 BGE-M3 Embedding 的语义匹配。"""
    results = await find_similar_analyses(query, limit=limit)
    return {"results": results}


# ---------------------------------------------------------------------------
# 流式 SSE 端点
# ---------------------------------------------------------------------------

NODE_LABELS = {
    "supervisor": "规划中",
    "sales_agent": "销售分析",
    "crm_agent": "CRM分析",
    "finance_agent": "财务分析",
    "inventory_agent": "库存分析",
    "supply_chain_agent": "供应链分析",
    "aggregator": "整合结果",
    "chart_advisor": "图表推荐",
    "report_agent": "生成报告",
    "reflection_agent": "质量审核",
    "save_memory": "保存记录",
}

# V4 流式进度：每个节点的详细进度文案（匹配 Demo 视频脚本）
NODE_PROGRESS_MESSAGES = {
    "supervisor": "🧠 正在规划任务，识别需要激活的分析 Agent...",
    "sales_agent": "📊 正在查询销售数据（趋势 / 排名 / 品类明细）...",
    "crm_agent": "👥 正在查询会员数据（活跃度 / 流失 / 复购率）...",
    "finance_agent": "💰 正在查询财务数据（退款率 / 客单价 / 利润）...",
    "inventory_agent": "📦 正在查询库存数据（周转率 / 缺货预警 / 滞销）...",
    "supply_chain_agent": "🚚 正在查询供应链数据（供应商绩效 / 采购成本）...",
    "aggregator": "📊 正在聚合各 Agent 分析结果...",
    "chart_advisor": "📈 正在推荐图表类型...",
    "report_agent": "📝 正在生成分析报告...",
    "reflection_agent": "✅ 正在从 4 个维度审核报告质量（一致性 / 逻辑 / 可操作 / 完整）...",
    "save_memory": "📥 正在保存分析记录至语义记忆...",
}


async def _stream_graph(
    question: str,
    user_id: int | None,
    store_ids: list[str] | None = None,
    session_id: str | None = None,
) -> AsyncGenerator[str, None]:
    """执行分析图并产生 SSE 事件流。

    V3：支持多轮对话上下文注入和追问建议生成。
    """
    # V4: trace_id 与 APM 追踪（与 /analyze 端点一致）
    trace_id = new_trace_id()
    bind_context(trace_id=trace_id, session_id=session_id or "", user_id=user_id)
    tracer = AgentTracer(session_id=session_id or "", question=question, trace_id=trace_id)
    set_tracer(tracer)

    # V3: Multi-turn context handling for streaming
    ctx = ContextManager(session_id) if session_id else None
    conversation_context = ""
    is_followup = False
    resolved_question = question

    if ctx:
        is_followup = await ctx.is_followup(question)
        conversation_context = await ctx.get_context_for_llm()
        resolved_question = await ctx.resolve_references(question)

    # Inject ranking/list instruction to prevent truncation
    from app.tools.question_enhancer import inject_ranking_hint as _inj_rank
    processed_question = _inj_rank(resolved_question)

    initial_state = {
        "question": processed_question,
        "user_id": user_id,
        "store_ids": store_ids,
        "session_id": session_id,
        "trace_id": trace_id,
        "conversation_context": conversation_context,
        "is_followup": is_followup,
        "resolved_question": resolved_question if is_followup else None,
    }

    # V4 (P0-1): 使用 graph.astream(stream_mode=["updates","custom","values"]) 一次性完成
    # 整个分析链路。各 Agent 节点通过 get_stream_writer() 发射 progress + token 事件，
    # 前端通过 "custom" 事件实时接收进度和流式文本。
    # 不再手动复制 report→reflection→retry→save_memory 编排。
    import time as _time
    final_state: dict = {}
    # 跟踪哪些节点已经开始（用于去重 phase 事件）以及开始时间（保证最短展示时间）
    _started_nodes: set[str] = set()
    _phase_start_times: dict[str, float] = {}
    _MIN_PHASE_DISPLAY_SEC = 0.6  # 每个步骤至少亮 0.6 秒，快完成的 Agent 也不一闪而过
    combined_stream = graph.astream(initial_state, stream_mode=["updates", "custom", "values"])
    async for mode, chunk in combined_stream:
        if mode == "updates":
            for node_name, node_output in chunk.items():
                # 确保 phase 至少展示了 MIN_PHASE_DISPLAY_SEC 才发 step
                started = _phase_start_times.get(node_name)
                if started:
                    elapsed = _time.monotonic() - started
                    if elapsed < _MIN_PHASE_DISPLAY_SEC:
                        await asyncio.sleep(_MIN_PHASE_DISPLAY_SEC - elapsed)
                label = NODE_LABELS.get(node_name, node_name)
                yield f"data: {json.dumps({'type': 'step', 'node': node_name, 'status': 'done', 'label': label})}\n\n"
        elif mode == "custom":
            # 统一解包 custom stream：兼容 dict 和 (namespace, data) 元组两种格式
            custom_data = None
            if isinstance(chunk, dict):
                custom_data = chunk
            elif isinstance(chunk, tuple) and len(chunk) == 2:
                custom_data = chunk[1]
            if isinstance(custom_data, dict):
                event_type = custom_data.get("type", "")
                if event_type == "token":
                    yield f"data: {json.dumps(custom_data, ensure_ascii=False)}\n\n"
                elif event_type == "progress":
                    # V4 流式进度：Agent 节点开始执行时推送进度消息
                    node = custom_data.get("node", "")
                    # 首次收到某节点的 progress 时，同时发送 phase（start）事件
                    if node and node not in _started_nodes:
                        _started_nodes.add(node)
                        _phase_start_times[node] = _time.monotonic()
                        label = NODE_LABELS.get(node, node)
                        progress_msg = NODE_PROGRESS_MESSAGES.get(node, custom_data.get("message", ""))
                        yield f"data: {json.dumps({'type': 'phase', 'node': node, 'status': 'start', 'label': label, 'message': progress_msg}, ensure_ascii=False)}\n\n"
        elif mode == "values":
            final_state = chunk

    # Extract results from the compiled graph's final state
    report = final_state.get("report", "")
    reflection_passed = final_state.get("reflection_passed", False)
    record_id = final_state.get("memory_record_id")

    # Flush APM traces (non-blocking)
    await tracer.flush()

    # Send the final result
    errors = format_agent_errors(final_state.get("agent_errors", []))

    # --- V3: Save conversation turn ---
    if ctx and report:
        entities = extract_entities_from_report(report)
        await ctx.add_turn(
            question=question,
            report=report,
            entities=entities,
            summary=report[:300],
        )

    # V4: 原始数据注入已通过 data_sources 字段实现（含 raw_data 和 row_count），
    # 前端可直接从 AnalysisResponse.data_sources 渲染完整数据表，
    # 无需在报告中搜索标记再追加。
    yield f"data: {json.dumps({'type': 'done', 'report': report, 'errors': [{'agent': e.get('agent','unknown'), 'error': str(e.get('error',''))[:200], 'user_message': e.get('user_message',''), 'icon': e.get('icon','')} for e in errors], 'reflection_passed': reflection_passed, 'record_id': record_id, 'data_sources': final_state.get('data_sources', []), 'followup_questions': final_state.get('followup_questions', [])}, ensure_ascii=False)}\n\n"


@router.post("/analyze-stream", summary="流式分析（SSE 实时推送）")
async def analyze_stream(
    request: Request,
    req: AnalysisRequest,
    user: dict = Depends(require_permission("analysis:create")),
):
    """提交问题并通过 Server-Sent Events 实时推送分析进度。

    事件类型：
    - phase: 节点开始执行（type=phase, node=..., label=...）
    - step:  节点执行完成（type=step, node=..., label=...）
    - done:  最终结果（type=done, report=..., reflection_passed=...）

    浏览器可用 EventSource 接收，前端进度条实时展示 9 步分析状态。
    """
    store_ids = await get_user_store_ids(user["user_id"])
    return StreamingResponse(
        _stream_graph(req.question, user["user_id"], store_ids, req.session_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
