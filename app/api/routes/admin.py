"""管理员路由 — 用户管理、门店分配、批量导入。

所有端点需要 admin 角色权限。
"""

import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text

from app.api.dependencies import require_permission
from app.auth.hashing import hash_password
from app.database.connection import get_session

router = APIRouter(prefix="/admin", tags=["系统管理"])


# ============================================================================
# 请求/响应模型
# ============================================================================


class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=50, description="登录用户名")
    password: str = Field(..., min_length=6, max_length=100, description="初始密码")
    display_name: str = Field(default="", max_length=100, description="显示名称")
    role: str = Field(..., description="角色: admin/regional_manager/store_manager")
    scope_type: str = Field(default="store", description="门店范围: all/region/store")
    region: str | None = Field(default=None, description="区域名（scope_type=region 时必填）")
    store_ids: list[str] = Field(default=[], description="门店 ID 列表（scope_type=store 时必填）")


class UpdateUserRequest(BaseModel):
    display_name: str | None = Field(default=None, description="显示名称")
    role: str | None = Field(default=None, description="角色")
    is_active: bool | None = Field(default=None, description="启用/禁用")
    scope_type: str | None = Field(default=None, description="门店范围")
    region: str | None = Field(default=None, description="区域名")
    store_ids: list[str] | None = Field(default=None, description="门店 ID 列表（scope_type=store 时必须提供）")


class ResetPasswordRequest(BaseModel):
    new_password: str = Field(..., min_length=6, max_length=100)


class UserInfo(BaseModel):
    id: int
    username: str
    display_name: str
    role: str
    is_active: bool
    scope_type: str
    region: str | None
    store_count: int


# ============================================================================
# 用户管理
# ============================================================================


@router.get("/users", summary="用户列表")
async def list_users(
    user: dict = Depends(require_permission("user:manage")),
    role: str | None = None,
    search: str | None = None,
    active_only: bool = False,
):
    """获取所有用户列表，支持按角色和关键词筛选。

    Args:
        role: 按角色筛选（admin/regional_manager/store_manager）
        search: 按用户名或显示名搜索
        active_only: 只显示启用的用户
    """
    async with get_session() as session:
        query = """
            SELECT
                u.id, u.username, u.display_name, u.is_active,
                COALESCE(r.name, '') as role_name,
                COALESCE(usa.scope_type, 'store') as scope_type,
                MAX(usa.region) as region,
                COUNT(usa.store_id) as store_count,
                STRING_AGG(usa.store_id, ',') FILTER (WHERE usa.store_id != '*') as store_ids_csv
            FROM users u
            LEFT JOIN user_roles ur ON u.id = ur.user_id
            LEFT JOIN roles r ON ur.role_id = r.id
            LEFT JOIN user_store_access usa ON u.id = usa.user_id
            WHERE 1=1
        """
        params: dict = {}

        if role:
            query += " AND r.name = :role"
            params["role"] = role
        if search:
            query += " AND (u.username ILIKE :search OR u.display_name ILIKE :search)"
            params["search"] = f"%{search}%"
        if active_only:
            query += " AND u.is_active = true"

        query += " GROUP BY u.id, u.username, u.display_name, u.is_active, r.name, usa.scope_type ORDER BY u.id"

        result = await session.execute(text(query), params)
        users = []
        for row in result.fetchall():
            store_ids_csv = row[8] or ""
            store_ids = [s.strip() for s in store_ids_csv.split(",") if s.strip()] if store_ids_csv else []
            users.append({
                "id": row[0],
                "username": row[1],
                "display_name": row[2] or "",
                "is_active": row[3],
                "role": row[4] or "",
                "scope_type": row[5] or "store",
                "region": row[6],
                "store_count": len(store_ids) if store_ids else row[7] or 0,
                "store_ids": store_ids,
            })
        return {"users": users, "total": len(users)}


