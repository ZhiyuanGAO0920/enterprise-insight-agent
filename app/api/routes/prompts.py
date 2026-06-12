"""Prompt 管理 API — V3 功能 (P1-3)。

支持在运行时查看和重新加载基于 YAML 的 Agent 提示词。
所有端点需要管理员级别权限。
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.dependencies import require_permission
from app.config import get_settings
from app.tools.prompt_loader import get_prompt_loader

router = APIRouter(prefix="/prompts", tags=["Prompt管理"])


class PromptListItem(BaseModel):
    agent: str
    version: str
    file: str
    prompt_keys: list[str]


class PromptListResponse(BaseModel):
    yaml_enabled: bool = Field(description="YAML prompt loading is enabled")
    agents: list[PromptListItem]


class AgentPromptResponse(BaseModel):
    agent: str
    version: str
    file: str
    yaml_enabled: bool
    prompts: dict[str, str]


class ReloadResponse(BaseModel):
    status: str
    agent_count: int


@router.get("", response_model=PromptListResponse, summary="列出所有 Agent Prompt 版本")
async def list_prompts(user: dict = Depends(require_permission("alert:view"))):
    """列出所有已加载的 Agent Prompt，包括版本号和可用键。

    需要管理员或区域经理权限。
    """
    loader = get_prompt_loader()
    agents = loader.list_agents()
    return PromptListResponse(
        yaml_enabled=loader.is_enabled(),
        agents=[PromptListItem(**a) for a in agents],
    )


@router.get("/{agent}", response_model=AgentPromptResponse, summary="获取指定 Agent 的 Prompt")
async def get_agent_prompt(
    agent: str,
    user: dict = Depends(require_permission("alert:view")),
):
    """获取指定 Agent 的完整 Prompt 内容（YAML 版本）。

    如果 YAML 未启用或无此 Agent，返回 404。
    """
    loader = get_prompt_loader()
    if not loader.is_enabled():
        raise HTTPException(
            status_code=503,
            detail="YAML Prompt 加载未启用。请在 .env 中设置 FEATURE_PROMPT_YAML=true",
        )

    info = loader.get_agent_info(agent)
    if info is None:
        raise HTTPException(
            status_code=404,
            detail=f"Agent '{agent}' 未找到。可用 Agent: {[a['agent'] for a in loader.list_agents()]}",
        )

    return AgentPromptResponse(
        agent=info["agent"],
        version=info["version"],
        file=info["file"],
        yaml_enabled=True,
        prompts={k: v for k, v in info["prompts"].items() if isinstance(v, str)},
    )


@router.post("/reload", response_model=ReloadResponse, summary="重新加载 YAML Prompt")
async def reload_prompts(
    user: dict = Depends(require_permission("alert:view")),
):
    """从磁盘重新加载所有 YAML Prompt 文件（热更新，无需重启服务）。

    修改 YAML 文件后调用此接口，新 Prompt 立即生效。
    需要管理员权限。
    """
    settings = get_settings()
    if not settings.feature_prompt_yaml:
        raise HTTPException(
            status_code=503,
            detail="YAML Prompt 加载未启用。请在 .env 中设置 FEATURE_PROMPT_YAML=true",
        )

    loader = get_prompt_loader()
    count = loader.reload()
    return ReloadResponse(status="ok", agent_count=count)
