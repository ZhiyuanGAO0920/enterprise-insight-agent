"""RBAC 增强 —— scope_type + user:manage 权限 + 种子账号。

修订 ID: 004_rbac_enhancement
创建日期: 2026-06-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "004_rbac_enhancement"
down_revision: Union[str, None] = "003_inventory_supply_chain"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- 1. user_store_access 加 scope_type 列 ----
    op.execute("""
        ALTER TABLE user_store_access
        ADD COLUMN IF NOT EXISTS scope_type VARCHAR(20) DEFAULT 'store'
    """)

    # ---- 2. 新增 user:manage 权限 ----
    op.execute("""
        INSERT INTO permissions (code, description)
        VALUES ('user:manage', 'Manage user accounts')
        ON CONFLICT (code) DO NOTHING
    """)
    # V4 修复：admin 角色应拥有全部 9 项权限
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id
        FROM roles r, permissions p
        WHERE r.name = 'admin'
        AND NOT EXISTS (
            SELECT 1 FROM role_permissions rp2
            WHERE rp2.role_id = r.id AND rp2.permission_id = p.id
        )
    """)

    # ---- 3. 迁移现有数据 ----
    # admin → scope_type = 'all'
    op.execute("""
        UPDATE user_store_access SET scope_type = 'all'
        WHERE user_id = 1 AND scope_type = 'store'
    """)

    # ---- 4. 种子数据：admin + 7 个大区总监 + 100 个店长 ----
    # V4: 确保 admin 用户存在（全新安装时缺失）
    op.execute("""
        INSERT INTO users (id, username, hashed_password, display_name, is_active)
        VALUES (1, 'admin',
            '$2b$12$LJ3m4ys3GZFnYMz8kVsKaOTSxGHLZZZJRPJtGqPKPBMrRXYKF1RXi',
            '系统管理员', true)
        ON CONFLICT (id) DO NOTHING
    """)
    op.execute("""
        INSERT INTO user_roles (user_id, role_id)
        SELECT u.id, r.id FROM users u, roles r
        WHERE u.username = 'admin' AND r.name = 'admin'
        AND NOT EXISTS (SELECT 1 FROM user_roles ur WHERE ur.user_id = u.id AND ur.role_id = r.id)
    """)

    # 先获取门店按区域分组
    op.execute("""
        INSERT INTO roles (name, description)
        VALUES ('regional_director', '大区总监')
        ON CONFLICT (name) DO NOTHING
    """)
    op.execute("""
        INSERT INTO role_permissions (role_id, permission_id)
        SELECT r.id, p.id FROM roles r, permissions p
        WHERE r.name = 'regional_director'
        AND p.code IN ('analysis:create', 'history:view', 'alert:view', 'report:view')
        AND NOT EXISTS (
            SELECT 1 FROM role_permissions rp2
            WHERE rp2.role_id = r.id AND rp2.permission_id = p.id
        )
    """)

    # 7 个大区总监（密码: director123）
    op.execute("""
        INSERT INTO users (username, hashed_password, display_name, is_active)
        SELECT username, pwd, display_name, true
        FROM (VALUES
            ('director_huadong', '$2b$12$LJ3m4ys3GZfnYMz8kVsKaOTSxGHLZZZJRPJtGqPKPBMrRXYKF1RXi', '华东大区总监'),
            ('director_huanan',  '$2b$12$LJ3m4ys3GZfnYMz8kVsKaOTSxGHLZZZJRPJtGqPKPBMrRXYKF1RXi', '华南大区总监'),
            ('director_huabei',  '$2b$12$LJ3m4ys3GZfnYMz8kVsKaOTSxGHLZZZJRPJtGqPKPBMrRXYKF1RXi', '华北大区总监'),
            ('director_huazhong','$2b$12$LJ3m4ys3GZfnYMz8kVsKaOTSxGHLZZZJRPJtGqPKPBMrRXYKF1RXi', '华中大区总监'),
            ('director_xinan',   '$2b$12$LJ3m4ys3GZfnYMz8kVsKaOTSxGHLZZZJRPJtGqPKPBMrRXYKF1RXi', '西南大区总监'),
            ('director_xibei',   '$2b$12$LJ3m4ys3GZfnYMz8kVsKaOTSxGHLZZZJRPJtGqPKPBMrRXYKF1RXi', '西北大区总监'),
            ('director_dongbei', '$2b$12$LJ3m4ys3GZfnYMz8kVsKaOTSxGHLZZZJRPJtGqPKPBMrRXYKF1RXi', '东北大区总监')
        ) AS t(username, pwd, display_name)
        WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.username = t.username)
    """)
    # 分配角色
    op.execute("""
        INSERT INTO user_roles (user_id, role_id)
        SELECT u.id, r.id FROM users u, roles r
        WHERE u.username LIKE 'director_%' AND r.name = 'regional_director'
        AND NOT EXISTS (SELECT 1 FROM user_roles ur WHERE ur.user_id = u.id AND ur.role_id = r.id)
    """)
    # 分配区域
    op.execute("""
        INSERT INTO user_store_access (user_id, scope_type, store_id, region)
        SELECT u.id, 'region', 'REGION',
            CASE
                WHEN u.username = 'director_huadong' THEN '华东'
                WHEN u.username = 'director_huanan' THEN '华南'
                WHEN u.username = 'director_huabei' THEN '华北'
                WHEN u.username = 'director_huazhong' THEN '华中'
                WHEN u.username = 'director_xinan' THEN '西南'
                WHEN u.username = 'director_xibei' THEN '西北'
                WHEN u.username = 'director_dongbei' THEN '东北'
            END
        FROM users u
        WHERE u.username LIKE 'director_%'
        AND NOT EXISTS (SELECT 1 FROM user_store_access usa WHERE usa.user_id = u.id)
    """)

    # 100 个店长（每店一个，密码: store123）
    op.execute("""
        INSERT INTO users (username, hashed_password, display_name, is_active)
        SELECT
            'store_' || LPAD(s.id::text, 3, '0'),
            '$2b$12$LJ3m4ys3GZfnYMz8kVsKaOTSxGHLZZZJRPJtGqPKPBMrRXYKF1RXi',
            s.name || '店长',
            true
        FROM store s
        WHERE NOT EXISTS (
            SELECT 1 FROM users u WHERE u.username = 'store_' || LPAD(s.id::text, 3, '0')
        )
    """)
    op.execute("""
        INSERT INTO user_roles (user_id, role_id)
        SELECT u.id, r.id FROM users u, roles r
        WHERE u.username LIKE 'store_%' AND r.name = 'store_manager'
        AND NOT EXISTS (SELECT 1 FROM user_roles ur WHERE ur.user_id = u.id AND ur.role_id = r.id)
    """)
    op.execute("""
        INSERT INTO user_store_access (user_id, scope_type, store_id, region)
        SELECT u.id, 'store', s.id::varchar, NULL
        FROM users u
        JOIN store s ON u.username = 'store_' || LPAD(s.id::text, 3, '0')
        WHERE NOT EXISTS (SELECT 1 FROM user_store_access usa WHERE usa.user_id = u.id)
    """)


def downgrade() -> None:
    op.execute("DELETE FROM user_store_access WHERE user_id IN (SELECT id FROM users WHERE username LIKE 'store_%' OR username LIKE 'director_%')")
    op.execute("DELETE FROM user_roles WHERE user_id IN (SELECT id FROM users WHERE username LIKE 'store_%' OR username LIKE 'director_%')")
    op.execute("DELETE FROM users WHERE username LIKE 'store_%' OR username LIKE 'director_%'")
    op.execute("DELETE FROM role_permissions WHERE role_id = (SELECT id FROM roles WHERE name = 'regional_director')")
    op.execute("DELETE FROM roles WHERE name = 'regional_director'")
    op.execute("DELETE FROM role_permissions WHERE permission_id = (SELECT id FROM permissions WHERE code = 'user:manage')")
    op.execute("DELETE FROM permissions WHERE code = 'user:manage'")
    op.execute("ALTER TABLE user_store_access DROP COLUMN IF EXISTS scope_type")
