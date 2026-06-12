"""Agent 性能追踪器 —— V4 增强。

为每个 LangGraph 节点提供轻量级执行追踪，支持 trace_id 全链路关联。
将耗时数据记录到数据库用于性能分析。

受 FEATURE_APM 环境变量控制。
"""

import hashlib
import time
from contextlib import asynccontextmanager
from typing import Optional

from sqlalchemy import text

from app.config import get_settings
from app.database.connection import get_session
from app.logging_config import get_logger

logger = get_logger("eia.apm")


class AgentTracer:
    """追踪 Agent 节点的执行情况以进行性能监控。

    V4：trace_id 贯穿全链路，每次追踪事件关联到同一次分析请求。
    """

    def __init__(self, session_id: str = "", question: str = "", trace_id: str = ""):
        self.settings = get_settings()
        self.session_id = session_id
        self.question = question
        self.trace_id = trace_id
        self._records: list[dict] = []

    def _should_trace(self) -> bool:
        return self.settings.feature_apm

    @asynccontextmanager
    async def trace(self, node_name: str):
        """上下文管理器：追踪单个节点的执行。

        用法：
            async with tracer.trace("sales_agent"):
                result = await sales_agent_node(state)
        """
        if not self._should_trace():
            yield
            return

        t0 = time.monotonic()
        error_msg: Optional[str] = None
        try:
            yield
        except Exception as e:
            error_msg = str(e)
            raise
        finally:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            self._records.append({
                "node": node_name,
                "elapsed_ms": elapsed_ms,
                "error": error_msg,
            })
            logger.debug(
                "Agent 节点完成",
                trace_id=self.trace_id,
                node=node_name,
                elapsed_ms=elapsed_ms,
                error=error_msg,
            )

    async def flush(self):
        """将所有记录的追踪事件持久化到数据库。

        非阻塞 —— 静默忽略失败，避免影响主分析流程。
        """
        if not self._should_trace() or not self._records:
            return

        try:
            async with get_session() as session:
                for rec in self._records:
                    await session.execute(
                        text("""
                            INSERT INTO agent_trace_events
                                (session_id, node_name, question_hash, elapsed_ms, error)
                            VALUES
                                (:sid, :node, :qh, :ms, :err)
                        """),
                        {
                            "sid": self.session_id,
                            "node": rec["node"],
                            "qh": int(hashlib.md5(self.question.encode()).hexdigest()[:8], 16),
                            "ms": rec["elapsed_ms"],
                            "err": rec["error"],
                        },
                    )
                await session.commit()
            logger.info(
                "APM 追踪已持久化",
                trace_id=self.trace_id,
                nodes=len(self._records),
            )
        except Exception:
            logger.warning("APM 持久化失败（不影响主流程）", trace_id=self.trace_id, exc_info=True)


# ---------------------------------------------------------------------------
# 全局追踪器访问
# ---------------------------------------------------------------------------

_tracer: Optional[AgentTracer] = None


def set_tracer(tracer: AgentTracer) -> None:
    """设置当前分析的追踪器（在每次分析开始时调用）。"""
    global _tracer
    _tracer = tracer


def get_tracer() -> Optional[AgentTracer]:
    """获取当前分析的追踪器。"""
    return _tracer
