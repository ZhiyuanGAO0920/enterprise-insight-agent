"""首次部署种子数据脚本。

由 docker-entrypoint.sh 在检测到空租户表时自动调用。
创建开箱即用所需的最小数据集：租户、角色、权限、管理员账号。

不与 FastAPI 耦合 —— 直接使用 SQLAlchemy async session 写入。
"""

import asyncio

from sqlalchemy import select

from app.auth.hashing import hash_password
from app.database.connection import get_session
from app.database.models import (
    Base,
    Permission,
    Role,
    RolePermission,
    Tenant,
    User,
    UserRole,
    UserStoreAccess,
    Store,
)


# =============================================================================
# 种子数据定义
# =============================================================================

DEFAULT_TENANT = {
    "name": "默认租户",
    "slug": "default",
}

PERMISSIONS = [
    ("analysis:create", "提交经营分析问题"),
    ("history:view", "查看历史分析记录"),
    ("user:manage", "管理用户和权限"),
    ("admin:manage", "系统管理（审计日志、Schema 配置等）"),
    ("dashboard:view", "查看经营仪表盘"),
    ("alerts:view", "查看预警和告警"),
    ("feedback:submit", "提交反馈"),
    ("prompts:view", "查看 Prompt 配置"),
]

ROLES = {
    "admin": {
        "description": "系统管理员 —— 拥有全部权限",
        "permissions": ["analysis:create", "history:view", "user:manage", "admin:manage",
                        "dashboard:view", "alerts:view", "feedback:submit",
                        "prompts:view"],
    },
    "analyst": {
        "description": "数据分析师 —— 可进行分析和查看，不可管理用户",
        "permissions": ["analysis:create", "history:view", "dashboard:view",
                        "alerts:view", "feedback:submit"],
    },
    "viewer": {
        "description": "只读用户 —— 仅可查看历史记录和仪表盘",
        "permissions": ["history:view", "dashboard:view"],
    },
}

DEFAULT_ADMIN = {
    "username": "admin",
    "password": "admin123",
    "display_name": "系统管理员",
}

DEMO_STORES = [
    {"store_name": "华东旗舰店（上海）", "region": "华东", "manager": "张经理", "status": "active"},
    {"store_name": "华北中心店（北京）", "region": "华北", "manager": "李经理", "status": "active"},
    {"store_name": "华南旗舰店（广州）", "region": "华南", "manager": "王经理", "status": "active"},
    {"store_name": "华中示范店（武汉）", "region": "华中", "manager": "陈经理", "status": "active"},
    {"store_name": "西南旗舰店（成都）", "region": "西南", "manager": "赵经理", "status": "active"},
]


# =============================================================================
# 主函数
# =============================================================================


async def seed():
    """写入完整的初始数据集。幂等 —— 仅当租户表为空时写入。"""
    async with get_session() as session:
        # 幂等检查
        existing = await session.execute(select(Tenant).limit(1))
        if existing.scalar_one_or_none() is not None:
            print("[seed] Tenants already exist — skipping (idempotent)")
            return

        print("[seed] Seeding initial data...")

        # ---- 1. 租户 ----
        tenant = Tenant(**DEFAULT_TENANT, is_active=True, max_users=100, plan="enterprise")
        session.add(tenant)
        await session.flush()
        print(f"[seed] Tenant created: {tenant.name} (id={tenant.id})")

        # ---- 2. 权限 ----
        perm_map: dict[str, Permission] = {}
        for code, desc in PERMISSIONS:
            perm = Permission(code=code, description=desc)
            session.add(perm)
            perm_map[code] = perm
        await session.flush()
        print(f"[seed] {len(PERMISSIONS)} permissions created")

        # ---- 3. 角色 + 角色-权限关联 ----
        role_map: dict[str, Role] = {}
        for role_name, role_def in ROLES.items():
            role = Role(name=role_name, description=role_def["description"])
            session.add(role)
            role_map[role_name] = role
        await session.flush()

        for role_name, role_def in ROLES.items():
            role = role_map[role_name]
            for perm_code in role_def["permissions"]:
                perm = perm_map[perm_code]
                session.add(RolePermission(role_id=role.id, permission_id=perm.id))
        await session.flush()
        print(f"[seed] {len(ROLES)} roles created with permissions")

        # ---- 4. 管理员用户 ----
        user = User(
            username=DEFAULT_ADMIN["username"],
            hashed_password=hash_password(DEFAULT_ADMIN["password"]),
            display_name=DEFAULT_ADMIN["display_name"],
            tenant_id=tenant.id,
            is_active=True,
        )
        session.add(user)
        await session.flush()

        # 绑定 admin 角色
        admin_role = role_map["admin"]
        session.add(UserRole(user_id=user.id, role_id=admin_role.id))
        await session.flush()
        print(f"[seed] Admin user created: {user.username} / {DEFAULT_ADMIN['password']}")

        # ---- 5. 门店访问权限（admin = 全部门店） ----
        # 先创建演示门店
        store_ids = []
        for store_data in DEMO_STORES:
            store = Store(**store_data)
            session.add(store)
            await session.flush()
            store_ids.append(store.id)
        print(f"[seed] {len(DEMO_STORES)} demo stores created")

        # admin 拥有 all 范围权限
        session.add(UserStoreAccess(user_id=user.id, store_id="*", scope_type="all"))
        await session.flush()

        # ---- 6. 提交 ----
        await session.commit()
        print("[seed] Seed data committed successfully!")
        print(f"[seed] Login: {DEFAULT_ADMIN['username']} / {DEFAULT_ADMIN['password']}")


# =============================================================================
# 入口
# =============================================================================

if __name__ == "__main__":
    asyncio.run(seed())
