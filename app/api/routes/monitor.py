"""AI 质量监控仪表板 API — 聚合展示 Agent 表现趋势。

从 agent_trace_events、user_feedback、analysis_history 三张表中
提取 AI PM 最关心的 5 个核心指标，支持按时间范围筛选。
"""

import json
from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text

from app.api.dependencies import require_permission
from app.database.connection import get_session
from app.database.redis import get_redis
from app.logging_config import get_logger

router = APIRouter(prefix="/monitor", tags=["质量监控"])
logger = get_logger("eia.api.monitor")


import re

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_ALLOWED_TIME_COLS = {"created_at", "create_time"}


def _parse_date(s: str) -> date:
    """安全地将 YYYY-MM-DD 字符串转为 date 对象。"""
    if not _DATE_RE.match(s):
        raise ValueError(f"无效日期格式: {s}，应为 YYYY-MM-DD")
    return datetime.strptime(s, "%Y-%m-%d").date()


def _time_filter(days: int, start_date: str | None, end_date: str | None, col: str = "created_at") -> tuple[str, dict]:
    """构造安全的 SQL 时间过滤条件和参数。

    Args:
        days: 天数 fallback。
        start_date: 开始日期 YYYY-MM-DD。
        end_date: 结束日期 YYYY-MM-DD。
        col: 时间列名（analysis_history 用 create_time，agent_trace_events 用 created_at）。

    Returns:
        (sql_fragment, params_dict)。优先级: start_date > days。
    """
    if col not in _ALLOWED_TIME_COLS:
        raise ValueError(f"\u4e0d\u5141\u8bb8\u7684\u65f6\u95f4\u5217: {col}")
    if start_date:
        sd = _parse_date(start_date)
        if end_date:
            ed = _parse_date(end_date)
            return f"{col} >= :sd AND {col} < :ed", {"sd": sd, "ed": ed}
        return f"{col} >= :sd", {"sd": sd}
    return f"{col} >= NOW() - (:d || ' days')::INTERVAL", {"d": str(days)}


def _calc_period_days(days: int, start_date: str | None, end_date: str | None) -> int:
    """计算时间范围的实际天数（用于描述和成本分摊）。"""
    if start_date:
        s = _parse_date(start_date)
        e = _parse_date(end_date) if end_date else date.today()
        if e < s:
            raise ValueError(f"start_date ({start_date}) 晚于 end_date ({end_date or date.today()})")
        return max((e - s).days, 1)
    return days


# 质检失败原因中文名（reflection_issues JSON 里的 category）
_QC_ISSUE_CN = {"consistency": "一致性", "logic": "逻辑", "actionability": "可操作性", "completeness": "完整性"}


def _reflection_error_text(question: str, issues) -> str:
    """把「质检未过」记录拼成可读的错误摘要，展示在最近错误列表。

    质检不过不抛异常（reflection_agent 内部吞掉后返回 reflection_passed=False），
    只落在 analysis_history.reflection_issues 里，这里还原为人类可读文本。
    """
    counts: dict[str, int] = {}
    first_desc = ""
    for item in issues or []:
        if not isinstance(item, dict):
            continue
        cat = item.get("category") or "other"
        counts[cat] = counts.get(cat, 0) + 1
        if not first_desc:
            first_desc = (item.get("description") or "").strip()
    cat_str = ", ".join(f"{_QC_ISSUE_CN.get(c, c)}×{n}" for c, n in counts.items()) or "无具体问题记录"
    q = (question or "").strip().replace("\n", " ")
    parts = [f"质检未通过[{cat_str}]"]
    if q:
        parts.append(f"「{q[:60]}」")
    if first_desc:
        parts.append(first_desc[:120])
    return "｜".join(parts)


