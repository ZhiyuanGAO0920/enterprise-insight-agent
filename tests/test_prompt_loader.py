"""提示词加载器测试 — V3 功能 (P1-3)。

覆盖 YAML 加载、回退行为、热重载和数据库同步。
"""

import os
import tempfile

import pytest
import yaml


class TestPromptLoader:
    """PromptLoader 类的测试。"""

    def test_loader_enabled_returns_yaml_content(self):
        """V4: FEATURE_PROMPT_YAML 默认 true，get_prompt 应返回 YAML 内容。"""
        from app.tools.prompt_loader import PromptLoader

        loader = PromptLoader()
        assert loader.is_enabled() is True
        result = loader.get_prompt("sales", "system_prompt", fallback="TEST_FALLBACK")
        # V4 默认启用 → 返回 YAML prompt 内容，不是 fallback
        assert result != "TEST_FALLBACK"
        assert len(result) > 50

    def test_loader_lists_agents(self):
        """list_agents 返回所有已加载的 Agent，不受功能开关影响。"""
        from app.tools.prompt_loader import PromptLoader

        loader = PromptLoader()
        agents = loader.list_agents()
        assert len(agents) >= 6  # At minimum all core agents
        agent_names = [a["agent"] for a in agents]
        assert "sales" in agent_names
        assert "report" in agent_names
        assert "supervisor" in agent_names

    def test_get_all_prompts_returns_content(self):
        """V4: FEATURE_PROMPT_YAML 默认 true，get_all_prompts 应返回 prompt 内容。"""
        from app.tools.prompt_loader import PromptLoader

        loader = PromptLoader()
        result = loader.get_all_prompts("sales")
        # V4 默认启用 → 返回 YAML 中的 prompts
        assert isinstance(result, dict)
        assert len(result) > 0

    def test_reload_returns_count(self):
        """reload() 应返回已加载的 Agent 数量。"""
        from app.tools.prompt_loader import PromptLoader

        loader = PromptLoader()
        count = loader.reload()
        assert count >= 6

    def test_agent_info(self):
        """get_agent_info 返回现有 Agent 的元数据。"""
        from app.tools.prompt_loader import PromptLoader

        loader = PromptLoader()
        info = loader.get_agent_info("sales")
        assert info is not None
        assert info["agent"] == "sales"
        assert "1.0.0" in info["version"]
        assert "system_prompt" in info["prompts"]

    def test_agent_info_nonexistent(self):
        """get_agent_info 对不存在的 Agent 返回 None。"""
        from app.tools.prompt_loader import PromptLoader

        loader = PromptLoader()
        assert loader.get_agent_info("nonexistent_agent") is None

    def test_custom_yaml_dir(self, tmp_path):
        """PromptLoader 可以从自定义目录加载。"""
        yaml_dir = tmp_path / "prompts"
        yaml_dir.mkdir()
        test_yaml = yaml_dir / "test_agent.yaml"
        test_yaml.write_text(
            yaml.dump({
                "agent": "test_agent",
                "version": "0.1.0",
                "prompts": {
                    "system_prompt": "You are a test agent.",
                    "greeting": "Hello!",
                },
            }),
            encoding="utf-8",
        )

        from app.tools.prompt_loader import PromptLoader

        loader = PromptLoader(yaml_dir=str(yaml_dir))
        agents = loader.list_agents()
        assert any(a["agent"] == "test_agent" for a in agents)

    def test_singleton(self):
        """get_prompt_loader 返回同一个实例（lru_cache）。"""
        from app.tools.prompt_loader import get_prompt_loader

        loader1 = get_prompt_loader()
        loader2 = get_prompt_loader()
        assert loader1 is loader2

    def test_get_prompt_enabled_returns_yaml(self, monkeypatch, tmp_path):
        """当 FEATURE_PROMPT_YAML=true 时，get_prompt 返回 YAML 内容。"""
        # 创建测试 YAML 目录
        yaml_dir = tmp_path / "prompts"
        yaml_dir.mkdir()
        sales_yaml = yaml_dir / "sales.yaml"
        sales_yaml.write_text(
            yaml.dump({
                "agent": "sales",
                "version": "1.0.0",
                "prompts": {
                    "system_prompt": "YAML_LOADED_PROMPT_FOR_TEST",
                },
            }),
            encoding="utf-8",
        )

        from app.tools.prompt_loader import PromptLoader, get_prompt_loader

        # 绕过单例进行本次测试 —— 使用测试目录创建新的加载器
        loader = PromptLoader(yaml_dir=str(yaml_dir))

        # 临时覆盖单例
        import app.tools.prompt_loader as pl
        pl.get_prompt_loader = lambda: loader

        # 启用功能标志
        from app.config import get_settings
        monkeypatch.setattr(get_settings(), "feature_prompt_yaml", True)
        assert loader.is_enabled() is True

        # 应返回 YAML 内容
        result = loader.get_prompt("sales", "system_prompt", fallback="FALLBACK")
        assert result == "YAML_LOADED_PROMPT_FOR_TEST"

    def test_get_prompt_missing_key_returns_fallback(self, monkeypatch, tmp_path):
        """当键在 YAML 中不存在时，返回 fallback。"""
        yaml_dir = tmp_path / "prompts"
        yaml_dir.mkdir()
        sales_yaml = yaml_dir / "sales.yaml"
        sales_yaml.write_text(
            yaml.dump({
                "agent": "sales",
                "version": "1.0.0",
                "prompts": {
                    "system_prompt": "Real prompt",
                },
            }),
            encoding="utf-8",
        )

        from app.tools.prompt_loader import PromptLoader
        from app.config import get_settings

        loader = PromptLoader(yaml_dir=str(yaml_dir))
        monkeypatch.setattr(get_settings(), "feature_prompt_yaml", True)

        # 键 'nonexistent_key' 不存在 —— 应回退到 fallback
        result = loader.get_prompt("sales", "nonexistent_key", fallback="FALLBACK_VALUE")
        assert result == "FALLBACK_VALUE"

    def test_broken_yaml_no_crash(self, tmp_path):
        """损坏的 YAML 文件不应导致加载器崩溃。"""
        yaml_dir = tmp_path / "prompts"
        yaml_dir.mkdir()
        # 创建一个有效的文件
        (yaml_dir / "good.yaml").write_text(
            yaml.dump({"agent": "good", "version": "1.0", "prompts": {"x": "y"}}),
            encoding="utf-8",
        )
        # 创建一个损坏的文件
        (yaml_dir / "broken.yaml").write_text(": invalid yaml ::: [[[", encoding="utf-8")

        from app.tools.prompt_loader import PromptLoader

        loader = PromptLoader(yaml_dir=str(yaml_dir))
        # 不应崩溃 —— 损坏的文件被跳过
        agents = loader.list_agents()
        assert any(a["agent"] == "good" for a in agents)
