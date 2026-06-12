"""V4 结构化日志配置 —— structlog + 全链路 trace_id。

所有日志携带标准字段：
  timestamp, level, module, agent_name, session_id, trace_id, user_id, tenant_id

开发环境：彩色控制台输出
生产环境：JSON 格式（LOG_FORMAT=json 时启用）
"""

import logging
import sys
import uuid
from contextvars import ContextVar

import structlog

from app.config import get_settings

# ---------------------------------------------------------------------------
# Context variables —— 线程安全的日志上下文
# ---------------------------------------------------------------------------
trace_id_ctx: ContextVar[str] = ContextVar("trace_id", default="")
session_id_ctx: ContextVar[str] = ContextVar("session_id", default="")
user_id_ctx: ContextVar[int | None] = ContextVar("user_id", default=None)
tenant_id_ctx: ContextVar[int | None] = ContextVar("tenant_id", default=None)
agent_name_ctx: ContextVar[str] = ContextVar("agent_name", default="")


def bind_context(
    trace_id: str = "",
    session_id: str = "",
    user_id: int | None = None,
    tenant_id: int | None = None,
    agent_name: str = "",
) -> None:
    """绑定当前请求/Agent 的上下文变量。"""
    if trace_id:
        trace_id_ctx.set(trace_id)
    if session_id:
        session_id_ctx.set(session_id)
    if user_id is not None:
        user_id_ctx.set(user_id)
    if tenant_id is not None:
        tenant_id_ctx.set(tenant_id)
    if agent_name:
        agent_name_ctx.set(agent_name)


def clear_context() -> None:
    """清除所有上下文变量（请求结束时调用）。"""
    trace_id_ctx.set("")
    session_id_ctx.set("")
    user_id_ctx.set(None)
    tenant_id_ctx.set(None)
    agent_name_ctx.set("")


def new_trace_id() -> str:
    """生成新的 trace_id（短 UUID）。"""
    return uuid.uuid4().hex[:12]


# ---------------------------------------------------------------------------
# structlog 共享处理器
# ---------------------------------------------------------------------------

def _add_context_fields(logger, method_name, event_dict):
    """将 contextvars 中的字段注入每条日志。"""
    tid = trace_id_ctx.get()
    if tid:
        event_dict["trace_id"] = tid
    sid = session_id_ctx.get()
    if sid:
        event_dict["session_id"] = sid
    uid = user_id_ctx.get()
    if uid is not None:
        event_dict["user_id"] = uid
    tnid = tenant_id_ctx.get()
    if tnid is not None:
        event_dict["tenant_id"] = tnid
    aname = agent_name_ctx.get()
    if aname:
        event_dict["agent"] = aname
    return event_dict


def setup_logging() -> None:
    """配置 structlog —— 应用启动时调用一次。

    开发环境：彩色控制台（默认）
    生产环境：设置 LOG_FORMAT=json 启用 JSON 输出
    """
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    log_format = settings.log_format  # console | json

    # 配置标准库 logging 根日志记录器
    root = logging.getLogger()
    root.setLevel(level)
    # 清除已有 handler 避免重复
    root.handlers.clear()

    if log_format == "json":
        # 生产环境：JSON 行输出
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        formatter = logging.Formatter(
            '{"timestamp":"%(asctime)s","level":"%(levelname)s","logger":"%(name)s","message":"%(message)s"}',
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
        handler.setFormatter(formatter)
        root.addHandler(handler)
    else:
        # 开发环境：彩色控制台
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(level)
        formatter = logging.Formatter(
            "%(asctime)s | %(levelname)-5s | %(name)s | %(message)s",
            datefmt="%H:%M:%S",
        )
        handler.setFormatter(formatter)
        root.addHandler(handler)

    # 配置 structlog
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="%Y-%m-%dT%H:%M:%S"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            _add_context_fields,
            structlog.dev.ConsoleRenderer()
            if log_format != "json"
            else structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )


def get_logger(name: str = "eia") -> structlog.stdlib.BoundLogger:
    """获取已配置的 structlog logger。

    用法：
        logger = get_logger(__name__)
        logger.info("分析开始", question=q[:80])

    Args:
        name: logger 名称，建议使用 __name__。

    Returns:
        structlog BoundLogger 实例。
    """
    return structlog.get_logger(name)