@router.get("/errors", summary="Agent 错误日志")
async def error_log(
    days: int = Query(7, ge=1, le=365),
    start_date: str | None = Query(None, description="开始日期 YYYY-MM-DD，优先于 days"),
    end_date: str | None = Query(None, description="结束日期 YYYY-MM-DD，需与 start_date 同时使用"),
    limit: int = Query(50, ge=1, le=200),
    user: dict = Depends(require_permission("alert:view")),
):
    """返回最近 Agent 执行错误的详细日志。

    两类错误合并展示（按时间倒序）：
      1. 技术异常 —— agent_trace_events.error 非空（节点抛异常）
      2. 质检未过 —— analysis_history.reflection_passed = false（质量失败，V4.6.2 并入）
    """
    try:
        time_sql, time_params = _time_filter(days, start_date, end_date)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))
    async with get_session() as session:
        # ── 1. 技术异常（原逻辑：节点抛异常才记录） ──
        result = await session.execute(text(f"""
            SELECT node_name, error, elapsed_ms, created_at, session_id
            FROM agent_trace_events
            WHERE error IS NOT NULL
              AND {time_sql}
            ORDER BY created_at DESC
            LIMIT :l
        """), {**time_params, "l": limit})
        errors = [
            {
                "time": row.created_at.isoformat() if row.created_at else "",
                "agent": row.node_name,
                "error": row.error[:300] if row.error else "",
                "elapsed_ms": row.elapsed_ms,
                "session": row.session_id or "",
            }
            for row in result.fetchall()
        ]
        agg_result = await session.execute(text(f"""
            SELECT node_name, COUNT(*) as cnt
            FROM agent_trace_events
            WHERE error IS NOT NULL
              AND {time_sql}
            GROUP BY node_name ORDER BY cnt DESC
        """), time_params)
        by_agent = {row.node_name: row.cnt for row in agg_result.fetchall()}

        # ── 2. 质检未过（质量失败，按 create_time 过滤） ──
        ah_sql, ah_params = _time_filter(days, start_date, end_date, col="create_time")
        qc_result = await session.execute(text(f"""
            SELECT question, reflection_issues, create_time
            FROM analysis_history
            WHERE reflection_passed = false
              AND {ah_sql}
            ORDER BY create_time DESC
            LIMIT :l
        """), {**ah_params, "l": limit})
        for row in qc_result.fetchall():
            issues = row.reflection_issues
            if isinstance(issues, str):
                try:
                    issues = json.loads(issues)
                except Exception:
                    issues = None
            errors.append({
                "time": row.create_time.isoformat() if row.create_time else "",
                "agent": "reflection_agent",
                "error": _reflection_error_text(row.question, issues)[:300],
                "elapsed_ms": None,
                "session": "",
            })
        # 质检未过总数（不受 limit 影响，用于 by_agent 统计）
        qc_total = (await session.execute(text(f"""
            SELECT COUNT(*) FROM analysis_history
            WHERE reflection_passed = false AND {ah_sql}
        """), ah_params)).scalar()
        if qc_total:
            by_agent["reflection_agent"] = by_agent.get("reflection_agent", 0) + qc_total

        # 合并后按时间倒序，截断到 limit
        errors.sort(key=lambda e: e["time"], reverse=True)
        errors = errors[:limit]

    return {"period_days": _calc_period_days(days, start_date, end_date), "total_errors": len(errors), "by_agent": by_agent, "errors": errors}


@router.get("/reflection-fallback", summary="解析兜底报告明细")
async def reflection_fallback_list(
    days: int = Query(30, ge=1, le=365),
    start_date: str | None = Query(None, description="开始日期 YYYY-MM-DD，优先于 days"),
    end_date: str | None = Query(None, description="结束日期 YYYY-MM-DD，需与 start_date 同时使用"),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(require_permission("alert:view")),
):
    """返回「解析兜底」报告明细（质检未返回结构化结果、被乐观放行的记录）。

    兜底标记：reflection_issues JSON 含 "Reflection did not return structured result"。
    这类报告的质量未经质检验证，是监控看板上唯一不可见的质量盲区，
    前端从 hero 卡片「解析兜底 N 条」点击下钻到本列表。
    """
    try:
        ah_sql, ah_params = _time_filter(days, start_date, end_date, col="create_time")
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))

    _FALLBACK_MARK = "%Reflection did not return structured result%"
    async with get_session() as session:
        total = (await session.execute(text(f"""
            SELECT COUNT(*)
            FROM analysis_history
            WHERE reflection_issues::text LIKE :mark AND {ah_sql}
        """), {**ah_params, "mark": _FALLBACK_MARK})).scalar() or 0
        rows = (await session.execute(text(f"""
            SELECT id, question, create_time
            FROM analysis_history
            WHERE reflection_issues::text LIKE :mark AND {ah_sql}
            ORDER BY create_time DESC
            LIMIT :l
        """), {**ah_params, "mark": _FALLBACK_MARK, "l": limit})).fetchall()

    return {
        "period_days": _calc_period_days(days, start_date, end_date),
        "total": total,
        "entries": [
            {
                "id": row.id,
                "question": (row.question or "")[:200],
                "time": row.create_time.isoformat() if row.create_time else "",
            }
            for row in rows
        ],
    }


