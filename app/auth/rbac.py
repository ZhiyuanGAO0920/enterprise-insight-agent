"""RBAC —— 权限查询和行级门店访问控制。

提供以下功能：
  - 获取用户的权限码（通过角色）
  - 获取用户可访问的门店（用于行级 SQL 过滤）
"""

from sqlalchemy import select

from app.database.connection import get_session
from app.database.models import Permission, RolePermission, UserRole, UserStoreAccess


async def get_user_permissions(user_id: int) -> list[str]:
    """返回用户的所有权限码（通过其角色）。

    Args:
        user_id: 用户 ID。

    Returns:
        权限码字符串列表（例如 ["analysis:create", "report:view"]）。
    """
    async with get_session() as session:
        stmt = (
            select(Permission.code)
            .select_from(UserRole)
            .join(RolePermission, RolePermission.role_id == UserRole.role_id)
            .join(Permission, Permission.id == RolePermission.permission_id)
            .where(UserRole.user_id == user_id)
        )
        result = await session.execute(stmt)
        return [row[0] for row in result.fetchall()]


async def get_user_store_access_raw(user_id: int) -> list[dict]:
    """返回用户的原始门店访问记录（含 scope_type）。

    Args:
        user_id: 用户 ID。

    Returns:
        包含 scope_type/store_id/region 的字典列表。
    """
    from sqlalchemy import text
    async with get_session() as session:
        result = await session.execute(
            text("""SELECT scope_type, store_id, region FROM user_store_access WHERE user_id = :uid"""),
            {"uid": user_id},
        )
        return [
            {"scope_type": row[0] or "store", "store_id": row[1], "region": row[2]}
            for row in result.fetchall()
        ]


async def get_user_store_ids(user_id: int) -> list[str] | None:
    """返回用户可访问的门店 ID 列表（已根据 scope_type 解析）。

    支持三种 scope_type：
      - 'all' → 返回 None（无限制，全部门店）
      - 'region' → 查询该区域下所有门店 ID
      - 'store' → 返回指定的门店 ID

    Returns:
        None = 完全访问（管理员/大区总监可能需要按区域动态查询但这里简化处理）
        list[str] = 可访问的门店 ID 列表
    """
    from sqlalchemy import text

    # 系统用户（ID=0）可访问全部门店，用于定时任务
    if user_id == 0:
        return None

    accesses = await get_user_store_access_raw(user_id)
    if not accesses:
        return []  # 无记录 = 无可访问门店（安全：默认拒绝）

    store_ids = []
    for access in accesses:
        scope = access["scope_type"]

        if scope == "all":
            return None  # 全部门店

        if scope == "region":
            # 动态查询该区域下的所有门店
            region = access["region"]
            if region:
                async with get_session() as session:
                    result = await session.execute(
                        text("SELECT id FROM store WHERE region = :r"),
                        {"r": region},
                    )
                    region_stores = [str(row[0]) for row in result.fetchall()]
                    store_ids.extend(region_stores)

        elif scope == "store":
            sid = access["store_id"]
            if sid and sid != "*":
                store_ids.append(str(sid))

    if not store_ids:
        return []  # 无可访问门店
    return list(set(store_ids))  # 去重


def build_store_filter_sql(store_ids: list[str] | None, store_column: str = "store_id") -> str:
    """构建用于门店级别过滤的 SQL WHERE 子句片段。

    安全：对 store_ids 值进行 SQL 注入防护（转义单引号），
    并对 store_column 进行白名单验证，防止列名注入。

    Args:
        store_ids: 允许访问的门店 ID 列表，None 表示无限制访问。
        store_column: 用于过滤的列名（默认："store_id"）。

    Returns:
        类似 " AND store_id IN ('s1','s2')" 的 WHERE 子句字符串或空字符串。
    """
    # 白名单验证 store_column 防止列名注入
    _ALLOWED_COLUMNS = frozenset({"store_id", "store_code", "store_name", "location_id"})
    if store_column not in _ALLOWED_COLUMNS:
        store_column = "store_id"  # 安全降级为默认值

    if store_ids is None:
        return ""
    if not store_ids:
        return " AND 1=0"  # 无可访问门店 —— 强制返回空结果
    # 安全转义：将单引号替换为两个单引号（PostgreSQL 标准的 SQL 转义）
    escaped = ", ".join(f"'{str(s).replace(chr(39), chr(39) + chr(39))}'" for s in store_ids)
    return f" AND {store_column} IN ({escaped})"
