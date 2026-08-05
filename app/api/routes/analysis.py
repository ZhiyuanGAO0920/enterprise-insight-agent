"""核心分析路由 — 用户主要使用的 API。

POST /api/analysis/analyze        — 提交经营分析问题，运行完整 Agent 链路
POST /api/analysis/analyze-stream — 流式分析（SSE 推送进度）
GET  /api/analysis/history        — 查看用户历史分析记录
GET  /api/analysis/similar        — 向量相似度搜索历史分析
"""

import hashlib
import json
import asyncio
import secrets
from datetime import datetime, timedelta
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.api.dependencies import get_current_user, rate_limit, require_permission
from app.apm.tracer import AgentTracer, set_tracer
from app.database.connection import get_session
from app.database.models import AnalysisHistory
from app.llm import reset_task_tokens
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
# 分析结果缓存（V3.1 引入；V4.6 增加流式缓存快速通道）
# ---------------------------------------------------------------------------

CACHE_TTL_SEC = 1800  # 分析结果缓存有效期（30 分钟；demo 预热重问题需 10 分钟级余量）


def _analysis_cache_key(
    user_id: int | str,
    tenant_id: str,
    store_ids: list[str],
    session_id: str | None,
    question: str,
) -> str:
    """构建分析结果缓存键。

    键含 user_id + tenant_id + store_ids + session_id + question，
    确保不同用户/门店权限/会话上下文的相同提问不会被错误命中。
    V4.6：流式快速通道使用 session_id="" 的别名键——同一用户/门店范围内
    的相同首次提问（不依赖会话上下文）可跨会话共享结果。
    """
    store_ids_key = ",".join(sorted(store_ids)) if store_ids else ""
    raw = "|".join([
        str(user_id),
        str(tenant_id or ""),
        store_ids_key,
        session_id or "",
        question,
    ])
    return "analysis:" + hashlib.md5(raw.encode()).hexdigest()[:16]


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
    skip_reflection: bool = Field(
        default=False,
        description="V4.6.3 实验参数：跳过 Reflection 质检与重试（对照实验用，生产勿开启；开启时绕过缓存保证每次真实执行）",
    )


class AnalysisResponse(BaseModel):
    record_id: int | None = Field(default=None, description="分析记录 ID，用于反馈提交")
    report: str | None = Field(default=None, description="分析报告正文（Markdown 格式，可能含图表标记）")
    reflection_passed: bool = Field(default=False, description="是否通过 Reflection Agent 质量审核")
    similar_histories: list[dict] = Field(default=[], description="相似历史分析记录")
    reflection_feedback: str | None = Field(default=None, description="Reflection 质检反馈 JSON")
    agent_errors: list[dict] = Field(default=[], description="各 Agent 错误信息（含用户友好提示）")
    data_sources: list[dict] = Field(default=[], description="数据来源追溯（SQL、执行时间、返回行数）")
    followup_questions: list[str] = Field(default=[], description="建议追问问题列表")
    supervisor_plan: str | None = Field(default=None, description="Supervisor 规划（激活的 Agent 和推理过程）")


class HistoryResponse(BaseModel):
    records: list[dict] = Field(description="历史分析记录列表")
    total: int = Field(default=0, description="总条数")
    page: int = Field(description="当前页码")
    page_size: int = Field(description="每页条数")