@router.get("/overview", summary="AI 质量总览")
async def quality_overview(
    days: int = Query(30, ge=1, le=365, description="统计最近 N 天"),
    start_date: str | None = Query(None, description="开始日期 YYYY-MM-DD，优先于 days"),
    end_date: str | None = Query(None, description="结束日期 YYYY-MM-DD，需与 start_date 同时使用"),
    user: dict = Depends(require_permission("alert:view")),
):
    """返回 AI 产品质量核心指标。

    五大核心指标：
      - 各 Agent 错误率排行
      - P50/P95 延迟
      - Reflection 通过率
      - 用户好评率
      - 每日分析量趋势
    """
    try:
        ah_sql, ah_params = _time_filter(days, start_date, end_date, col="create_time")
        ae_sql, ae_params = _time_filter(days, start_date, end_date, col="created_at")
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))

    period_days = _calc_period_days(days, start_date, end_date)

    # V4.4: Redis 缓存（60 秒 TTL），避免每次打开监控页都跑 11 个 SQL
    _cache_key = f"monitor:overview:{days}:{start_date or ''}:{end_date or ''}"
    try:
        _rc = get_redis()
        _cached = await _rc.get(_cache_key)
        if _cached:
            import json as _json
            return _json.loads(_cached)
    except Exception:
        pass  # 缓存miss时降级为查库

    try:
        async with get_session() as session:
            # 1. Reflection 通过率 + 分析总量
            # V4.1: 用 NULLIF 防止 analysis_history 为空时除零错误
            # V4.6.3: 三态口径（DB 能力边界内的最大细分）：
            #   failed   = 质检未通过（reflection_passed=false）
            #   fallback = 质检解析失败按通过记（reflection_issues 含
            #              "Reflection did not return structured result" 标记，reflection_agent 兜底）
            #   passed   = 通过（含 V4.6.2 起简单查询跳过质检的乐观记过——
            #              DB 无 reflection_feedback 列，skipped 与真过不可区分，如实标注）
            # pass_rate 保持向后兼容（passed/total）。
            reflect = await session.execute(text(f"""
            SELECT
                COUNT(*) as total,
                COUNT(CASE WHEN reflection_passed = true THEN 1 END) as passed,
                COUNT(CASE WHEN reflection_passed = false THEN 1 END) as failed,
                COUNT(CASE WHEN reflection_issues::text LIKE '%Reflection did not return structured result%' THEN 1 END) as fallback,
                ROUND(COUNT(CASE WHEN reflection_passed = true THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0), 1) as pass_rate
            FROM analysis_history
            WHERE {ah_sql}
        """), ah_params)
            r = reflect.fetchone()

            # 2. 各 Agent 错误率排行
            # V4.1: 用 NULLIF 防止 agent_trace_events 为空时除零错误
            # V4.4: 统一 node_name（去掉 _agent 后缀），避免同一 Agent 重复统计
            agent_errors = await session.execute(text(f"""
            SELECT
                CASE
                    WHEN node_name LIKE '%_agent' THEN LEFT(node_name, LENGTH(node_name) - 6)
                    ELSE node_name
                END as agent,
                COUNT(*) as total_runs,
                COUNT(CASE WHEN error IS NOT NULL THEN 1 END) as error_count,
                ROUND(COUNT(CASE WHEN error IS NOT NULL THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0), 1) as error_rate,
                ROUND(AVG(elapsed_ms)) as avg_ms,
                ROUND(MAX(elapsed_ms)) as max_ms
            FROM agent_trace_events
            WHERE {ae_sql}
            GROUP BY 1
            ORDER BY error_rate DESC
        """), ae_params)
            agents = [
                {
                    "agent": row.agent,
                    "total_runs": row.total_runs,
                    "error_count": row.error_count,
                    "error_rate": row.error_rate,
                    "avg_ms": row.avg_ms,
                    "max_ms": row.max_ms,
                }
                for row in agent_errors.fetchall()
            ]

            # 3. 异常会话统计（V4.6.6）—— 技术异常事件基本为超时（SQL 错误被 Agent 内部自愈，
            #    不落 trace），口径如实标注：异常会话 = 至少一次 error 事件的会话，多数经重试自愈仍产出报告
            abnormal_row = (await session.execute(text(f"""
                SELECT
                    COUNT(*) FILTER (WHERE error IS NOT NULL) AS abnormal_events,
                    COUNT(DISTINCT session_id) FILTER (WHERE error IS NOT NULL AND session_id IS NOT NULL) AS abnormal_sessions,
                    COUNT(DISTINCT session_id) FILTER (WHERE session_id IS NOT NULL) AS total_trace_sessions
                FROM agent_trace_events
                WHERE {ae_sql}
            """), ae_params)).fetchone()
            abnormal_sessions = abnormal_row.abnormal_sessions or 0
            abnormal_events = abnormal_row.abnormal_events or 0
            total_trace_sessions = abnormal_row.total_trace_sessions or 0
            abnormal_rate = round(abnormal_sessions * 100.0 / total_trace_sessions, 1) if total_trace_sessions else 0

            # 4. P50/P95 延迟
            latency = await session.execute(text(f"""
                SELECT
                    ROUND(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY elapsed_ms)) as p50,
                    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY elapsed_ms)) as p95
                FROM agent_trace_events
                WHERE {ae_sql}
            """), ae_params)
            lat = latency.fetchone()

            # 5. 反馈统计（user_feedback 用 created_at）
            uf_sql, uf_params = _time_filter(days, start_date, end_date, col="created_at")
            feedback = await session.execute(text(f"""
                SELECT
                    COUNT(*) as total,
                    COUNT(CASE WHEN rating = 'helpful' THEN 1 END) as helpful,
                    ROUND(COUNT(CASE WHEN rating = 'helpful' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0), 1) as helpful_pct
                FROM user_feedback
                WHERE {uf_sql}
            """), uf_params)
            fb = feedback.fetchone()

            # 6. 每日分析量
            daily = await session.execute(text(f"""
                SELECT DATE(create_time) as dt, COUNT(*) as cnt
                FROM analysis_history
                WHERE {ah_sql}
                GROUP BY dt ORDER BY dt
            """), ah_params)
            daily_trend = [{"date": str(row.dt), "count": row.cnt} for row in daily.fetchall()]

            total_analyses = r.total

            # 7. 真实成本（从 analysis_history.llm_cost 汇总）
            cost_row = (await session.execute(text(f"""
                SELECT COALESCE(SUM(llm_cost), 0) as total_cost,
                       COUNT(*) as n
                FROM analysis_history
                WHERE {ah_sql}
            """), ah_params)).fetchone()
            total_cost = float(cost_row.total_cost) if cost_row else 0.0
            total_count = cost_row.n if cost_row else 0
            # V4.6.6: 单任务平均成本（全部分析口径，含 llm_cost 为 NULL 的 0 成本记录）
            avg_cost_per_task = round(total_cost / total_count, 4) if total_count else 0

            # 8. Reflection 失败原因分布（从 reflection_issues JSON 中统计）
            issues_row = (await session.execute(text(f"""
                SELECT
                    COALESCE(COUNT(CASE WHEN reflection_issues::jsonb @> '[{{"category":"consistency"}}]' THEN 1 END), 0) as consistency,
                    COALESCE(COUNT(CASE WHEN reflection_issues::jsonb @> '[{{"category":"logic"}}]' THEN 1 END), 0) as logic,
                    COALESCE(COUNT(CASE WHEN reflection_issues::jsonb @> '[{{"category":"actionability"}}]' THEN 1 END), 0) as actionability,
                    COALESCE(COUNT(CASE WHEN reflection_issues::jsonb @> '[{{"category":"completeness"}}]' THEN 1 END), 0) as completeness
                FROM analysis_history
                WHERE reflection_passed = false
                  AND {ah_sql}
            """), ah_params)).fetchone()

            reflection_issue_dist = {
                "consistency": issues_row.consistency if issues_row else 0,
                "logic": issues_row.logic if issues_row else 0,
                "actionability": issues_row.actionability if issues_row else 0,
                "completeness": issues_row.completeness if issues_row else 0,
            }

            # ── 8. Token 消耗趋势（每日） ──
            token_trend_rows = (await session.execute(text(f"""
                SELECT
                    DATE(create_time) as dt,
                    COALESCE(SUM(input_tokens), 0) as in_tokens,
                    COALESCE(SUM(output_tokens), 0) as out_tokens,
                    COALESCE(SUM(llm_cost), 0) as cost
                FROM analysis_history
                WHERE {ah_sql}
                GROUP BY dt ORDER BY dt
            """), ah_params)).fetchall()
            token_trend = [
                {"date": str(row.dt), "input_tokens": row.in_tokens, "output_tokens": row.out_tokens, "cost": round(float(row.cost), 4)}
                for row in token_trend_rows
            ]

            # ── 9. 重试率 + 修复成功率 ──
            # 注意：report_runs 只统计 report_agent 事件。正常会话有 report + reflection
            # 两条事件，若把两者都计入，任何会话都会 report_runs>=2，重试率恒为 100%。
            retry_rows = (await session.execute(text(f"""
                SELECT session_id,
                    COUNT(*) FILTER (WHERE node_name = 'report_agent') as report_runs,
                    bool_or(CASE WHEN node_name = 'reflection_agent' AND error IS NULL THEN true ELSE false END) as reflection_ok
                FROM agent_trace_events
                WHERE node_name IN ('report_agent', 'reflection_agent') AND {ae_sql}
                GROUP BY session_id
            """), ae_params)).fetchall()
            total_sessions = 0; retry_sessions = 0; fixed_after_retry = 0
            for row in retry_rows:
                if not row.session_id: continue
                total_sessions += 1
                if row.report_runs >= 2:
                    retry_sessions += 1
                    if row.reflection_ok: fixed_after_retry += 1
            retry_rate = round(retry_sessions * 100.0 / total_sessions, 1) if total_sessions else 0
            fix_rate = round(fixed_after_retry * 100.0 / retry_sessions, 1) if retry_sessions else 0

            # ── 10. 完整分析耗时分布 ──
            duration_rows = (await session.execute(text(f"""
                SELECT session_id, MAX(elapsed_ms) - MIN(elapsed_ms) as total_ms
                FROM agent_trace_events
                WHERE session_id IS NOT NULL AND {ae_sql}
                GROUP BY session_id HAVING MAX(elapsed_ms) - MIN(elapsed_ms) > 0
            """), ae_params)).fetchall()
            durations = sorted([row.total_ms for row in duration_rows if row.total_ms])
            total_dc = len(durations)
            avg_duration = round(sum(durations) / total_dc, 0) if total_dc else 0
            def _pct(arr, p):
                if not arr: return 0
                idx = int(len(arr) * p / 100)
                return round(arr[min(idx, len(arr)-1)], 0)
            p50_duration = _pct(durations, 50)
            p90_duration = _pct(durations, 90)
            p95_duration = _pct(durations, 95)

            # ── 11. 追问率 ──
            fq_row = (await session.execute(text(f"""
                SELECT COUNT(*) as total,
                    COUNT(CASE WHEN followup_questions IS NOT NULL AND followup_questions != '' AND followup_questions != '[]' THEN 1 END) as has_fq
                FROM analysis_history WHERE {ah_sql}
            """), ah_params)).fetchone()
            followup_rate = round(fq_row.has_fq * 100.0 / fq_row.total, 1) if fq_row.total > 0 else 0

            _result = {
                "period_days": period_days,
                "total_analyses": total_analyses,
                "total_issues_reports": r.total - (r.passed or 0) if r.total > 0 else 0,
                "reflection_pass_rate": r.pass_rate if r.total > 0 else 0,
                # V4.6.3: 三态口径（未过/解析兜底），与离线评估对齐
                "reflection_failed": r.failed or 0,
                "reflection_fallback": r.fallback or 0,
                "reflection_issue_dist": reflection_issue_dist,
                "feedback_helpful_rate": fb.helpful_pct if fb.total > 0 else 0,
                "latency_p50_ms": lat.p50 or 0,
                "latency_p95_ms": lat.p95 or 0,
                # V4.6.6: 异常会话（技术异常=超时，多数经重试自愈仍产出报告）+ 单任务平均成本
                "abnormal_sessions": abnormal_sessions,
                "abnormal_events": abnormal_events,
                "abnormal_rate": abnormal_rate,
                "avg_cost_per_task": avg_cost_per_task,
                "estimated_daily_cost": round(total_cost / period_days, 4),
                "estimated_monthly_cost": round(total_cost / period_days * 30, 4),
                "agents": agents,
                "daily_trend": daily_trend,
                "token_trend": token_trend,
                "retry_rate": retry_rate,
                "fix_rate": fix_rate,
                "retry_count": retry_sessions,
                "total_sessions": total_sessions,
                "avg_duration_ms": avg_duration,
                "p50_duration_ms": p50_duration,
                "p90_duration_ms": p90_duration,
                "p95_duration_ms": p95_duration,
                "followup_rate": followup_rate,
                "health": {
                    "reflection": "✅" if (r.pass_rate or 0) >= 80 else "⚠️",
                    "latency": "✅" if (lat.p95 or 0) < 60000 else "⚠️",
                    "feedback": "✅" if (fb.helpful_pct or 0) >= 80 else "⚠️",
                },
            }

        # V4.4: 缓存结果 60 秒
        try:
            import json as _json
            await _rc.setex(_cache_key, 60, _json.dumps(_result, ensure_ascii=False, default=str))
        except Exception:
            pass
        return _result

    except Exception as e:
        logger.exception("质量监控概览异常: %s", e)
        raise


