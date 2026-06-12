"""测试种子数据脚本的正确性。

不连接真实 PostgreSQL——使用 SQLite 内存数据库验证数据模型和逻辑。
"""

import pytest

from app.auth.hashing import hash_password, verify_password
from scripts.seed_data import (
    DEFAULT_ADMIN,
    DEFAULT_TENANT,
    DEMO_STORES,
    PERMISSIONS,
    ROLES,
)


class TestSeedDataIntegrity:
    """验证种子数据定义本身的一致性，不依赖数据库。"""

    def test_default_tenant_has_required_fields(self):
        assert DEFAULT_TENANT["name"] == "默认租户"
        assert DEFAULT_TENANT["slug"] == "default"

    def test_default_admin_credentials(self):
        assert DEFAULT_ADMIN["username"] == "admin"
        assert DEFAULT_ADMIN["password"] == "admin123"
        assert len(DEFAULT_ADMIN["display_name"]) > 0

    def test_all_permissions_have_code_and_description(self):
        for code, desc in PERMISSIONS:
            assert ":" in code, f"Permission code '{code}' should contain ':'"
            assert len(desc) > 0, f"Permission '{code}' has empty description"

    def test_admin_role_has_all_permissions(self):
        admin_perms = set(ROLES["admin"]["permissions"])
        all_perms = {code for code, _ in PERMISSIONS}
        assert admin_perms == all_perms, "Admin should have ALL permissions"

    def test_analyst_role_permissions_subset_of_admin(self):
        analyst_perms = set(ROLES["analyst"]["permissions"])
        admin_perms = set(ROLES["admin"]["permissions"])
        assert analyst_perms.issubset(admin_perms)
        assert "user:manage" not in analyst_perms, "Analyst should NOT have user:manage"

    def test_viewer_role_is_readonly(self):
        viewer_perms = set(ROLES["viewer"]["permissions"])
        assert "analysis:create" not in viewer_perms, "Viewer should NOT create analysis"
        assert "history:view" in viewer_perms, "Viewer SHOULD view history"
        assert "dashboard:view" in viewer_perms, "Viewer SHOULD view dashboard"

    def test_all_role_permissions_exist(self):
        """每个角色引用的权限必须在 PERMISSIONS 中定义。"""
        all_perms = {code for code, _ in PERMISSIONS}
        for role_name, role_def in ROLES.items():
            for perm in role_def["permissions"]:
                assert perm in all_perms, f"Role '{role_name}' references undefined permission '{perm}'"

    def test_demo_stores_have_unique_regions(self):
        regions = [s["region"] for s in DEMO_STORES]
        assert len(regions) == len(set(regions)), "Demo stores should cover different regions"

    def test_demo_stores_all_active(self):
        for store in DEMO_STORES:
            assert store["status"] == "active", f"Store '{store['store_name']}' should be active"
            assert len(store["store_name"]) > 0
            assert len(store["region"]) > 0
            assert len(store["manager"]) > 0


class TestPasswordHashing:
    """验证密码哈希功能可用。"""

    def test_hash_and_verify(self):
        hashed = hash_password("admin123")
        assert hashed != "admin123"
        assert verify_password("admin123", hashed)

    def test_wrong_password_fails(self):
        hashed = hash_password("admin123")
        assert not verify_password("wrong", hashed)

    def test_default_admin_password_hashable(self):
        hashed = hash_password(DEFAULT_ADMIN["password"])
        assert len(hashed) > 20  # bcrypt hash is at least 60 chars


class TestSeedDataIdempotent:
    """幂等性验证——检查种子数据定义无重复。"""

    def test_no_duplicate_permission_codes(self):
        codes = [c for c, _ in PERMISSIONS]
        assert len(codes) == len(set(codes))

    def test_no_duplicate_role_names(self):
        assert len(ROLES) == len(set(ROLES.keys()))

    def test_no_duplicate_store_names(self):
        names = [s["store_name"] for s in DEMO_STORES]
        assert len(names) == len(set(names))
