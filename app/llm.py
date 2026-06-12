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
"""

import logging

import httpx
from langchain_core.callbacks import BaseCallbackHandler
from langchain_openai import ChatOpenAI

from app.config import get_settings

settings = get_settings()

# ---------------------------------------------------------------------------
# 成本追踪回调
# ---------------------------------------------------------------------------

cost_logger = logging.getLogger("eia.llm.cost")

# DeepSeek 定价（¥/百万 tokens）
# deepseek-chat: 输入 ¥1/MTok, 输出 ¥2/MTok
DEEPSEEK_INPUT_PRICE = 1.0
DEEPSEEK_OUTPUT_PRICE = 2.0


class CostTracker(BaseCallbackHandler):
    """记录每次 LLM 调用的 Token 消耗和成本估算。

    通过 langchain 回调机制注入，每次 LLM 调用结束后自动触发。
    输出到 eia.llm.cost 日志通道，可在终端中实时观察。
    """

    def on_llm_end(self, response, **kwargs) -> None:
        """LLM 调用结束时的回调 —— 记录 Token 用量和成本。"""
        try:
            llm_output = response.llm_output or {}
            token_usage = llm_output.get("token_usage", {})
            input_tokens = token_usage.get("prompt_tokens", 0)
            output_tokens = token_usage.get("completion_tokens", 0)

            if input_tokens == 0 and output_tokens == 0:
                return

            cost = (
                input_tokens * DEEPSEEK_INPUT_PRICE
                + output_tokens * DEEPSEEK_OUTPUT_PRICE
            ) / 1_000_000

            cost_logger.info(
                "¥%.5f | input=%d | output=%d | total=%d",
                cost,
                input_tokens,
                output_tokens,
                input_tokens + output_tokens,
            )
        except Exception:
            pass  # 成本追踪失败不影响主流程（由调用方 Agent 的日志记录）


# 全局单例
_cost_tracker = CostTracker()


# ---------------------------------------------------------------------------
# 共享 HTTP 客户端 —— 代理隔离 + 超时控制
# ---------------------------------------------------------------------------

# trust_env=False 阻止 httpx 读取 HTTP_PROXY/HTTPS_PROXY 等环境变量，
# 从而避免本地代理（Clash/V2Ray/Verge）拦截 DeepSeek API 请求。
# 与旧方案（os.environ.pop）不同，这只影响 DeepSeek 请求，
# 进程中其他 HTTP 库的网络行为不受任何影响。
_http_client = httpx.AsyncClient(
    timeout=httpx.Timeout(120.0, connect=30.0),
    limits=httpx.Limits(max_keepalive_connections=5),
    trust_env=False,
)


# ---------------------------------------------------------------------------
# LLM 工厂
# ---------------------------------------------------------------------------


def create_llm(temperature: float | None = None) -> ChatOpenAI:
    """创建一个指向 DeepSeek 的 ChatOpenAI 实例。

    自动注入 CostTracker 回调以追踪每次调用的成本。
    使用 trust_env=False 的共享 httpx 客户端隔离本地代理。

    P1-1: 添加 max_retries=2 利用 OpenAI SDK 指数退避自动重试 5xx 错误，
    防止 DeepSeek API 偶发抖动导致分析失败。

    Args:
        temperature: 覆盖默认温度。None = 使用配置默认值。

    Returns:
        已配置的 ChatOpenAI 实例（尚未绑定工具）。
    """
    return ChatOpenAI(
        model=settings.deepseek_model_name,
        temperature=temperature if temperature is not None else settings.llm_temperature,
        max_tokens=settings.llm_max_tokens,
        api_key=settings.deepseek_api_key,
        base_url=settings.deepseek_base_url,
        max_retries=2,
        http_async_client=_http_client,
        callbacks=[_cost_tracker],
    )


# 便捷实例：默认 LLM 实例（温度来自配置）
llm = create_llm()