@router.get("/feedback", summary="User feedback detail")
async def feedback_detail(
    days: int = Query(30, ge=1, le=365),
    rating: str | None = Query(None, description="Filter: helpful / inaccurate / not_relevant"),
    limit: int = Query(20, ge=1, le=100),
    user: dict = Depends(require_permission("alert:view")),
):
    try:
        try:
            ah_sql, ah_params = _time_filter(days, None, None, col="created_at")
        except ValueError as e:
            from fastapi import HTTPException
            raise HTTPException(status_code=400, detail=str(e))

        async with get_session() as session:
            stats = await session.execute(
            text("SELECT COUNT(*) as total, COUNT(CASE WHEN rating = 'helpful' THEN 1 END) as helpful, ROUND(COUNT(CASE WHEN rating = 'helpful' THEN 1 END) * 100.0 / NULLIF(COUNT(*), 0), 1) as helpful_pct FROM user_feedback WHERE " + ah_sql), ah_params
        )
        st = stats.fetchone()

        rating_filter = ""
        params = dict(ah_params)
        params["l"] = limit
        if rating:
            rating_filter = "AND f.rating = :rating"
            params["rating"] = rating

        entries = await session.execute(
            text("SELECT f.id, f.rating, f.reason, f.created_at, a.question, a.reflection_passed FROM user_feedback f LEFT JOIN analysis_history a ON f.analysis_history_id = a.id WHERE f.created_at >= NOW() - (:d || ' days')::INTERVAL " + rating_filter + " ORDER BY f.created_at DESC LIMIT :l"), params
        )
        entries_list = [
            {
                "id": row.id,
                "rating": row.rating,
                "reason": row.reason or "",
                "created_at": row.created_at.isoformat() if row.created_at else "",
                "question": row.question[:200] if row.question else "",
                "reflection_passed": row.reflection_passed if row.reflection_passed is not None else False,
            }
            for row in entries.fetchall()
        ]

        return {
            "period_days": _calc_period_days(days, None, None),
            "total_feedback": st.total,
            "helpful_count": st.helpful,
            "helpful_rate": st.helpful_pct if st.total > 0 else 0,
            "entries": entries_list,
        }

    except Exception as e:
        logger.exception("反馈详情查询异常: %s", e)
        from fastapi import HTTPException
        raise HTTPException(status_code=500, detail=f"Feedback query error: {e}")
