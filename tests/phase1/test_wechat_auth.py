"""Phase 1: 微信小程序登录绑定测试。

使用唯一 code 前缀避免数据库状态冲突。
每个测试复用同一 TestClient 实例，避免 Windows 事件循环冲突。
"""

import pytest
import time
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def unique_code_suffix():
    """为每个测试生成唯一后缀，避免数据库状态冲突。"""
    return str(int(time.time() * 1000))


@pytest.fixture
def client():
    """提供持久化 TestClient，避免 Windows 事件循环冲突。"""
    from app.api.main import app
    with TestClient(app) as c:
        yield c


@pytest.fixture(autouse=True)
def clean_binding_table():
    """Demo 模式 openid 固定为 demo_wechat_dev_user，所有测试共享同一绑定行，
    每个测试前清空绑定表保证隔离（旧实现按 code 哈希生成 openid，天然隔离）。

    用同步 psycopg2 连接清理（database_url_sync），避免 asyncio.run 与
    TestClient 事件循环冲突（Windows Proactor 已知问题）。
    """
    import psycopg2
    from app.config import get_settings

    # database_url_sync 形如 postgresql+psycopg2://...，psycopg2 不接受驱动后缀
    sync_url = get_settings().database_url_sync.replace("+psycopg2", "")
    conn = psycopg2.connect(sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM user_wechat_bindings")
        conn.commit()
    finally:
        conn.close()
    yield


pytestmark = pytest.mark.db


class TestWechatLogin:
    """微信登录 + 绑定流程测试（Demo 模式）。"""

    def test_login_not_bound(self, client, unique_code_suffix):
        """未绑定的微信 code 应返回 200 + need_bind 标记。

        不能用 4021 状态码：非法 HTTP 状态（合法范围 100-599），uvicorn/h11 会
        拒绝写入响应并断开连接，真机表现为登录失败。
        """
        code = f"unbound_{unique_code_suffix}"
        r = client.post("/api/auth/wechat-login", json={"code": code})
        assert r.status_code == 200
        data = r.json()
        assert data["need_bind"] is True
        assert data["access_token"] == ""

    def test_bind_success(self, client, unique_code_suffix):
        """绑定成功后返回 JWT。"""
        code = f"bind_{unique_code_suffix}"
        r = client.post("/api/auth/wechat-bind", json={
            "code": code,
            "username": "admin",
            "password": "admin123",
        })
        assert r.status_code == 200
        data = r.json()
        assert "access_token" in data
        assert data["user_id"] > 0
        assert data["message"] == "绑定成功"

    def test_login_after_bind(self, client, unique_code_suffix):
        """绑定后，同一 code 直接登录成功。"""
        code = f"login_{unique_code_suffix}"
        bind_r = client.post("/api/auth/wechat-bind", json={
            "code": code,
            "username": "admin",
            "password": "admin123",
        })
        assert bind_r.status_code == 200

        login_r = client.post("/api/auth/wechat-login", json={"code": code})
        assert login_r.status_code == 200
        data = login_r.json()
        assert "access_token" in data
        assert data["message"] == "登录成功"

    def test_bind_duplicate_code(self, client, unique_code_suffix):
        """同一 code 不能重复绑定。"""
        code = f"dup_{unique_code_suffix}"
        client.post("/api/auth/wechat-bind", json={
            "code": code,
            "username": "admin",
            "password": "admin123",
        })
        r = client.post("/api/auth/wechat-bind", json={
            "code": code,
            "username": "admin",
            "password": "admin123",
        })
        assert r.status_code == 400

    def test_bind_wrong_password(self, client, unique_code_suffix):
        """错误密码应返回 401。"""
        code = f"wrong_{unique_code_suffix}"
        r = client.post("/api/auth/wechat-bind", json={
            "code": code,
            "username": "admin",
            "password": "wrong_password",
        })
        assert r.status_code == 401

    def test_bind_nonexistent_user(self, client, unique_code_suffix):
        """不存在的用户应返回 401。"""
        code = f"nouser_{unique_code_suffix}"
        r = client.post("/api/auth/wechat-bind", json={
            "code": code,
            "username": "nonexistent",
            "password": "password",
        })
        assert r.status_code == 401

    def test_demo_mode_binding_persists_across_codes(self, client, unique_code_suffix):
        """Demo 模式：不同 code 映射同一固定 openid，绑定一次后任意 code 都能登录。

        基于 code 哈希的 openid 会导致每次登录都重新绑定（wx.login code 一次性有效），
        已改为固定 openid。生产模式（配置真实 WECHAT_APPID/SECRET）不受影响。
        """
        code_a = f"diff_a_{unique_code_suffix}"
        code_b = f"diff_b_{unique_code_suffix}"

        # 用 code_a 完成绑定
        bind_r = client.post("/api/auth/wechat-bind", json={
            "code": code_a,
            "username": "admin",
            "password": "admin123",
        })
        assert bind_r.status_code == 200

        # 用完全不同的 code_b 登录 → 应命中同一绑定
        r_b = client.post("/api/auth/wechat-login", json={"code": code_b})
        assert r_b.status_code == 200
        data = r_b.json()
        assert data["access_token"]
        assert data["need_bind"] is False

    def test_empty_code_rejected(self, client):
        """空 code 应返回 422。"""
        r = client.post("/api/auth/wechat-login", json={"code": ""})
        assert r.status_code == 422
