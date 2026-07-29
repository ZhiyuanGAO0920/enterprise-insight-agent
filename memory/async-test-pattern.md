---
name: async-test-pattern
description: 项目测试中必须使用 @pytest.mark.asyncio 而非 asyncio.run()
metadata:
  type: reference
---

# 测试异步模式

所有包含 `ContextManager` 或任何 Redis/数据库 async 调用的测试，必须使用 `@pytest.mark.asyncio` + `await`，**禁止** `asyncio.run()`。

**Why:** `asyncio.run()` 创建独立事件循环，与 pytest-asyncio 管理的循环冲突，导致 `RuntimeError: Event loop is closed`。

**How to apply:**

```python
# ❌ 错误
def test_something(self):
    result = asyncio.run(ctx.is_followup(q))

# ✅ 正确
@pytest.mark.asyncio
async def test_something(self):
    result = await ctx.is_followup(q)
```

**conftest 中必须设置 `FEATURE_MULTI_TURN=false`** 避免测试无意连接 Redis，调用 `get_settings.cache_clear()` 确保环境变量修改对所有模块生效。
