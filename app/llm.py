"""共享 LLM 工厂 —— 模型配置的唯一来源 + 成本追踪。

所有 Agent 从此处导入其 LLM 实例。切换模型只需
修改 DEEPSEEK_* 环境变量。

DeepSeek API 兼容 OpenAI，因此我们使用 langchain-openai 的
ChatOpenAI，将 base_url 指向 api.deepseek.com。

代理隔离：
  使用 trust_env=False 的 httpx.AsyncClient 确保 DeepSeek API 请求
  不被本地代理（Clash/V2Ray/Verge）拦截，同时不影响进程中其他 HTTP 库。

超时 & 重试：
  - request_timeout=120s 防止 LLM 调用无限挂起
  - max_retries=2 利用 OpenAI SDK 内置指数退避自动重试 5xx 错误

成本追踪：
  CostTracker 使用 threading.Lock + 共享 dict 做累计。
  因 LangGraph 的 Send 并行分支创建独立 asyncio Task，
  ContextVar 按 task 隔离导致并行场景下累加值丢失。
  故采用 threading.Lock 保护共享 dict，确保跨 task 正确累加。

  每次分析开始前调用 reset_task_tokens()，结束时 get_task_tokens() 获取
  本次分析的总 Token 消耗和成本，写入 analysis_history.llm_cost。
"""

import contextvars
import threading
from langchain_core.callbacks import BaseCallbackHandler
from langchain_openai import ChatOpenAI

from app.config import get_settings
from app.logging_config import get_logger

settings = get_settings()

# LLM 模块的日志器，用于 fallback 切换、调用记录等
logger = get_logger("eia.llm")

# ---------------------------------------------------------------------------
# 成本追踪（共享可变对象 + Lock，可跨 asyncio Task 正确累加）
# ---------------------------------------------------------------------------

cost_logger = get_logger("eia.llm.cost")  # 使用标准 logger（structlog 会代理此 name）

# DeepSeek 定价（¥/百万 tokens）
DEEPSEEK_INPUT_PRICE = 1.0
DEEPSEEK_OUTPUT_PRICE = 2.0

# 使用共享 dict + threading.Lock 而非 ContextVar。
# ContextVar 在 asyncio task 创建时复制，并行 Agent 各有一份副本，
# save_memory_node 读取时看到的永远是初始值 0。
# 共享 dict 则所有 task 写入同一个对象，Lock 保证线程安全。
_token_usage: dict[str, int] = {"input": 0, "output": 0}
_token_lock = threading.Lock()


class CostTracker(BaseCallbackHandler):
    """追踪单次分析中的 Token 消耗和成本。

    使用 threading.Lock 保护共享 _token_usage 字典，
    确保 LangGraph 并行 Send 分支中的 LLM 调用都能正确累积。
    """

    def on_llm_end(self, response, **kwargs):
        try:
            llm_output = getattr(response, "llm_output", None)
            if llm_output:
                token_usage = llm_output.get("token_usage", {})
                input_tokens = token_usage.get("prompt_tokens", 0)
                output_tokens = token_usage.get("completion_tokens", 0)
                with _token_lock:
                    _token_usage["input"] += input_tokens
                    _token_usage["output"] += output_tokens
                    cost_logger.debug("token_tracking",
                        input_tokens=_token_usage["input"],
                        output_tokens=_token_usage["output"],
                        cost=(_token_usage["input"] * 1.0 + _token_usage["output"] * 2.0) / 1_000_000)
        except Exception as _e:
            cost_logger.warning("token_tracking_error", error=str(_e))

    def on_llm_error(self, error, **kwargs):
        pass


def reset_task_tokens():
    """重置本次分析的 Token 计数器（在每次分析前调用）。"""
    with _token_lock:
        _token_usage["input"] = 0
        _token_usage["output"] = 0


def get_task_tokens() -> tuple[int, int, float]:
    """获取本次分析累计的 Token 消耗和估算成本。

    Returns:
        (input_tokens, output_tokens, estimated_cost)
        成本按 ¥1/Mtok 输入、¥2/Mtok 输出估算。
    """
    with _token_lock:
        inp = _token_usage["input"]
        out = _token_usage["output"]
    cost = (inp * DEEPSEEK_INPUT_PRICE + out * DEEPSEEK_OUTPUT_PRICE) / 1_000_000
    return inp, out, round(cost, 6)


# ---------------------------------------------------------------------------
# 共享 HTTP 客户端单例（防止 per-call 创建泄漏连接）
# ---------------------------------------------------------------------------
import httpx

# Force-disable all proxy detection — avoid Windows proxy / system proxy interception
_http_client = httpx.Client(trust_env=False, follow_redirects=True, proxy=None, timeout=httpx.Timeout(120.0, connect=30.0))
_http_async_client = httpx.AsyncClient(trust_env=False, proxy=None, timeout=httpx.Timeout(120.0, connect=30.0))
_cost_tracker = CostTracker()


# ---------------------------------------------------------------------------
# Fixture loader helper
# ---------------------------------------------------------------------------


def _build_chat_openai(
    api_key: str,
    base_url: str,
    model: str,
    temperature: float,
    max_tokens: int,
    max_retries: int = 2,
) -> ChatOpenAI:
    """统一创建 ChatOpenAI 实例，共享 HTTP 客户端和回调。"""
    return ChatOpenAI(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=120,
        max_retries=max_retries,
        openai_api_key=api_key,
        openai_api_base=base_url,
        openai_proxy=None,
        http_client=_http_client,
        http_async_client=_http_async_client,
        callbacks=[_cost_tracker],
        http_socket_options=(),
    )