@router.post("/users", summary="创建用户")
async def create_user(
    req: CreateUserRequest,
    user: dict = Depends(require_permission("user:manage")),
):
    """创建一个新用户并分配角色和门店访问权限。

    - 用户名必须唯一
    - 密码通过 bcrypt 哈希存储
    - 同时创建角色关联和门店访问记录
    """
    async with get_session() as session:
        # 检查用户名唯一性
        existing = await session.execute(
            text("SELECT id FROM users WHERE username = :u"),
            {"u": req.username},
        )
        if existing.fetchone():
            raise HTTPException(status_code=400, detail="用户名已存在")

        # 获取角色 ID
        role_result = await session.execute(
            text("SELECT id FROM roles WHERE name = :r"),
            {"r": req.role},
        )
        role_row = role_result.fetchone()
        if not role_row:
            raise HTTPException(status_code=400, detail=f"无效角色: {req.role}")
        role_id = role_row[0]

        # 创建用户
        hashed = hash_password(req.password)
        result = await session.execute(
            text("""
                INSERT INTO users (username, hashed_password, display_name, is_active)
                VALUES (:u, :p, :d, true)
                RETURNING id
            """),
            {"u": req.username, "p": hashed, "d": req.display_name or req.username},
        )
        user_id = result.scalar_one()

        # 分配角色
        await session.execute(
            text("INSERT INTO user_roles (user_id, role_id) VALUES (:uid, :rid)"),
            {"uid": user_id, "rid": role_id},
        )

        # 分配门店访问权限
        await _set_store_access(session, user_id, req.scope_type, req.region, req.store_ids)

        await session.commit()
        return {"status": "ok", "user_id": user_id, "message": f"用户 {req.username} 创建成功"}


@router.put("/users/{target_user_id}", summary="修改用户")
async def update_user(
    target_user_id: int,
    req: UpdateUserRequest,
    user: dict = Depends(require_permission("user:manage")),
):
    """修改用户信息——显示名称、角色、启用状态、门店访问范围。"""
    # 验证：scope_type=store 时必须提供 store_ids，防止误清空门店访问权限
    if req.scope_type == "store" and not req.store_ids:
        raise HTTPException(status_code=422, detail="scope_type 为 'store' 时必须提供 store_ids 列表")
    # 验证：scope_type=region 时必须提供 region，防止误清空门店访问权限
    if req.scope_type == "region" and not req.region:
        raise HTTPException(status_code=422, detail="scope_type 为 'region' 时必须提供 region 值")

    async with get_session() as session:
        # 检查用户存在
        existing = await session.execute(
            text("SELECT id FROM users WHERE id = :uid"),
            {"uid": target_user_id},
        )
        if not existing.fetchone():
            raise HTTPException(status_code=404, detail="用户不存在")

        # 更新基本信息
        if req.display_name is not None:
            await session.execute(
                text("UPDATE users SET display_name = :d WHERE id = :uid"),
                {"d": req.display_name, "uid": target_user_id},
            )
        if req.is_active is not None:
            await session.execute(
                text("UPDATE users SET is_active = :a WHERE id = :uid"),
                {"a": req.is_active, "uid": target_user_id},
            )

        # 更新角色
        if req.role is not None:
            role_result = await session.execute(
                text("SELECT id FROM roles WHERE name = :r"),
                {"r": req.role},
            )
            role_row = role_result.fetchone()
            if role_row:
                await session.execute(
                    text("DELETE FROM user_roles WHERE user_id = :uid"),
                    {"uid": target_user_id},
                )
                await session.execute(
                    text("INSERT INTO user_roles (user_id, role_id) VALUES (:uid, :rid)"),
                    {"uid": target_user_id, "rid": role_row[0]},
                )

        # 更新门店访问
        if req.scope_type is not None:
            await session.execute(
                text("DELETE FROM user_store_access WHERE user_id = :uid"),
                {"uid": target_user_id},
            )
            await _set_store_access(
                session, target_user_id,
                req.scope_type,
                req.region,
                req.store_ids or [],
            )

        await session.commit()
        return {"status": "ok", "message": "用户信息已更新"}


