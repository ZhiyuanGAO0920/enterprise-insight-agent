"""T-16 应用内告警兜底 —— 幂等判据与接管逻辑测试。

设计说明（同 test_canary_scheduler）：
- 幂等判据 alert_check_ran_since 依赖 audit_log 的"最近 N 小时是否有 /alerts/check
  调用"状态，该状态会被真实 n8n 触发/手工调用污染，因此逻辑测试用 mock（不依赖外部状态）。
- 真库集成只保留"插入记录 → True"（自包含，创建即删，不受污染影响）。
"""

from datetime import datetime

import pytest
from sqlalchemy import text

import app.scheduler as scheduler_mod
from app.database.connection import get_session
from app.scheduler import alert_check_ran_since, run_alert_check_cycle


class _FakeResult:
    def __init__(self, n: int):
        self._n = n

    def scalar(self):
        return self._n


class _FakeSession:
    """假 session：execute 返回固定计数。"""

    def __init__(self, n: int):
        self._n = n

    async def execute(self, *args, **kwargs):  # noqa: ANN002, ANN003
        return _FakeResult(self._n)

    async def close(self):
        pass


# ---------------------------------------------------------------------------
# 幂等判据
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_no_recent_call_returns_false(monkeypatch):
    """最近 N 小时无 /alerts/check 调用 → False（n8n 停摆，应接管）。"""
    monkeypatch.setattr("app.scheduler.get_session", lambda: _FakeSession(0))
    assert await alert_check_ran_since(20) is False


@pytest.mark.asyncio
async def test_recent_call_returns_true(monkeypatch):
    """最近 N 小时有调用 → True（n8n 正常，幂等跳过）。"""
    monkeypatch.setattr("app.scheduler.get_session", lambda: _FakeSession(1))
    assert await alert_check_ran_since(20) is True


@pytest.mark.asyncio
async def test_real_db_insert_then_true():
    """真库集成：插入一条 /alerts/check 审计记录 → True。自包含（创建即删）。"""
    session = get_session()
    now = datetime.utcnow()
    try:
        await session.execute(
            text(
                "INSERT INTO audit_log (action, resource, created_at) "
                "VALUES ('POST', '/api/v1/alerts/check', :now)"
            ),
            {"now": now},
        )
        await session.commit()
        assert await alert_check_ran_since(20) is True
    finally:
        await session.execute(
            text(
                "DELETE FROM audit_log "
                "WHERE resource = '/api/v1/alerts/check' AND created_at = :now"
            ),
            {"now": now},
        )
        await session.commit()
        await session.close()


# ---------------------------------------------------------------------------
# 单次兜底周期（skipped / fallback + 停摆提示去重）
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cycle_skips_when_n8n_alive(monkeypatch):
    """n8n 正常（有调用记录）→ skipped：不执行兜底检测，并重置停摆提示状态。"""
    scheduler_mod._n8n_down_notified = True  # 预置"已提示停摆"状态
    ran = {"check": False}

    async def _fake_ran_since(hours: int) -> bool:
        return True

    async def _fake_run_now() -> bool:
        ran["check"] = True
        return True

    monkeypatch.setattr(scheduler_mod, "alert_check_ran_since", _fake_ran_since)
    monkeypatch.setattr(scheduler_mod, "run_alert_check_now", _fake_run_now)

    assert await run_alert_check_cycle(20) == "skipped"
    assert ran["check"] is False
    assert scheduler_mod._n8n_down_notified is False  # n8n 恢复 → 重置


@pytest.mark.asyncio
async def test_cycle_fallback_notifies_once_then_keeps_checking(monkeypatch):
    """n8n 停摆 → fallback：执行检测 + 首次推送停摆提示；后续周期不再重复推送。"""
    scheduler_mod._n8n_down_notified = False
    sent = {"notify": 0, "check": 0}

    async def _fake_ran_since(hours: int) -> bool:
        return False

    async def _fake_run_now() -> bool:
        sent["check"] += 1
        return True

    async def _fake_send_notification(title: str, content: str) -> dict:
        sent["notify"] += 1
        return {"feishu": True}

    monkeypatch.setattr(scheduler_mod, "alert_check_ran_since", _fake_ran_since)
    monkeypatch.setattr(scheduler_mod, "run_alert_check_now", _fake_run_now)
    # cycle 内为函数级 from-import，patch 源模块属性即可生效
    monkeypatch.setattr("app.services.notification.send_notification", _fake_send_notification)

    assert await run_alert_check_cycle(20) == "fallback"
    assert sent == {"notify": 1, "check": 1}

    # 第二个周期：n8n 仍停摆 → 提示不重复，检测继续
    assert await run_alert_check_cycle(20) == "fallback"
    assert sent == {"notify": 1, "check": 2}