def _is_fallback_configured() -> bool:
    """检查是否配置了备用 LLM Provider。"""
    return bool(settings.fallback_api_key)


# ---------------------------------------------------------------------------
# Fallback LLM 包装器（透明降级：主 LLM 失败 → 自动切备用）
# ---------------------------------------------------------------------------
# 所有 Agent 通过 create_llm() 获取 LLM，此包装器对它们完全透明。
# 支持 ainvoke / astream / bind_tools 三个接口。


async def _invoke_with_fallback(
    primary_fn, fallback_fn,
    primary_name: str, fallback_name: str,
    messages, **kwargs,
):
    """异步调用主 LLM，失败时切换到备用 LLM。"""
    try:
        logger.info("LLM 调用: %s", primary_name)
        return await primary_fn(messages, **kwargs)
    except Exception as e:
        logger.warning(
            "主 LLM %s 失败 (%s: %.100s)，切换到 %s",
            primary_name, type(e).__name__, str(e), fallback_name,
        )
        return await fallback_fn(messages, **kwargs)


def _invoke_with_fallback_sync(
    primary_fn, fallback_fn,
    primary_name: str, fallback_name: str,
    messages, **kwargs,
):
    """同步调用主 LLM，失败时切换到备用 LLM。"""
    try:
        logger.info("LLM 调用: %s", primary_name)
        return primary_fn(messages, **kwargs)
    except Exception as e:
        logger.warning(
            "主 LLM %s 失败 (%s: %.100s)，切换到 %s",
            primary_name, type(e).__name__, str(e), fallback_name,
        )
        return fallback_fn(messages, **kwargs)


async def _stream_with_fallback(
    primary_stream, fallback_stream,
    primary_name: str, fallback_name: str,
    messages, **kwargs,
):
    """流式调用主 LLM，失败时切换到备用 LLM 重新流式。"""
    tried_fallback = False
    try:
        async for chunk in primary_stream(messages, **kwargs):
            yield chunk
    except Exception as e:
        logger.warning(
            "主 LLM %s 流式失败 (%s: %.100s)，切换到 %s",
            primary_name, type(e).__name__, str(e), fallback_name,
        )
        tried_fallback = True
    if tried_fallback:
        async for chunk in fallback_stream(messages, **kwargs):
            yield chunk


class FallbackLLM:
    """主备 LLM 包装器。实现了 Agent 需要的三个接口：ainvoke / astream / bind_tools。

    当主 LLM（DeepSeek）的调用抛出异常时，自动切换到备用 LLM（MiMo）。
    不对 ChatOpenAI 做完整接口包装，只覆盖 Agent 实际使用的方法。
    """

    def __init__(self, primary: ChatOpenAI, fallback: ChatOpenAI):
        self._primary = primary
        self._fallback = fallback

    async def ainvoke(self, messages, **kwargs):
        return await _invoke_with_fallback(
            self._primary.ainvoke, self._fallback.ainvoke,
            "DeepSeek", "MiMo", messages, **kwargs,
        )

    def invoke(self, messages, **kwargs):
        return _invoke_with_fallback_sync(
            self._primary.invoke, self._fallback.invoke,
            "DeepSeek", "MiMo", messages, **kwargs,
        )

    def astream(self, messages, **kwargs):
        return _stream_with_fallback(
            self._primary.astream, self._fallback.astream,
            "DeepSeek", "MiMo", messages, **kwargs,
        )

    def bind_tools(self, tools, **kwargs):
        return FallbackBoundLLM(
            self._primary.bind_tools(tools, **kwargs),
            self._fallback.bind_tools(tools, **kwargs),
        )


class FallbackBoundLLM:
    """bind_tools 之后的 Fallback 包装器。

    LangChain 的 bind_tools() 返回 RunnableBinding，
    此包装器持有两个 RunnableBinding（主 + 备），ainvoke 时按需 fallback。
    """

    def __init__(self, primary, fallback):
        self._primary = primary
        self._fallback = fallback

    async def ainvoke(self, messages, **kwargs):
        return await _invoke_with_fallback(
            self._primary.ainvoke, self._fallback.ainvoke,
            "DeepSeek", "MiMo", messages, **kwargs,
        )

    def invoke(self, messages, **kwargs):
        return _invoke_with_fallback_sync(
            self._primary.invoke, self._fallback.invoke,
            "DeepSeek", "MiMo", messages, **kwargs,
        )


# ---------------------------------------------------------------------------
# 公开工厂函数
# ---------------------------------------------------------------------------


def create_llm(temperature: float | None = None, max_tokens: int | None = None):
    """创建 LLM 实例。

    如果配置了 FALLBACK_API_KEY，返回 FallbackLLM 包装器（自动主备切换）；
    否则返回普通的 ChatOpenAI 实例（行为与之前完全一致）。

    Args:
        temperature: 覆盖默认 temperature，None 则使用配置值。
        max_tokens: 覆盖默认 max_tokens，None 则使用配置值。

    Returns:
        ChatOpenAI 或 FallbackLLM 实例。
    """
    temp = temperature if temperature is not None else settings.llm_temperature
    mt = max_tokens if max_tokens is not None else settings.llm_max_tokens

    primary = _build_chat_openai(
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        model=settings.deepseek_model_name,
        temperature=temp,
        max_tokens=mt,
        max_retries=2,
    )

    if not _is_fallback_configured():
        return primary

    fallback = _build_chat_openai(
        api_key=settings.fallback_api_key,
        base_url=settings.fallback_base_url,
        model=settings.fallback_model_name,
        temperature=temp,
        max_tokens=mt,
        max_retries=1,
    )

    return FallbackLLM(primary, fallback)
