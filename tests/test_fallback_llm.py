"""Fallback LLM 单元测试。

验证 FallbackLLM / FallbackBoundLLM 的自动降级逻辑：
1. 主 LLM 成功 → 直接使用主 LLM 结果
2. 主 LLM 失败 → 自动切换到备用 LLM
3. 主+备都失败 → 异常向上传播
4. create_llm() 根据配置返回正确的类型
"""
# pylint: disable=redefined-outer-name

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ============================================================================
# FallbackLLM / FallbackBoundLLM 单元测试
# ============================================================================


@pytest.fixture
def mock_primary():
    """模拟主 LLM（ChatOpenAI）。"""
    m = MagicMock()
    m.model = "deepseek-v4-pro"
    m.ainvoke = AsyncMock()
    m.invoke = MagicMock()
    m.astream = MagicMock()
    return m


@pytest.fixture
def mock_fallback():
    """模拟备用 LLM（MiMo ChatOpenAI）。"""
    m = MagicMock()
    m.model = "mimo-v2.5"
    m.ainvoke = AsyncMock()
    m.invoke = MagicMock()
    m.astream = MagicMock()
    return m


class TestFallbackLLM:
    """FallbackLLM 包装器测试。"""

    def test_init_no_fallback(self):
        """无 fallback 时 FallbackLLM 只持有 primary。"""
        from app.llm import FallbackLLM

        primary = MagicMock()
        llm = FallbackLLM(primary=primary, fallback=None)
        assert llm._fallback is None
        assert llm._primary is primary

    @pytest.mark.asyncio
    async def test_ainvoke_primary_success(self, mock_primary, mock_fallback):
        """主 LLM 成功 → fallback 不被调用。"""
        from app.llm import FallbackLLM

        mock_primary.ainvoke.return_value = "primary result"
        llm = FallbackLLM(primary=mock_primary, fallback=mock_fallback)

        result = await llm.ainvoke("test input")

        assert result == "primary result"
        mock_primary.ainvoke.assert_awaited_once_with("test input")
        mock_fallback.ainvoke.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_ainvoke_primary_failure(self, mock_primary, mock_fallback):
        """主 LLM 失败 → 自动切换到 fallback。"""
        from app.llm import FallbackLLM

        mock_primary.ainvoke.side_effect = Exception("Connection timeout")
        mock_fallback.ainvoke.return_value = "fallback result"
        llm = FallbackLLM(primary=mock_primary, fallback=mock_fallback)

        result = await llm.ainvoke("test input")

        assert result == "fallback result"
        mock_primary.ainvoke.assert_awaited_once_with("test input")
        mock_fallback.ainvoke.assert_awaited_once_with("test input")

    @pytest.mark.asyncio
    async def test_ainvoke_all_fail(self, mock_primary, mock_fallback):
        """主+备都失败 → 异常向上传播。"""
        from app.llm import FallbackLLM

        mock_primary.ainvoke.side_effect = Exception("Primary error")
        mock_fallback.ainvoke.side_effect = Exception("Fallback also down")
        llm = FallbackLLM(primary=mock_primary, fallback=mock_fallback)

        with pytest.raises(Exception, match="Fallback also down"):
            await llm.ainvoke("test input")

        mock_primary.ainvoke.assert_awaited_once_with("test input")
        mock_fallback.ainvoke.assert_awaited_once_with("test input")

    def test_invoke_primary_success(self, mock_primary, mock_fallback):
        """同步 invoke，主 LLM 成功。"""
        from app.llm import FallbackLLM

        mock_primary.invoke.return_value = "sync primary"
        llm = FallbackLLM(primary=mock_primary, fallback=mock_fallback)

        result = llm.invoke("test")

        assert result == "sync primary"
        mock_primary.invoke.assert_called_once_with("test")
        mock_fallback.invoke.assert_not_called()

    def test_invoke_primary_failure(self, mock_primary, mock_fallback):
        """同步 invoke，主 LLM 失败 → fallback。"""
        from app.llm import FallbackLLM

        mock_primary.invoke.side_effect = Exception("Timeout")
        mock_fallback.invoke.return_value = "sync fallback"
        llm = FallbackLLM(primary=mock_primary, fallback=mock_fallback)

        result = llm.invoke("test")

        assert result == "sync fallback"
        mock_primary.invoke.assert_called_once_with("test")
        mock_fallback.invoke.assert_called_once_with("test")

    @pytest.mark.asyncio
    async def test_astream_primary_success(self, mock_primary, mock_fallback):
        """流式调用，主 LLM 成功。"""
        from app.llm import FallbackLLM

        async def _primary_gen(_messages, **_kw):
            for chunk in ["A", "B", "C"]:
                yield chunk

        mock_primary.astream.return_value = _primary_gen("test")
        llm = FallbackLLM(primary=mock_primary, fallback=mock_fallback)

        result = [chunk async for chunk in llm.astream("test")]

        assert result == ["A", "B", "C"]
        mock_fallback.astream.assert_not_called()

    @pytest.mark.asyncio
    async def test_astream_primary_failure(self, mock_primary, mock_fallback):
        """流式调用，主 LLM 失败 → fallback 重新流式。"""
        from app.llm import FallbackLLM

        # 主 LLM 流式在第一次迭代时抛出异常
        async def _fail_gen(_messages, **_kw):
            raise Exception("Stream broken")
            yield  # pragma: no cover

        async def _fallback_gen(_messages, **_kw):
            for chunk in ["X", "Y", "Z"]:
                yield chunk

        mock_primary.astream.return_value = _fail_gen("test")
        mock_fallback.astream.return_value = _fallback_gen("test")
        llm = FallbackLLM(primary=mock_primary, fallback=mock_fallback)

        result = [chunk async for chunk in llm.astream("test")]

        assert result == ["X", "Y", "Z"]
        mock_fallback.astream.assert_called_once()

    def test_bind_tools(self, mock_primary, mock_fallback):
        """bind_tools 返回 FallbackBoundLLM。"""
        from app.llm import FallbackLLM, FallbackBoundLLM

        mock_primary.bind_tools.return_value = MagicMock()
        mock_fallback.bind_tools.return_value = MagicMock()
        llm = FallbackLLM(primary=mock_primary, fallback=mock_fallback)

        bound = llm.bind_tools(["tool1"])

        assert isinstance(bound, FallbackBoundLLM)
        mock_primary.bind_tools.assert_called_once_with(["tool1"])
        mock_fallback.bind_tools.assert_called_once_with(["tool1"])

    @pytest.mark.asyncio
    async def test_fallback_bound_ainvoke_primary_failure(self):
        """FallbackBoundLLM.ainvoke 在主 LLM 失败时降级。"""
        from app.llm import FallbackBoundLLM

        primary_bound = MagicMock()
        primary_bound.ainvoke = AsyncMock(side_effect=Exception("Primary error"))
        fallback_bound = MagicMock()
        fallback_bound.ainvoke = AsyncMock(return_value="bound fallback")

        binding = FallbackBoundLLM(primary=primary_bound, fallback=fallback_bound)
        result = await binding.ainvoke("test")

        assert result == "bound fallback"
        primary_bound.ainvoke.assert_awaited_once_with("test")
        fallback_bound.ainvoke.assert_awaited_once_with("test")