@router.delete("/users/{target_user_id}", summary="删除用户")
async def delete_user(
    target_user_id: int,
    user: dict = Depends(require_permission("user:manage")),
):
    """删除用户及其关联的角色和门店访问记录。"""
    async with get_session() as session:
        # 先检查用户是否存在
        existing = await session.execute(
            text("SELECT id FROM users WHERE id = :uid"),
            {"uid": target_user_id},
        )
        if not existing.fetchone():
            raise HTTPException(status_code=404, detail="用户不存在")

        await session.execute(
            text("DELETE FROM user_store_access WHERE user_id = :uid"),
            {"uid": target_user_id},
        )
        await session.execute(
            text("DELETE FROM user_roles WHERE user_id = :uid"),
            {"uid": target_user_id},
        )
        await session.execute(
            text("DELETE FROM users WHERE id = :uid"),
            {"uid": target_user_id},
        )
        await session.commit()
        return {"status": "ok", "message": "用户已删除"}


@router.post("/users/{target_user_id}/reset-password", summary="重置密码")
async def reset_password(
    target_user_id: int,
    req: ResetPasswordRequest,
    user: dict = Depends(require_permission("user:manage")),
):
    """重置指定用户的密码。"""
    async with get_session() as session:
        hashed = hash_password(req.new_password)
        result = await session.execute(
            text("UPDATE users SET hashed_password = :p WHERE id = :uid RETURNING id"),
            {"p": hashed, "uid": target_user_id},
        )
        if not result.fetchone():
            raise HTTPException(status_code=404, detail="用户不存在")
        await session.commit()
        return {"status": "ok", "message": "密码已重置"}


@router.post("/users/batch-import", summary="批量导入用户")
async def batch_import(
    file: UploadFile,
    user: dict = Depends(require_permission("user:manage")),
):
    """上传 CSV 文件批量创建用户。

    CSV 格式：
    username,password,display_name,role,scope_type,region,store_ids
    zhangsan,123456,张三,regional_manager,region,华东,
    lisi,123456,李四,store_manager,store,,42
    """
    content = await file.read()
    reader = csv.DictReader(io.StringIO(content.decode("utf-8")))

    created, skipped, errors = 0, 0, []

    async with get_session() as session:
        for row in reader:
            username = row.get("username", "").strip()
            if not username:
                continue

            # 检查是否已存在
            existing = await session.execute(
                text("SELECT id FROM users WHERE username = :u"),
                {"u": username},
            )
            if existing.fetchone():
                skipped += 1
                continue

            try:
                # 创建用户
                hashed = hash_password(row.get("password", "123456"))
                result = await session.execute(
                    text("INSERT INTO users (username, hashed_password, display_name, is_active) VALUES (:u, :p, :d, true) RETURNING id"),
                    {"u": username, "p": hashed, "d": row.get("display_name", username)},
                )
                uid = result.scalar_one()

                # 分配角色
                role_name = row.get("role", "store_manager")
                role_result = await session.execute(
                    text("SELECT id FROM roles WHERE name = :r"),
                    {"r": role_name},
                )
                role_row = role_result.fetchone()
                if role_row:
                    await session.execute(
                        text("INSERT INTO user_roles (user_id, role_id) VALUES (:uid, :rid)"),
                        {"uid": uid, "rid": role_row[0]},
                    )

                # 分配门店访问
                scope_type = row.get("scope_type", "store")
                region = row.get("region", "").strip() or None
                store_ids_str = row.get("store_ids", "").strip()
                store_ids = [s.strip() for s in store_ids_str.split(",") if s.strip()] if store_ids_str else []
                await _set_store_access(session, uid, scope_type, region, store_ids)

                created += 1
            except Exception as e:
                errors.append(f"{username}: {e}")

        await session.commit()

    return {
        "status": "ok",
        "created": created,
        "skipped": skipped,
        "errors": errors,
    }


# ============================================================================
# 门店列表
# ============================================================================