class ShareRequest(BaseModel):
    record_id: int = Field(..., description="要分享的分析记录 ID")


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
    store_ids = await get_user_store_ids(user["user_id"])
    # V4.6.3: 对照实验（skip_reflection）绕过缓存 —— 保证每次真实执行且不污染生产缓存
    redis = None
    cache_key = None
    if not req.skip_reflection:
        cache_key = _analysis_cache_key(user["user_id"], user.get("tenant_id", ""), store_ids, req.session_id, req.question)
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

    # V4.6.1: 相似历史检索与主链路并发执行，不再阻塞图启动。
    # 它只影响「相似历史」展示面板，而 Embedding + 向量搜索可能耗时 1-3s。
    # 任务在响应组装时收割；图超时则取消，防止悬挂。
    similar_task = asyncio.create_task(
        find_similar_analyses(req.question, user_id=user["user_id"])
    )

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

    # 重置 Token 累计（为本次分析清空上次的残留）
    reset_task_tokens()

    # Run the full graph (with V4 trace_id)
    # V4.2: 420s 超时防止单次分析无限挂起（含 LLM 重试场景）
    try:
        state = await asyncio.wait_for(
            graph.ainvoke({
                "question": question,
                "original_question": resolved_question,  # 原始问题（不带 ranking hint），用于展示
                "user_id": user["user_id"],
                "store_ids": store_ids,
                "session_id": req.session_id,
                "trace_id": trace_id,
                "conversation_context": conversation_context,
                "is_followup": is_followup,
                "resolved_question": resolved_question if is_followup else None,
                "skip_reflection": req.skip_reflection,
            }),
            timeout=420,
        )
    except asyncio.TimeoutError:
        similar_task.cancel()  # 主链路已超时，取消并发的相似历史检索
        logger.error("分析链路超时（>420s），返回空报告")
        return AnalysisResponse(
            report=None,
            reflection_passed=False,
            agent_errors=[{"agent": "system", "error": "分析链路超时，请简化问题后重试"}],
        )

    logger.info("分析链路完成", reflection_passed=state.get("reflection_passed", False))
    # Flush APM traces (non-blocking)
    await tracer.flush()

    # Extract results
    report = state.get("report", "")
    reflection_passed = state.get("reflection_passed", False)
    _debug_fb = state.get("reflection_feedback")
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

    # V4.6.1: 收割并发执行的相似历史检索（15s 兜底，不影响主响应返回）
    try:
        similar = await asyncio.wait_for(similar_task, timeout=15)
    except asyncio.CancelledError:
        raise  # 请求中断直接透传
    except Exception as e:
        logger.warning("相似历史检索失败（降级处理）", exc_info=True)
        similar = []

    # V4.5: 传递 Supervisor 规划供前端展示推理过程
    _supervisor_plan = state.get("supervisor_plan")

    response = AnalysisResponse(
        record_id=state.get("memory_record_id"),
        report=report,
        reflection_passed=reflection_passed,
        reflection_feedback=state.get("reflection_feedback"),
        similar_histories=similar,
        agent_errors=agent_errors,
        data_sources=state.get("data_sources", []),
        followup_questions=state.get("followup_questions", []),
        supervisor_plan=_supervisor_plan,
    )

    # ── V3.1: 写入分析结果缓存（30 分钟 TTL）──
    if redis is not None:
        try:
            _payload_obj = json.loads(response.model_dump_json())
            # V4.6: 记录实际执行节点，供缓存重放精确还原进度条（避免全 11 步闪烁）
            try:
                _plan = state.get("supervisor_plan") or ""
                _agents = (json.loads(_plan) or {}).get("activated_agents", []) if isinstance(_plan, str) else (_plan or {}).get("activated_agents", [])
                _completed = ["supervisor"] + list(_agents) + ["aggregator", "report_agent", "save_memory"]
                if state.get("query_type") != "simple":
                    _completed += ["chart_advisor", "reflection_agent"]
                _payload_obj["completed_nodes"] = _completed
            except Exception:
                pass  # 推导失败不影响主流程（重放时走启发式兜底）
            payload = json.dumps(_payload_obj, ensure_ascii=False)
            await redis.setex(cache_key, CACHE_TTL_SEC, payload)
            # V4.6: 同时写入无 session 的别名键，供流式端点（键不含 session）命中
            alias_key = _analysis_cache_key(user["user_id"], user.get("tenant_id", ""), store_ids, "", req.question)
            await redis.setex(alias_key, CACHE_TTL_SEC, payload)
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
    # V4.5: 查询总条数供前端分页显示
    from app.database.connection import get_session
    from sqlalchemy import select, func
    from app.database.models import AnalysisHistory
    async with get_session() as s:
        total = (await s.execute(select(func.count(AnalysisHistory.id)).where(AnalysisHistory.user_id == user["user_id"]))).scalar() or 0
    return HistoryResponse(records=records, total=total, page=page, page_size=page_size)


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


# ---------------------------------------------------------------------------
# 报告分享（只读链接）
# ---------------------------------------------------------------------------

SHARE_TTL_DAYS = 30  # 分享链接默认有效期


@router.post("/share", summary="生成报告分享链接")
async def create_share_link(
    payload: ShareRequest,
    user: dict = Depends(require_permission("history:view")),
):
    """为历史分析生成只读分享链接。已有未过期的 token 则复用。

    返回的 url 为相对路径（/share/{token}），前端拼接 origin 使用。
    """
    detail = await get_history_detail(payload.record_id, user_id=user["user_id"])
    if detail is None:
        raise HTTPException(status_code=404, detail="历史记录不存在")

    now = datetime.now().replace(microsecond=0)
    expires = now + timedelta(days=SHARE_TTL_DAYS)
    async with get_session() as session:
        r = await session.get(AnalysisHistory, payload.record_id)
        if r is None:
            raise HTTPException(status_code=404, detail="历史记录不存在")
        if r.share_token and r.share_expires_at and r.share_expires_at > now:
            # 已有有效分享，复用
            token, expires = r.share_token, r.share_expires_at
        else:
            token = secrets.token_urlsafe(24)
            r.share_token = token
            r.share_expires_at = expires
            await session.commit()
    return {"token": token, "url": f"/share/{token}", "expires_at": expires.isoformat()}


