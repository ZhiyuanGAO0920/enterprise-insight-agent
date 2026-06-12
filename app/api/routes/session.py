"""会话管理路由 — V3 功能（P0-2：多轮对话）。"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.dependencies import get_current_user
from app.tools.context_manager import ContextManager, create_session

router = APIRouter(prefix="/session", tags=["会话管理"])


class SessionCreateResponse(BaseModel):
    session_id: str = Field(description="新建的会话 ID")


class SessionInfoResponse(BaseModel):
    session_id: str = Field(description="会话 ID")
    turn_count: int = Field(description="当前对话轮次")
    history: list[dict] = Field(description="对话历史记录")
    entity_memory: dict = Field(description="已记住的实体（门店名、区域名等）")


async def _verify_session_ownership(session_id: str, user_id: int) -> None:
    """验证会话所有权，防止跨用户会话读取。"""
    ctx = ContextManager(session_id)
    session_user_id = await ctx.get_session_user_id()
    if session_user_id is not None and session_user_id != user_id:
        raise HTTPException(status_code=403, detail="无权访问此会话")


@router.post("/create", response_model=SessionCreateResponse, summary="创建新会话")
async def create_new_session(user: dict = Depends(get_current_user)):
    """创建新的分析会话，返回 session_id。

    在后续调用 /api/analysis/analyze 时传入 session_id 即可启用多轮对话上下文。
    会话数据存储在 Redis 中，有效期与 JWT 令牌一致（默认 8 小时）。
    """
    session_id = await create_session(user["user_id"])
    return {"session_id": session_id}


@router.get("/{session_id}", response_model=SessionInfoResponse, summary="获取会话信息")
async def get_session_info(
    session_id: str,
    user: dict = Depends(get_current_user),
):
    """查看指定会话的当前状态：对话历史、已记住的实体、轮次计数。

    可用于前端展示"已记住：旗舰店040、华东区"等上下文信息。
    """
    await _verify_session_ownership(session_id, user["user_id"])
    ctx = ContextManager(session_id)
    history = await ctx.get_history()
    entity_memory = await ctx.get_entity_memory()
    return {
        "session_id": session_id,
        "turn_count": len(history),
        "history": [
            {"question": h["question"], "summary": h.get("summary", "")[:200]}
            for h in history
        ],
        "entity_memory": entity_memory,
    }