@router.post("/impersonate/{target_user_id}", summary="模拟用户视角分析")
async def impersonate_user(
    target_user_id: int,
    question: str = "查询我可以访问的门店列表",
    user: dict = Depends(require_permission("user:manage")),
):
    """以指定用户的权限执行一次分析，用于验证 RBAC 是否正确配置。

    Args:
        target_user_id: 要模拟的用户 ID
        question: 分析问题（默认："查询我可以访问的门店列表"）
    """
    from app.auth.rbac import get_user_store_ids
    from app.workflow.graph import graph
    from app.workflow.state import AnalysisState

    store_ids = await get_user_store_ids(target_user_id)

    # 获取目标用户名
    async with get_session() as session:
        name_result = await session.execute(
            text("SELECT username FROM users WHERE id = :uid"),
            {"uid": target_user_id},
        )
        name_row = name_result.fetchone()
        target_name = name_row[0] if name_row else str(target_user_id)

    state = await graph.ainvoke({
        "question": question,
        "user_id": target_user_id,
        "store_ids": store_ids,
    })

    return {
        "target_user": target_name,
        "target_user_id": target_user_id,
        "store_ids": store_ids,
        "store_count": len(store_ids) if store_ids else "全部",
        "report": state.get("report", ""),
        "errors": [
            {"agent": e.get("agent", ""), "error": str(e.get("error", ""))[:200]}
            for e in state.get("agent_errors", [])
        ],
    }


@router.get("/stores", summary="门店列表")
async def list_stores(
    user: dict = Depends(require_permission("user:manage")),
    region: str | None = None,
):
    """获取门店列表，用于管理界面分配门店时选择。

    Args:
        region: 可选，按区域筛选。
    """
    async with get_session() as session:
        query = "SELECT id, store_name, region FROM store"
        params: dict = {}
        if region:
            query += " WHERE region = :region"
            params["region"] = region
        query += " ORDER BY region, store_name LIMIT 500"

        result = await session.execute(text(query), params)
        stores = [
            {"id": row[0], "name": row[1], "region": row[2]}
            for row in result.fetchall()
        ]
        # 获取所有区域列表
        regions_result = await session.execute(
            text("SELECT DISTINCT region FROM store ORDER BY region")
        )
        regions = [row[0] for row in regions_result.fetchall()]

        return {"stores": stores, "regions": regions, "total": len(stores)}


# ============================================================================
# 辅助
# ============================================================================


async def _set_store_access(session, user_id: int, scope_type: str, region: str | None, store_ids: list[str]):
    """为用户设置门店访问权限。"""
    if scope_type == "all":
        await session.execute(
            text("INSERT INTO user_store_access (user_id, scope_type, store_id, region) VALUES (:uid, 'all', '*', NULL)"),
            {"uid": user_id},
        )
    elif scope_type == "region" and region:
        await session.execute(
            text("INSERT INTO user_store_access (user_id, scope_type, store_id, region) VALUES (:uid, 'region', 'REGION', :r)"),
            {"uid": user_id, "r": region},
        )
    elif scope_type == "store":
        for sid in store_ids:
            await session.execute(
                text("INSERT INTO user_store_access (user_id, scope_type, store_id, region) VALUES (:uid, 'store', :sid, NULL)"),
                {"uid": user_id, "sid": sid},
            )


# ============================================================================
# V4: 审计日志查询
# ============================================================================