@router.get("/share/{token}", summary="通过分享链接查看报告（公开只读）")
async def get_shared_report(token: str):
    """免登录只读接口：通过 token 返回报告内容。token 不存在或已过期返回 404。"""
    async with get_session() as session:
        from sqlalchemy import select
        r = (await session.execute(select(AnalysisHistory).where(AnalysisHistory.share_token == token))).scalar_one_or_none()
        if r is None or r.share_expires_at is None or r.share_expires_at < datetime.now().replace(microsecond=0):
            raise HTTPException(status_code=404, detail="分享链接不存在或已过期")
        return {
            "id": r.id,
            "question": r.question,
            "report": r.report or "",
            "reflection_passed": r.reflection_passed,
            "create_time": r.create_time.isoformat() if r.create_time else None,
        }


@router.delete("/share", summary="取消报告分享")
async def revoke_share_link(
    record_id: int = Query(..., description="要取消分享的分析记录 ID"),
    user: dict = Depends(require_permission("history:view")),
):
    """取消分享：清空 share_token，原链接立即失效。"""
    detail = await get_history_detail(record_id, user_id=user["user_id"])
    if detail is None:
        raise HTTPException(status_code=404, detail="历史记录不存在")
    async with get_session() as session:
        r = await session.get(AnalysisHistory, record_id)
        if r is None:
            raise HTTPException(status_code=404, detail="历史记录不存在")
        r.share_token = None
        r.share_expires_at = None
        await session.commit()
    return {"ok": True}


@router.get("/similar", summary="搜索相似历史分析")
async def search_similar(
    query: str = Query(..., min_length=1, description="搜索关键词"),
    limit: int = Query(5, ge=1, le=20, description="最大返回条数"),
    user: dict = Depends(require_permission("history:view")),
):
    """使用向量相似度搜索历史分析记录。基于 BGE-M3 Embedding 的语义匹配。"""
    results = await find_similar_analyses(query, limit=limit, user_id=user["user_id"])
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


# V4.6: 缓存重放每步最短展示时长（与 _stream_graph 内 _MIN_PHASE_DISPLAY_SEC 一致，
# 11 步约 7 秒，画面自然且保留「流式进度」演示卖点）
_CACHE_REPLAY_STEP_SEC = 0.6

# ---------------------------------------------------------------------------
# SSE 心跳：节点内部执行期（非流式 LLM 调用 / SQL / Embedding）可能长达数十秒，
# 期间无任何事件 —— 前端 45s 看门狗会误判连接挂死而 abort（"整体经营状况分析"
# 等全 Agent 综合查询在 LLM 慢时必然触发）。每 20s 推一个心跳事件仅用于保活，
# 前端忽略其内容；45s 看门狗语义不变，仍能兜住真正的死连接。
# ---------------------------------------------------------------------------

_HEARTBEAT_INTERVAL_SEC = 20.0


async def _with_heartbeat(
    graph_stream: AsyncGenerator,
    interval: float = _HEARTBEAT_INTERVAL_SEC,
) -> AsyncGenerator:
    """在 graph 事件流中穿插心跳 SSE 事件；graph 正常结束或抛异常时立即终止。

    心跳从属于主数据流：graph 结束后无论心跳任务处于何处都取消它，
    避免无限心跳流导致合并永不终止。
    慢节点（非流式 LLM / SQL / Embedding）静默期间，心跳保持字节流动，
    前端 45s 看门狗不再误判连接挂死；45s 语义不变，真死连接仍会被兜住。
    """
    queue: asyncio.Queue = asyncio.Queue()

    async def _pump() -> None:
        try:
            async for item in graph_stream:
                await queue.put(("data", item))
            await queue.put(("stop", None))
        except asyncio.CancelledError:
            raise
        except Exception as e:
            await queue.put(("error", e))  # 传播原始异常，行为与无心跳时一致

    async def _hb_pump() -> None:
        try:
            while True:
                await asyncio.sleep(interval)
                await queue.put(("hb", None))
        except asyncio.CancelledError:
            raise

    t_pump = asyncio.create_task(_pump())
    t_hb = asyncio.create_task(_hb_pump())
    try:
        while True:
            kind, payload = await queue.get()
            if kind == "stop":
                break
            if kind == "error":
                raise payload
            if kind == "hb":
                yield f"data: {json.dumps({'type': 'heartbeat'}, ensure_ascii=False)}\n\n"
            else:
                yield payload
    finally:
        t_pump.cancel()
        t_hb.cancel()
        await asyncio.gather(t_pump, t_hb, return_exceptions=True)


