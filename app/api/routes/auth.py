"""认证路由 — 登录、登出、令牌签发。"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.dependencies import get_current_user, rate_limit, rate_limit_ip
from app.auth.hashing import verify_password
from app.auth.jwt import create_access_token, get_token_remaining_ttl
from app.database.connection import get_session
from app.database.models import User
from app.database.redis import blacklist_token

router = APIRouter(prefix="/auth", tags=["用户认证"])


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, description="用户名", examples=["admin"])
    password: str = Field(..., min_length=1, description="密码", examples=["admin123"])


class LoginResponse(BaseModel):
    access_token: str = Field(description="JWT 访问令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
    user_id: int = Field(description="用户 ID")
    username: str = Field(description="用户名")


@router.post("/login", response_model=LoginResponse, summary="用户登录")
async def login(
    req: LoginRequest,
    _: None = Depends(rate_limit_ip),
):
    """验证用户名和密码，返回 JWT 访问令牌。

    令牌有效期 8 小时（可在环境变量 JWT_EXPIRE_MINUTES 中配置）。
    凭据无效时返回 401 错误。
    """
    async with get_session() as session:
        result = await session.execute(
            select(User).where(User.username == req.username)
        )
        user = result.scalar_one_or_none()

        if not user or not verify_password(req.password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="用户名或密码错误",
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="账户已被禁用",
            )

        token = create_access_token({"user_id": user.id, "username": user.username})

        return LoginResponse(
            access_token=token,
            user_id=user.id,
            username=user.username,
        )


@router.get("/verify", summary="验证令牌有效性")
async def verify_token(user: dict = Depends(get_current_user)):
    """轻量级 token 验证。仅检查 JWT 有效性，不查数据库。"""
    return {"status": "ok", "user_id": user.get("user_id")}

@router.post("/logout", summary="用户登出")
async def logout(user: dict = Depends(get_current_user)):
    """将当前 JWT 令牌加入黑名单，使其立即失效。

    登出后该令牌不可再次使用，需要重新登录获取新令牌。
    """
    jti = user.get("jti")
    if jti:
        ttl = get_token_remaining_ttl(user)
        await blacklist_token(jti, ttl)
    return {"status": "ok", "message": "令牌已注销"}
