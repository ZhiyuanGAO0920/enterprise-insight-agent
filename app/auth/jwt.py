"""JWT 令牌创建与验证。"""

import uuid
from datetime import datetime, timedelta, timezone as _tz

from jose import JWTError, jwt

from app.config import get_settings

settings = get_settings()


def create_access_token(data: dict) -> str:
    """创建新的 JWT 访问令牌，包含用于撤销支持的唯一 JTI。

    V4：自动从 data 中提取 tenant_id 写入 JWT payload。

    Args:
        data: 载荷字典（必须包含 'user_id'，可选 'tenant_id'）。

    Returns:
        编码后的 JWT 字符串。
    """
    to_encode = data.copy()
    now = datetime.now(_tz.utc)  # 保留 tzinfo，确保跨时区兼容
    expire = now + timedelta(minutes=settings.jwt_expire_minutes)
    to_encode.update({
        "exp": expire,
        "iat": now,
        "jti": uuid.uuid4().hex,  # 唯一令牌 ID，用于黑名单支持
        "tenant_id": data.get("tenant_id"),  # V4: 多租户
    })
    return jwt.encode(to_encode, settings.jwt_secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict | None:
    """解码并验证 JWT 访问令牌。

    Args:
        token: 待解码的 JWT 字符串。

    Returns:
        如果有效则返回载荷字典，过期/无效返回 None。
    """
    try:
        return jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None


def get_token_remaining_ttl(payload: dict) -> int:
    """计算令牌剩余的 TTL（秒）。

    Args:
        payload: 解码后的 JWT 载荷。

    Returns:
        到过期前的剩余秒数（最小为 0）。
    """
    exp = payload.get("exp", 0)
    now = datetime.now(_tz.utc).timestamp()
    return max(0, int(exp - now))
