"""FastAPI 依赖注入 —— 认证和授权。

提供以下依赖注入：
  - get_current_user：验证 JWT、检查黑名单、返回载荷
  - require_permission：检查特定权限码的工厂函数
  - rate_limit：按用户的速率限制依赖
"""

import hashlib

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth.jwt import decode_access_token
from app.auth.rbac import get_user_permissions
from app.database.redis import check_rate_limit, is_token_blacklisted

security = HTTPBearer()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> dict:
    """验证 JWT 令牌，检查黑名单，并返回载荷字典。

    如果令牌缺失、无效或已被撤销，抛出 401 错误。
    """
    token = credentials.credentials
    payload = decode_access_token(token)
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # 检查令牌黑名单（支持登出）
    jti = payload.get("jti")
    if jti and await is_token_blacklisted(jti):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has been revoked",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # V4 安全加固：验证账户仍处于活跃状态（防止 JWT 签发后被禁用）
    user_id = payload.get("user_id")
    if user_id is not None:
        try:
            from app.database.connection import get_session
            from sqlalchemy import text
            async with get_session() as s:
                r = await s.execute(
                    text("SELECT is_active FROM users WHERE id = :uid"),
                    {"uid": user_id},
                )
                row = r.fetchone()
                if row is None or not row[0]:
                    raise HTTPException(
                        status_code=status.HTTP_401_UNAUTHORIZED,
                        detail="Account has been disabled or deleted",
                        headers={"WWW-Authenticate": "Bearer"},
                    )
        except HTTPException:
            raise
        except Exception:
            pass  # 数据库不可用时优雅降级，不阻断已认证请求

    return payload


def require_permission(permission_code: str):
    """工厂函数：返回一个检查指定权限的依赖。

    用法：
        @router.get("/admin")
        async def admin_route(user = Depends(require_permission("admin:access"))):
            ...

    如果用户缺少所需权限，抛出 403 错误。
    """

    async def _check(user: dict = Depends(get_current_user)) -> dict:
        perms = await get_user_permissions(user["user_id"])
        if permission_code not in perms:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permission: {permission_code}",
            )
        return user

    return _check


async def rate_limit(
    request: Request,
    user: dict = Depends(get_current_user),
    max_requests: int = 30,
    window_seconds: int = 60,
) -> None:
    """对已认证用户进行请求速率限制。Redis 不可用时优雅降级。

    如果用户超出限制，抛出 429 错误。

    用法：
        @router.post("/analyze")
        async def analyze(..., _: None = Depends(rate_limit)):
            ...
    """
    try:
        endpoint = request.url.path
        allowed, remaining = await check_rate_limit(
            user["user_id"],
            endpoint,
            max_requests=max_requests,
            window_seconds=window_seconds,
        )
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Try again later.",
                headers={"Retry-After": str(window_seconds)},
            )
    except HTTPException:
        raise
    except Exception:
        # Redis 不可用时优雅降级，但记录警告以便运维发现
        import logging
        logging.getLogger("eia.rate_limit").warning("速率限制 Redis 不可用，降级放行", exc_info=True)
        pass


async def rate_limit_ip(
    request: Request,
    max_requests: int = 10,
    window_seconds: int = 60,
) -> None:
    """按客户端 IP 进行请求速率限制（用于未认证端点）。

    使用客户端的 IP 地址作为速率限制的键。
    Redis 不可用时优雅降级，不阻断请求。

    如果 IP 超出限制，抛出 429 错误。

    用法：
        @router.post("/login")
        async def login(..., _: None = Depends(rate_limit_ip)):
            ...
    """
    try:
        # 对抗审查 M9：部署在反代后时 request.client.host 恒为反代 IP，
        # 所有用户共享一个限速窗口（10 次/分钟全局锁，可被刷成对所有人的 DoS）。
        # 优先取 X-Forwarded-For 首个 IP（反代写入的客户端真实 IP）；
        # 注意这是限速而非认证，伪造 XFF 只能影响自己的限速配额，风险可接受。
        forwarded = request.headers.get("x-forwarded-for", "")
        client_ip = forwarded.split(",")[0].strip() if forwarded else (request.client.host if request.client else "unknown")
        endpoint = request.url.path
        ip_key = int(hashlib.md5(f"{client_ip}:{endpoint}".encode()).hexdigest(), 16) % (2**31)
        allowed, remaining = await check_rate_limit(
            ip_key,
            endpoint,
            max_requests=max_requests,
            window_seconds=window_seconds,
        )
        if not allowed:
            raise HTTPException(
                status_code=429,
                detail="Too many requests. Please try again later.",
                headers={"Retry-After": str(window_seconds)},
            )
    except HTTPException:
        raise  # 重新抛出 429
    except Exception:
        import logging
        logging.getLogger("eia.rate_limit").warning("IP 速率限制 Redis 不可用，降级放行", exc_info=True)
        pass  # Redis 不可用时优雅降级，不阻断请求
