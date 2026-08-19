"""T-12 应用内金丝雀定时兜底 —— 幂等判断测试。

设计说明：幂等判据 canary_ran_since 依赖 eval_runs 的"最近 N 天是否有记录"状态，
该状态会被真实评估（手动触发/n8n/定时）污染，因此：
- 逻辑测试用 mock（不依赖 DB 外部状态，全量跑稳定）
- 真库集成只保留"插入当天记录→True"（自包含，创建即删，不受污染影响）
"""

from datetime import datetime

import pytest

from app.database.connection import get_session
from app.database.models import EvalRun
from app.scheduler import canary_ran_since


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


@pytest.mark.asyncio
async def test_no_record_recently_returns_false(monkeypatch):
    """最近 N 天无记录 → False（应触发评估）。mock 数据库层，不依赖外部状态。"""
    monkeypatch.setattr("app.scheduler.get_session", lambda: _FakeSession(0))
    assert await canary_ran_since(7) is False


@pytest.mark.asyncio
async def test_record_recently_returns_true(monkeypatch):
    """最近 N 天有记录 → True（幂等跳过）。"""
    monkeypatch.setattr("app.scheduler.get_session", lambda: _FakeSession(1))
    assert await canary_ran_since(7) is True


@pytest.mark.asyncio
async def test_real_db_insert_then_true():
    """真库集成：插入当天 canary 记录 → True。自包含（创建即删）。"""
    session = get_session()
    fake = EvalRun(
        run_at=datetime.utcnow(),  # 当天 UTC
        model_version="deepseek-v4-flash",
        canary=True,
        total=16, passed=9, failed=7,
        pass_rate=56.3,
    )
    try:
        session.add(fake)
        await session.commit()
        assert await canary_ran_since(7) is True
    finally:
        await session.delete(fake)
        await session.commit()
        await session.close()
