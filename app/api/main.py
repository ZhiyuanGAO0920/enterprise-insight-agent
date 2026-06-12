"""FastAPI 应用入口。

组装所有路由模块并提供 app 实例供 uvicorn 服务。
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.routing import APIRouter

from app.config import get_settings
from app.errors.user_friendly import to_user_message
from app.logging_config import get_logger
from app.middleware.audit import audit_middleware
from app.middleware.tenant import TenantMiddleware

settings = get_settings()
logger = get_logger("eia.api")

from app.api.routes.admin import router as admin_router
from app.api.routes.alerts import router as alerts_router
from app.api.routes.analysis import router as analysis_router
from app.api.routes.auth import router as auth_router
from app.api.routes.dashboard import router as dashboard_router
from app.api.routes.monitor import router as monitor_router
from app.api.routes.feedback import router as feedback_router
from app.api.routes.prompts import router as prompts_router
from app.api.routes.session import router as session_router
from app.api.routes.weekly import router as weekly_router

app = FastAPI(
    title="企业智能经营分析平台 V4",
    description="自然语言驱动的企业级 Multi-Agent 经营分析平台。V4：10 Agent 节点、5 业务域（销售/CRM/财务/库存/供应链）、ECharts 可视化、多轮对话、数据溯源、移动端适配、多租户、审计日志、PDF 报告、结构化日志。",
    version="4.0.0",
)

# CORS —— 从配置读取允许的来源。开发用 "*"，生产必须限制为具体域名。
_cors_origins_raw = settings.cors_origins.strip()
if _cors_origins_raw == "*":
    _cors_origins = ["*"]
else:
    _cors_origins = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# V4: 审计日志中间件（在 CORS 之后，异常处理之前）
app.middleware("http")(audit_middleware)

# V4: 多租户中间件（从 JWT 提取 tenant_id，注入请求上下文）
app.add_middleware(TenantMiddleware)

# ---------------------------------------------------------------------------
# 全局异常处理器 — 将技术错误转换为用户友好消息
# ---------------------------------------------------------------------------


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """捕获所有未处理的异常，返回用户友好错误消息。"""
    logger.exception("未处理异常 %s %s", request.method, request.url.path)
    friendly = to_user_message(str(exc))
    return JSONResponse(
        status_code=500,
        content={
            "detail": friendly["user_message"],
            "icon": friendly["icon"],
            "action": friendly["action"],
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """HTTPException 也经过友好错误映射，统一输出格式。"""
    detail_str = str(exc.detail) if not isinstance(exc.detail, str) else exc.detail
    friendly = to_user_message(detail_str)
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "detail": friendly["user_message"],
            "icon": friendly["icon"],
            "action": friendly["action"],
        },
    )


# ---------------------------------------------------------------------------
# API 版本化 — 所有业务路由挂载在 /api/v1 下
# ---------------------------------------------------------------------------

v1_router = APIRouter(prefix="/api/v1")
v1_router.include_router(analysis_router)
v1_router.include_router(auth_router)
v1_router.include_router(weekly_router)
v1_router.include_router(alerts_router)
v1_router.include_router(dashboard_router)  # V3: Mobile dashboard snapshot
v1_router.include_router(session_router)    # V3: Multi-turn sessions
v1_router.include_router(feedback_router)   # V3: User feedback
v1_router.include_router(admin_router)      # V3: Admin — user management
v1_router.include_router(monitor_router)    # V3: AI quality dashboard
v1_router.include_router(prompts_router)    # V3: Prompt management

app.include_router(v1_router)


# --- API 版本响应头中间件 ---
@app.middleware("http")
async def add_api_version_header(request: Request, call_next):
    """为所有 /api/v1 响应添加版本和弃用提示头。"""
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers["X-API-Version"] = "v1"
    return response


# --- 向后兼容：/api/xxx → /api/v1/xxx 重定向 ---
# 在 v4 或 v5 中移除
@app.api_route("/api/{rest_of_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def redirect_api_v1(rest_of_path: str, request: Request):
    """将旧版 /api/* 请求 308 永久重定向到 /api/v1/*。"""
    # 防止对 /api/v1/* 的未知路径产生双写 v1 前缀
    if rest_of_path.startswith("v1/"):
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    new_url = f"/api/v1/{rest_of_path}"
    if request.url.query:
        new_url += f"?{request.url.query}"
    logger.warning("旧版 API 路径重定向: %s → %s", request.url.path, new_url)
    return RedirectResponse(
        url=new_url,
        status_code=308,
        headers={
            "X-API-Version": "v1",
            "X-Deprecation-Notice": "/api/* is deprecated. Use /api/v1/* instead.",
        },
    )


# 注册 API 路由 — 已移至上方 v1_router
# （保留空注释块以避免误读）

# 静态文件（Web 界面）
_static_dir = Path(__file__).parent / "static"
try:
    _static_dir.mkdir(exist_ok=True)
except OSError:
    pass  # 只读文件系统下不阻断启动，静态文件 serving 会提供清晰错误
app.mount("/static", StaticFiles(directory=str(_static_dir)), name="static")


@app.get("/", response_class=FileResponse)
async def root():
    """提供 Web 界面。"""
    return _static_dir / "index.html"


@app.get("/health", tags=["健康检查"], summary="存活检查")
async def health():
    """检查服务是否存活。返回服务版本号。"""
    return {"status": "ok", "version": "4.0.0"}


@app.get("/health/ready", tags=["健康检查"], summary="就绪检查")
async def readiness():
    """就绪检查 — 验证数据库和 Redis 连接是否正常。"""
    checks = {}
    try:
        from app.database.connection import get_session
        from sqlalchemy import text as _sql
        async with get_session() as s:
            await s.execute(_sql("SELECT 1"))
        checks["数据库"] = "正常"
    except Exception:
        checks["数据库"] = "异常（请检查 PostgreSQL 连接）"

    try:
        from app.database.redis import get_redis
        r = get_redis()
        await r.ping()
        checks["Redis"] = "正常"
    except Exception:
        checks["Redis"] = "异常（请检查 Redis 连接）"

    all_ok = all(v == "正常" for v in checks.values())
    return {
        "status": "就绪" if all_ok else "降级",
        "version": "4.0.0",
        "checks": checks,
    }


# ---------------------------------------------------------------------------
# 生命周期事件
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def startup_event():
    """服务启动时初始化日志系统。"""
    from app.logging_config import setup_logging

    setup_logging()
    logger.info("EIA V4 服务启动 — 日志系统已初始化")