@router.get("/audit-logs", summary="查询审计日志（仅管理员）")
async def get_audit_logs(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(50, ge=1, le=200, description="每页条数"),
    user_id: int | None = Query(None, description="按用户筛选"),
    action: str | None = Query(None, description="按操作类型筛选：GET/POST/PUT/DELETE"),
    resource: str | None = Query(None, description="按资源路径模糊搜索"),
    days: int = Query(7, ge=1, le=365, description="查询最近 N 天的日志"),
    _: dict = Depends(require_permission("admin:manage")),
):
    """查询系统操作审计日志。支持按用户、操作类型、资源路径、时间范围筛选。"""
    offset = (page - 1) * page_size
    conditions = ["created_at >= NOW() - INTERVAL '1 day' * :days"]
    params = {"days": days, "limit": page_size, "offset": offset}

    if user_id:
        conditions.append("user_id = :user_id")
        params["user_id"] = user_id
    if action:
        conditions.append("action = :action")
        params["action"] = action
    if resource:
        conditions.append("resource ILIKE :resource")
        params["resource"] = f"%{resource}%"

    where_clause = " AND ".join(conditions)

    async with get_session() as session:
        result = await session.execute(
            text(f"""
                SELECT id, user_id, tenant_id, action, resource, ip_address,
                       session_id, status_code, elapsed_ms, created_at
                FROM audit_log
                WHERE {where_clause}
                ORDER BY created_at DESC
                LIMIT :limit OFFSET :offset
            """),
            params,
        )
        rows = result.fetchall()

        count_result = await session.execute(
            text(f"SELECT COUNT(*) FROM audit_log WHERE {where_clause}"),
            {k: v for k, v in params.items() if k not in ("limit", "offset")},
        )
        total = count_result.scalar()

    return {
        "records": [
            {
                "id": r.id,
                "user_id": r.user_id,
                "tenant_id": r.tenant_id,
                "action": r.action,
                "resource": r.resource,
                "ip_address": r.ip_address,
                "session_id": r.session_id,
                "status_code": r.status_code,
                "elapsed_ms": r.elapsed_ms,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


# ============================================================================
# V4: Schema 配置向导
# ============================================================================


@router.get("/schema/discover", summary="自动发现客户数据库 Schema")
async def discover_schema_endpoint(
    include_samples: bool = Query(True, description="是否包含样本数据"),
    _: dict = Depends(require_permission("admin:manage")),
):
    """连接客户数据库，自动发现所有表、列和样本数据。

    返回结构化的 Schema 报告，供管理员配置 customer_schema.yaml 映射时参考。
    需要 admin:manage 权限。
    """
    from app.adapters.schema_discovery import discover_schema, format_discovery_report

    try:
        report = await discover_schema(include_samples=include_samples)
        return {
            "database_type": report.database_type,
            "database_name": report.database_name,
            "table_count": len(report.tables),
            "tables": [
                {
                    "name": t.name,
                    "row_count": t.row_count,
                    "column_count": len(t.columns),
                    "columns": [
                        {
                            "name": c.name,
                            "data_type": c.data_type,
                            "is_nullable": c.is_nullable,
                            "is_primary_key": c.is_primary_key,
                            "sample_values": c.sample_values,
                        }
                        for c in t.columns
                    ],
                    "sample_rows": t.sample_rows[:3] if t.sample_rows else [],
                }
                for t in report.tables
            ],
            "foreign_keys": report.foreign_keys,
            "markdown_preview": format_discovery_report(report)[:5000],
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Schema 发现失败：{str(e)}。请检查数据库连接是否正常。",
        )


class SchemaMappingPreview(BaseModel):
    mappings: dict = Field(..., description="逻辑表名 → 物理表名的映射，如 {'orders': 't_orders'}")


@router.post("/schema/preview-yaml", summary="预览 customer_schema.yaml")
async def preview_schema_yaml(
    body: SchemaMappingPreview,
    _: dict = Depends(require_permission("admin:manage")),
):
    """根据用户配置的表名映射，生成 customer_schema.yaml 预览。

    输入：{"orders": "t_orders", "store": "t_store", ...}
    输出：完整的 YAML 配置内容。
    """
    import yaml

    config = {
        "version": "1.0",
        "customer_name": "待填写",
        "tables": {},
    }

    for logical_name, physical_name in body.mappings.items():
        config["tables"][logical_name] = {
            "table": physical_name,
            "description": f"映射自 {physical_name}",
        }

    yaml_content = yaml.dump(config, allow_unicode=True, default_flow_style=False, sort_keys=False)

    return {
        "yaml_content": yaml_content,
        "mapping_count": len(body.mappings),
    }


@router.get("/schema/test-connection", summary="测试数据库连接")
async def test_connection(
    _: dict = Depends(require_permission("user:manage")),
):
    """测试当前配置的数据库连接是否正常。"""
    from app.database.connection import get_session
    from sqlalchemy import text as _sql

    try:
        async with get_session() as session:
            result = await session.execute(_sql("SELECT 1"))
            result.scalar_one()
            # 获取数据库版本
            version_result = await session.execute(_sql("SELECT version()"))
            version = version_result.scalar_one_or_none()
            return {
                "status": "connected",
                "database_version": str(version)[:100] if version else "unknown",
            }
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="数据库连接失败，请检查数据库配置是否正确",
        )
