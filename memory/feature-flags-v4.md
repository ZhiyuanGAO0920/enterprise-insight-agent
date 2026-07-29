---
name: feature-flags-v4
description: V4 所有 Feature Flag 默认 true（V3 曾为 false）
metadata:
  type: reference
---

# V4 Feature Flag 默认值

| Flag | V3 默认 | V4 默认 |
|------|---------|---------|
| `FEATURE_CHART` | false | **true** |
| `FEATURE_MULTI_TURN` | false | **true** |
| `FEATURE_DATA_TRACE` | false | **true** |
| `FEATURE_APM` | false | **true** |
| `FEATURE_FRIENDLY_ERRORS` | false | **true** |
| `FEATURE_FEEDBACK` | true | true |
| `FEATURE_PROMPT_YAML` | false | true |
| `FEATURE_MOBILE_UI` | true | true |

**Why:** V3 功能已通过 137 条测试验证，V4 默认全部开启。

**How to apply:** 测试中需要验证默认值时，必须显式设置环境变量（`os.environ["FLAG"] = "..."`），因为 `get_settings()` 有 `@lru_cache` 单例缓存，且 conftest 会覆盖 `FEATURE_MULTI_TURN=false`。