# ============================================================================
# create_llm() 集成测试（mock 配置而非真实 LLM）
# ============================================================================


class TestCreateLLM:
    """验证 create_llm 根据配置返回正确类型。"""

    def test_no_fallback_config_returns_plain_llm(self):
        """FALLBACK_API_KEY 为空 → 返回 ChatOpenAI（非 FallbackLLM）。"""
        import app.llm as llm_module
        from app.llm import create_llm, FallbackLLM
        from langchain_openai import ChatOpenAI

        with patch.object(llm_module.settings, "fallback_api_key", ""):
            llm = create_llm()
            assert not isinstance(llm, FallbackLLM)
            assert isinstance(llm, ChatOpenAI)

    def test_with_fallback_config_returns_fallback_llm(self):
        """FALLBACK_API_KEY 非空 → 返回 FallbackLLM。"""
        import app.llm as llm_module
        from app.llm import create_llm, FallbackLLM

        with patch.object(llm_module.settings, "fallback_api_key", "sk-test-key"):
            llm = create_llm()
            assert isinstance(llm, FallbackLLM)

    def test_fallback_passed_to_underlying(self):
        """FALLBACK_API_KEY 非空时，fallback LLM 使用正确的配置。"""
        import app.llm as llm_module
        from app.llm import create_llm, FallbackLLM

        test_key = "sk-test-key-12345"
        with (
            patch.object(llm_module.settings, "fallback_api_key", test_key),
            patch.object(llm_module.settings, "fallback_base_url", "https://mimo.test/v1"),
            patch.object(llm_module.settings, "fallback_model_name", "mimo-test"),
        ):
            llm = create_llm()
            assert isinstance(llm, FallbackLLM)
            assert llm._fallback is not None
            assert llm._fallback.openai_api_key.get_secret_value() == test_key
            assert llm._fallback.openai_api_base == "https://mimo.test/v1"
            assert "mimo-test" in llm._fallback.model
