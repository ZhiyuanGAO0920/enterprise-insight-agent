"""密码哈希 —— 通过 passlib 使用 bcrypt，含纯 Python 备用方案。

如果 passlib 的原生 bcrypt 后端失败（Python 3.14 上的已知问题），
则回退到直接使用 bcrypt 库。
"""

import logging

from passlib.context import CryptContext

logger = logging.getLogger(__name__)

# 主方案：passlib + bcrypt
try:
    pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
    # 冒烟测试后端
    pwd_context.hash("test")
except (ValueError, AttributeError) as e:
    logger.warning("passlib bcrypt backend failed (%s), using bcrypt directly", e)
    pwd_context = None


def hash_password(password: str) -> str:
    """使用 bcrypt 对明文密码进行哈希。"""
    if pwd_context is not None:
        return pwd_context.hash(password)

    # 备用方案：直接使用 bcrypt
    import bcrypt

    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证明文密码是否匹配 bcrypt 哈希。"""
    if pwd_context is not None:
        return pwd_context.verify(plain_password, hashed_password)

    # 备用方案：直接使用 bcrypt
    import bcrypt

    return bcrypt.checkpw(
        plain_password.encode("utf-8"),
        hashed_password.encode("utf-8"),
    )
