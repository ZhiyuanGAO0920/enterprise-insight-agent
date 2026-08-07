"""嵌入向量生成 —— Ollama BGE-M3（主）或 OpenAI API（备选）。

通过 .env 中的 EMBEDDING_PROVIDER 选择提供商：
  "ollama" —— Ollama BGE-M3（http://localhost:11434，1024 维）
  "openai" —— 通过 OpenAI API 的 text-embedding-3-small（1536 维）
"""

import asyncio
import hashlib
import json
from typing import Optional

from openai import AsyncOpenAI

from app.config import get_settings
from app.logging_config import get_logger

settings = get_settings()
logger = get_logger("eia.embedding")

_client: Optional[AsyncOpenAI] = None
_http_client: Optional["httpx.AsyncClient"] = None
_lock = asyncio.Lock()

# ---------------------------------------------------------------------------
# V4.6.1: Embedding 结果缓存（P0-1 优化）
# ---------------------------------------------------------------------------
# 一次完整分析会调用 get_embedding 多达 7 次（路由 1 次 + 5 个 Agent 各 1 次 + 记忆节点 1 次），
# 其中 5 次是对同一问题文本的重复计算（BGE-M3 单次 300ms~1s+，且 Ollama 并发请求会排队）。
# 缓存 key 含 provider + model + dimension：更换嵌入模型后旧缓存自动失效，避免跨模型余弦距离失真。
# 仅缓存成功的向量（失败降级的全零向量不写缓存，防止劣化被固化 7 天）。

EMBEDDING_CACHE_TTL = 7 * 24 * 3600  # 7 天

# 同文本并发请求合并为一次计算（LangGraph Send 并行分支会同时发起）
_coalesce_locks: dict[str, asyncio.Lock] = {}
_coalesce_locks_guard = asyncio.Lock()


def _cache_key(text: str) -> str:
    """构建嵌入缓存键：emb:{provider}:{model}:{dim}:{md5(text)}"""
    raw = f"{settings.embedding_provider}|{settings.embedding_model_name}|{settings.embedding_dimension}|{text}"
    return f"emb:{hashlib.md5(raw.encode()).hexdigest()[:16]}"


async def _get_cached_embedding(text: str) -> list[float] | None:
    """从 Redis 读取缓存向量，不可用时返回 None（降级为实时计算）。"""
    try:
        from app.database.redis import get_redis

        data = await get_redis().get(_cache_key(text))
        if data:
            return json.loads(data)
    except Exception:
        pass  # Redis 不可用不影响主流程
    return None


async def _set_cached_embedding(text: str, vec: list[float]) -> None:
    """写入嵌入缓存；仅缓存非全零向量（全零 = 降级兜底，不固化）。"""
    if not vec or not any(vec):
        return
    try:
        from app.database.redis import get_redis

        await get_redis().setex(_cache_key(text), EMBEDDING_CACHE_TTL, json.dumps(vec))
    except Exception:
        pass


async def _coalesce_lock(text: str) -> asyncio.Lock:
    """获取（或创建）文本对应的进程内锁，用于并发请求合并。"""
    key = _cache_key(text)
    async with _coalesce_locks_guard:
        if key not in _coalesce_locks:
            _coalesce_locks[key] = asyncio.Lock()
        return _coalesce_locks[key]


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
    """为多个文本生成嵌入向量（带 Redis 缓存 + 并发合并）。

    同一文本在本次分析中只计算一次：5 个 Agent 并发对同一问题
    调用 get_embedding 时，第一个计算完成后其余全部命中缓存。

    Args:
        texts: 待嵌入的文本列表。

    Returns:
        嵌入向量列表。失败时返回零向量作为降级兜底。
    """
    try:
        results: list[list[float]] = []
        for t in texts:
            vec = await _get_cached_embedding(t)
            if vec is not None:
                results.append(vec)
                continue
            # 缓存未命中：加锁后二次检查（并发合并），再实时计算
            lock = await _coalesce_lock(t)
            async with lock:
                vec = await _get_cached_embedding(t)
                if vec is None:
                    vec = (await _embed([t]))[0]
                    await _set_cached_embedding(t, vec)
                results.append(vec)
        return results
    except Exception as e:
        logger.warning("批量嵌入生成失败，返回零向量降级: %s", e)
        return [[0.0] * settings.embedding_dimension for _ in texts]


async def _shutdown_http():
    """关闭 embedding 模块的 HTTP 连接池（在 FastAPI shutdown 事件中调用）。"""
    global _http_client
    if _http_client is not None:
        await _http_client.aclose()
        _http_client = None