def _replay_nodes(cached: dict) -> list[str]:
    """推导缓存报告实际执行过的节点，用于精确还原进度条（而非全 11 步）。

    优先使用写入时记录的 completed_nodes；旧缓存（无该字段）则从
    supervisor_plan.activated_agents + reflection 标记推导：
    - 简单查询（无质检）：supervisor → 激活 Agent → aggregator → report → save_memory
    - 分析型（reflection_passed/feedback 存在）：追加 chart_advisor / reflection_agent
    """
    order = list(NODE_LABELS.keys())
    nodes = cached.get("completed_nodes")
    if nodes:
        return [n for n in order if n in nodes]
    try:
        plan = json.loads(cached.get("supervisor_plan") or "{}")
        agents = plan.get("activated_agents", [])
    except Exception:
        agents = []
    selected = {"supervisor", "aggregator", "report_agent", "save_memory"} | set(agents)
    if cached.get("reflection_passed") or cached.get("reflection_feedback"):
        selected |= {"chart_advisor", "reflection_agent"}
    return [n for n in order if n in selected]


async def _replay_cached_stream(cached: dict):
    """V4.6: 缓存命中时快速重放 SSE 事件流（无需重新调用 LLM）。

    只亮起实际执行过的节点（与真实链路一致），最后推送 done 事件
    携带缓存报告（含图表标记，前端渲染路径与真实流程完全一致）。
    """
    for node in _replay_nodes(cached):
        label = NODE_LABELS[node]
        msg = NODE_PROGRESS_MESSAGES.get(node, "")
        yield f"data: {json.dumps({'type': 'phase', 'node': node, 'status': 'start', 'label': label, 'message': msg}, ensure_ascii=False)}\n\n"
        await asyncio.sleep(_CACHE_REPLAY_STEP_SEC)
        yield f"data: {json.dumps({'type': 'step', 'node': node, 'status': 'done', 'label': label})}\n\n"
    errors = [
        {"agent": e.get("agent", "unknown"), "error": str(e.get("error", ""))[:200], "user_message": e.get("user_message", ""), "icon": e.get("icon", "")}
        for e in (cached.get("agent_errors") or [])
    ]
    yield f"data: {json.dumps({'type': 'done', 'report': cached.get('report') or '', 'errors': errors, 'reflection_passed': cached.get('reflection_passed', False), 'record_id': cached.get('record_id'), 'data_sources': cached.get('data_sources', []), 'followup_questions': cached.get('followup_questions', []), 'supervisor_plan': cached.get('supervisor_plan')}, ensure_ascii=False)}\n\n"


