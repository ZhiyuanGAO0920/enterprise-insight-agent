"""嵌入向量生成 —— Ollama BGE-M3（主）或 OpenAI API（备选）。

通过 .env 中的 EMBEDDING_PROVIDER 选择提供商：
  "ollama" —— Ollama BGE-M3（http://localhost:11434，1024 维）
  "openai" —— 通过 OpenAI API 的 text-embedding-3-small（1536 维）
"""

import asyncio
from typing import Optional

from openai import AsyncOpenAI

from app.config import get_settings
from app.logging_config import get_logger

settings = get_settings()
logger = get_logger("eia.embedding")

_client: Optional[AsyncOpenAI] = None
_http_client: Optional["httpx.AsyncClient"] = None
_lock = asyncio.Lock()


async def _get_client() -> AsyncOpenAI:
    """获取或创建异步的 OpenAI 兼容客户端。

    对于 Ollama，指向 localhost:11434/v1。
    对于 OpenAI，使用 api.openai.com。

    在 Windows 上，系统代理设置可能会干扰 localhost 请求。
    我们通过使用自定义 httpx 客户端绕过代理检测。

    使用 asyncio.Lock 防止竞态条件下创建多个客户端实例。
    """
    global _client, _http_client
    if _client is not None:
        return _client
    async with _lock:
        if _client is not None:
            return _client
        import httpx

        _http_client = httpx.AsyncClient(
            proxy=None,       # 绕过系统代理
            trust_env=False,  # 不读取 HTTP_PROXY/HTTPS_PROXY 环境变量
        )

        provider = settings.embedding_provider
        if provider == "ollama":
            _client = AsyncOpenAI(
                api_key="ollama",  # Ollama 不需要真实密钥
                base_url=f"{settings.ollama_base_url}/v1",
                http_client=_http_client,
            )
        elif provider == "openai":
            if not settings.openai_api_key:
                raise ValueError("embedding_provider=openai 但 openai_api_key 未配置")
            _client = AsyncOpenAI(
                api_key=settings.openai_api_key,
                http_client=_http_client,
            )
        else:
            raise ValueError(
                f"不支持的 EMBEDDING_PROVIDER: '{provider}'，"
                f"仅支持 'ollama' 或 'openai'"
            )
    return _client


async def _embed(texts: list[str]) -> list[list[float]]:
    """通过 Ollama 或 OpenAI 生成嵌入向量。"""
    client = await _get_client()
    response = await client.embeddings.create(
        model=settings.embedding_model_name,
        input=texts,
    )
    return [item.embedding for item in response.data]


# ============================================================================
# 公开 API
# ============================================================================


async def get_embedding(text: str) -> list[float]:
    """生成单个嵌入向量。返回零向量作为降级兜底。

    使用 Ollama BGE-M3（1024 维）或 OpenAI（1536 维）。
    """
    try:
        embeddings = await get_embeddings([text])
        return embeddings[0]
    except Exception as e:
        logger.warning("嵌入生成失败，返回零向量降级: %s", e)
        return [0.0] * settings.embedding_dimension


async def get_embeddings(texts: list[str]) -> list[list[float]]:
    """为多个文本生成嵌入向量。

    Args:
        texts: 待嵌入的文本列表。

    Returns:
        嵌入向量列表。失败时返回零向量作为降级兜底。
    """
    try:
        return await _embed(texts)
    except Exception as e:
        logger.warning("批量嵌入生成失败，返回零向量降级: %s", e)
        return [[0.0] * settings.embedding_dimension for _ in texts]


async def _shutdown_http():
    """关闭 embedding 模块的 HTTP 连接池（在 FastAPI shutdown 事件中调用）。"""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
