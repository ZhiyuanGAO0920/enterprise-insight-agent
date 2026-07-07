"""Redis 连接 —— 带连接池的异步客户端。

提供：
  - get_redis()：延迟初始化的 Redis 客户端单例
  - 令牌黑名单：添加/检查已撤销的令牌（支持登出）
  - 速率限制器：滑动窗口速率限制
"""

import time
from typing import Optional

import redis.asyncio as aioredis

from app.config import get_settings

settings = get_settings()

_client: Optional[aioredis.Redis] = None


def get_redis() -> aioredis.Redis:
    """返回共享的异步 Redis 客户端（延迟初始化）。"""
    global _client
    if _client is None:
        _client = aioredis.from_url(
            settings.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )
    return _client


# ---------------------------------------------------------------------------
# 令牌黑名单（登出）
# ---------------------------------------------------------------------------

BLACKLIST_PREFIX = "bl:"  # 键格式：bl:{jti}


async def blacklist_token(jti: str, ttl_seconds: int) -> None:
    """通过将 JTI 加入黑名单来撤销 JWT 令牌。

    Args:
        jti: 待撤销的 JWT ID（jti 声明）。
        ttl_seconds: 黑名单条目的保留时长（应与令牌剩余有效期匹配）。
    """
    r = get_redis()
    await r.setex(f"{BLACKLIST_PREFIX}{jti}", ttl_seconds, "1")


async def is_token_blacklisted(jti: str) -> bool:
    """检查 JWT 令牌是否已被撤销。

    Args:
        jti: 待检查的 JWT ID。

    Returns:
        如果令牌已被撤销返回 True。Redis 不可用时返回 False 降级放行。
    """
    try:
        r = get_redis()
        return await r.exists(f"{BLACKLIST_PREFIX}{jti}") > 0
    except Exception:
        return False  # Redis 不可用时降级放行


# ---------------------------------------------------------------------------
# 速率限制器（滑动窗口）
# ---------------------------------------------------------------------------

RATE_LIMIT_PREFIX = "rl:"  # 键格式：rl:{user_id}:{endpoint}


async def check_rate_limit(
    user_id: int,
    endpoint: str = "default",
    max_requests: int = 30,
    window_seconds: int = 60,
) -> tuple[bool, int]:
    """滑动窗口速率限制器。

    使用有序集合跟踪每个用户每个端点的请求时间戳。

    Args:
        user_id: 用户 ID。
        endpoint: API 端点标识符。
        max_requests: 窗口内允许的最大请求数。
        window_seconds: 时间窗口（秒）。

    Returns:
        (allowed: bool, remaining: int) 元组。
    """
    r = get_redis()
    key = f"{RATE_LIMIT_PREFIX}{user_id}:{endpoint}"
    now = time.time()
    window_start = now - window_seconds

    # 移除过期的记录
    await r.zremrangebyscore(key, 0, window_start)

    # 统计窗口内当前的请求数
    count = await r.zcard(key)

    if count >= max_requests:
        return False, 0

    # 添加当前请求
    await r.zadd(key, {str(now): now})
    await r.expire(key, window_seconds + 10)

    return True, max_requests - count - 1