async def _stream_graph(
    question: str,
    user_id: int | None,
    store_ids: list[str] | None = None,
    session_id: str | None = None,
    skip_reflection: bool = False,
) -> AsyncGenerator[str, None]:
    """执行分析图并产生 SSE 事件流。

    V3：支持多轮对话上下文注入和追问建议生成。
    V4.6.3: skip_reflection —— 对照实验参数，跳过质检与重试。
    """
    # 重置 Token 累计（为本次分析清空上次的残留）
    reset_task_tokens()

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
    display_question = resolved_question   # 原始问题（不带 hint），用于展示和存库
    processed_question = _inj_rank(resolved_question)

    initial_state = {
        "question": processed_question,
        "original_question": display_question,
        "user_id": user_id,
        "store_ids": store_ids,
        "session_id": session_id,
        "trace_id": trace_id,
        "conversation_context": conversation_context,
        "is_followup": is_followup,
        "resolved_question": resolved_question if is_followup else None,
        "skip_reflection": skip_reflection,
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
    combined_stream = _with_heartbeat(
        graph.astream(initial_state, stream_mode=["updates", "custom", "values"]),
    )
    async for item in combined_stream:
        # 心跳为完整 SSE 字符串，直接透传保活；图事件为 (mode, chunk) 元组
        if isinstance(item, str):
            yield item
            continue
        mode, chunk = item
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

    # V4.5/V4.6: 流式结果写入 Redis 缓存（相同问题 30 分钟内秒回）
    # V4.6.3: 对照实验不写缓存（避免污染生产缓存，键无 skip 标记会误命中）
    if report and not skip_reflection:
        try:
            _cache_payload = json.dumps({
                "record_id": record_id,
                "report": report,
                "reflection_passed": reflection_passed,
                "reflection_feedback": final_state.get("reflection_feedback"),
                "agent_errors": [],
                "data_sources": final_state.get("data_sources", []),
                "followup_questions": final_state.get("followup_questions", []),
                "supervisor_plan": final_state.get("supervisor_plan"),
                "completed_nodes": sorted(_started_nodes),  # V4.6: 实际执行节点，重放精确还原进度条
            }, ensure_ascii=False)
            from app.database.redis import get_redis
            _rc = get_redis()
            await _rc.setex(_analysis_cache_key(user_id, "", store_ids or [], session_id, question), CACHE_TTL_SEC, _cache_payload)
            # V4.6: 无 session 别名键，供流式缓存快速通道跨会话命中
            await _rc.setex(_analysis_cache_key(user_id, "", store_ids or [], "", question), CACHE_TTL_SEC, _cache_payload)
        except Exception:
            pass  # 缓存写入失败不影响主流程

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

    # V4.5: 原始数据注入已通过 data_sources 字段实现（含 raw_data 和 row_count），
    # 前端可直接从 AnalysisResponse.data_sources 渲染完整数据表，
    # 无需在报告中搜索标记再追加。
    _sp = final_state.get("supervisor_plan")
    yield f"data: {json.dumps({'type': 'done', 'report': report, 'errors': [{'agent': e.get('agent','unknown'), 'error': str(e.get('error',''))[:200], 'user_message': e.get('user_message',''), 'icon': e.get('icon','')} for e in errors], 'reflection_passed': reflection_passed, 'record_id': record_id, 'data_sources': final_state.get('data_sources', []), 'followup_questions': final_state.get('followup_questions', []), 'supervisor_plan': _sp}, ensure_ascii=False)}\n\n"


@router.post("/analyze-stream", summary="流式分析（SSE 实时推送）")
async def analyze_stream(
    request: Request,
    req: AnalysisRequest,
    user: dict = Depends(require_permission("analysis:create")),
    _: None = Depends(rate_limit),
):
    """提交问题并通过 Server-Sent Events 实时推送分析进度。

    事件类型：
    - phase: 节点开始执行（type=phase, node=..., label=...）
    - step:  节点执行完成（type=step, node=..., label=...）
    - done:  最终结果（type=done, report=..., reflection_passed=...）

    浏览器可用 EventSource 接收，前端进度条实时展示 9 步分析状态。
    """
    store_ids = await get_user_store_ids(user["user_id"])

    # ── V4.6: 缓存命中快速通道 ──
    # 相同问题（同用户/租户/门店范围）10 分钟内直接重放缓存报告，不触发 LLM。
    # 键不含 session_id：不同会话中的首次提问可共享结果；多轮追问跳过（避免丢失会话上下文）。
    # V4.6.3: 对照实验（skip_reflection）绕过缓存，保证每次真实执行。
    cached: dict | None = None
    if not req.skip_reflection:
        try:
            if not req.session_id or not await ContextManager(req.session_id).is_followup(req.question):
                from app.database.redis import get_redis
                _hit = await get_redis().get(
                    _analysis_cache_key(user["user_id"], user.get("tenant_id", ""), store_ids, "", req.question)
                )
                if _hit:
                    cached = json.loads(_hit)
        except Exception:
            cached = None  # 缓存不可用/异常 → 走完整分析链路
    if cached and cached.get("report"):
        logger.info("流式缓存命中，快速重放", question=req.question[:80])
        return StreamingResponse(
            _replay_cached_stream(cached),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "Connection": "keep-alive", "X-Accel-Buffering": "no"},
        )

    # V4.5: SSE 流式超时保护（420s，与 /analyze 同步端点一致）
    async def _timeout_wrapper():
        try:
            async with asyncio.timeout(420):
                async for item in _stream_graph(req.question, user["user_id"], store_ids, req.session_id, req.skip_reflection):
                    yield item
        except asyncio.TimeoutError:
            logger.warning("SSE 流式分析超时")
            yield json.dumps({"type": "done", "report": None, "errors": [{"agent": "system", "error": "分析链路超时，请简化问题后重试"}], "reflection_passed": False}) + "\n"
    return StreamingResponse(
        _timeout_wrapper(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
