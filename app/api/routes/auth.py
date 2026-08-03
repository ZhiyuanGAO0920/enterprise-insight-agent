"""认证路由 — 登录、登出、令牌签发、微信小程序登录绑定。"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.dependencies import get_current_user, rate_limit, rate_limit_ip
from app.auth.hashing import verify_password
from app.auth.jwt import create_access_token, get_token_remaining_ttl
from app.config import get_settings
from app.database.connection import get_session
from app.database.models import User, UserWechatBinding
from app.database.redis import blacklist_token

router = APIRouter(prefix="/auth", tags=["用户认证"])

settings = get_settings()


# ── 请求/响应模型 ──


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, description="用户名", examples=["admin"])
    password: str = Field(..., min_length=1, description="密码", examples=["admin123"])


class LoginResponse(BaseModel):
    access_token: str = Field(description="JWT 访问令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
    user_id: int = Field(description="用户 ID")
    username: str = Field(description="用户名")


class WechatLoginRequest(BaseModel):
    code: str = Field(..., min_length=1, description="wx.login() 返回的 code")


class WechatBindRequest(BaseModel):
    code: str = Field(..., min_length=1, description="wx.login() 返回的 code")
    username: str = Field(..., min_length=1, description="现有系统账号用户名")
    password: str = Field(..., min_length=1, description="现有系统账号密码")


class WechatLoginResponse(BaseModel):
    access_token: str = Field(description="JWT 访问令牌")
    token_type: str = Field(default="bearer", description="令牌类型")
    user_id: int = Field(description="用户 ID")
    username: str = Field(description="用户名")
    message: str = Field(default="ok", description="提示信息")
    need_bind: bool = Field(default=False, description="是否需要在绑定页完成账号绑定（未绑定微信账号时为 true）")


# ── 辅助函数 ──


async def _wechat_code2session(code: str) -> str:
    """将微信 code 转换为 openid。

    生产模式（WECHAT_APPID 已配置）：调用微信 code2Session API。
    Demo 模式（WECHAT_APPID 为空）：基于 code 生成确定性 openid，
    方便小程序测试号开发，无需真实微信 API 凭据。
    """
    if settings.wechat_appid and settings.wechat_secret:
        import httpx
        url = "https://api.weixin.qq.com/sns/jscode2session"
        params = {
            "appid": settings.wechat_appid,
            "secret": settings.wechat_secret,
            "js_code": code,
            "grant_type": "authorization_code",
        }
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params)
            data = resp.json()
        if "openid" not in data:
            errcode = data.get("errcode", "unknown")
            errmsg = data.get("errmsg", "unknown error")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"微信 code2Session 失败: [{errcode}] {errmsg}",
            )
        return data["openid"]

    # Demo 模式：固定 openid。
    # ⚠️ 不能基于 code 哈希：wx.login 的 code 一次性有效，每次登录都产生新 openid，
    # 绑定永远无法命中 → 每次登录都要重新绑定（曾出现多行 demo_* 绑定记录）。
    # Demo 场景单人使用，固定身份可接受；生产配置真实 WECHAT_APPID/SECRET 后自动走真实 openid。
    return "demo_wechat_dev_user"


def _build_login_response(user: User) -> WechatLoginResponse:
    """根据 User 构建统一的登录响应。"""
    token = create_access_token({"user_id": user.id, "username": user.username})
    return WechatLoginResponse(
        access_token=token,
        user_id=user.id,
        username=user.username,
    )


# ── 路由 ──


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


@router.post("/wechat-login", response_model=WechatLoginResponse, summary="微信小程序登录")
async def wechat_login(
    req: WechatLoginRequest,
    _: None = Depends(rate_limit_ip),
):
    """微信小程序一键登录。

    流程：wx.login() → code → 后端换 openid → 查绑定表：
    - 已绑定 → 直接签发 JWT
    - 未绑定 → 返回 200 + need_bind=true（前端跳转绑定页）
    """
    openid = await _wechat_code2session(req.code)

    async with get_session() as session:
        result = await session.execute(
            select(UserWechatBinding).where(UserWechatBinding.openid == openid)
        )
        binding = result.scalar_one_or_none()

        if not binding:
            # ⚠️ 不能 raise HTTPException(status_code=4021)：4021 不是合法 HTTP 状态码
            # （合法范围 100-599），uvicorn/h11 会拒绝写入响应并直接断开连接，
            # 客户端收到"空响应"表现为登录失败（TestClient 宽松所以测试未暴露）。
            # 改为 200 + need_bind 业务标记，前端据此跳转绑定页。
            return WechatLoginResponse(
                access_token="",
                user_id=0,
                username="",
                message="微信账号未绑定系统账号，请先绑定",
                need_bind=True,
            )

        user_result = await session.execute(
            select(User).where(User.id == binding.user_id)
        )
        user = user_result.scalar_one_or_none()

        if not user or not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="账户已被禁用",
            )

        resp = _build_login_response(user)
        resp.message = "登录成功"
        return resp


@router.post("/wechat-bind", response_model=WechatLoginResponse, summary="微信账号绑定系统账号")
async def wechat_bind(
    req: WechatBindRequest,
    _: None = Depends(rate_limit_ip),
):
    """将微信 openid 绑定到现有系统账号。

    首次使用微信登录时调用。验证系统账号密码后建立绑定关系。
    """
    openid = await _wechat_code2session(req.code)

    async with get_session() as session:
        existing = await session.execute(
            select(UserWechatBinding).where(UserWechatBinding.openid == openid)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="该微信账号已绑定",
            )

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

        binding = UserWechatBinding(openid=openid, user_id=user.id)
        session.add(binding)
        await session.commit()

        resp = _build_login_response(user)
        resp.message = "绑定成功"
        return resp


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
