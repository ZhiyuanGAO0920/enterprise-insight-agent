"""流式工具 —— safe_get_stream_writer 提供 LangGraph 上下文外的降级兜底。"""

from app.logging_config import get_logger

logger = get_logger("eia.stream")


def _noop_writer(msg: dict):
    """LangGraph 运行时外部的空操作 writer 降级。"""
    pass


def safe_get_stream_writer():
    """获取 LangGraph 流式 writer，在 LangGraph 上下文外返回 noop 降级。

    所有 Agent 节点都应使用此函数而非直接调用 get_stream_writer()，
    以确保在单元测试或非标准调用场景中不会因 RuntimeError 崩溃。
    """
    try:
        from langgraph.config import get_stream_writer as _get_stream_writer
        return _get_stream_writer()
    except (RuntimeError, ImportError, AttributeError):
        logger.debug("在 LangGraph 运行时外调用 get_stream_writer，使用 noop 降级")
        return _noop_writer
