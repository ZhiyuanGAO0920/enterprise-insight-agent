"""提示词加载器 — V3 功能 (P1-3)。

当 FEATURE_PROMPT_YAML 启用时，从 YAML 文件加载 Agent 提示词，
否则回退到硬编码的 Python 字符串常量。

受 FEATURE_PROMPT_YAML 环境变量控制。禁用时，get_prompt()
始终返回回退值 —— Agent 无需条件逻辑。
"""

import os
from functools import lru_cache

import yaml

from app.config import get_settings


class PromptLoader:
    """从 YAML 文件加载并缓存提示词。

    用法：
        loader = PromptLoader()
        prompt = loader.get_prompt("sales", "system_prompt", fallback=SALES_SYSTEM_PROMPT)
    """

    def __init__(self, yaml_dir: str | None = None):
        self._cache: dict[str, dict] = {}
        if yaml_dir is None:
            yaml_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                "prompts", "yaml",
            )
        self._yaml_dir = yaml_dir
        self._load_all()

    def _load_all(self) -> None:
        """将所有 YAML 文件从 yaml 目录加载到内存中。"""
        self._cache.clear()
        if not os.path.isdir(self._yaml_dir):
            return

        for filename in os.listdir(self._yaml_dir):
            if not filename.endswith((".yaml", ".yml")):
                continue
            filepath = os.path.join(self._yaml_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if isinstance(data, dict) and "agent" in data and "prompts" in data:
                    self._cache[data["agent"]] = {
                        "version": data.get("version", "0.0.0"),
                        "file": filename,
                        "prompts": data["prompts"],
                    }
            except (yaml.YAMLError, OSError) as e:
                # 跳过损坏的 YAML 文件 —— 不要让加载器崩溃
                import logging
                logging.getLogger("prompt_loader").warning(
                    f"无法加载 {filename}: {e}"
                )

    def is_enabled(self) -> bool:
        """检查是否通过功能标志启用了 YAML 提示词加载。"""
        return get_settings().feature_prompt_yaml

    def get_prompt(self, agent: str, key: str, fallback: str = "") -> str:
        """获取指定 Agent 和键的提示词值。

        Args:
            agent: Agent 名称（例如 'sales'、'report'、'chart_advisor'）
            key: YAML 中的提示词键（例如 'system_prompt'、'human_template'）
            fallback: YAML 禁用、Agent 未找到或键缺失时返回的值。
                      始终在此传入硬编码的常量。

        Returns:
            如果已启用且找到则返回 YAML 提示词，否则返回 fallback。
        """
        if not self.is_enabled():
            return fallback

        agent_data = self._cache.get(agent)
        if agent_data is None:
            return fallback

        return agent_data.get("prompts", {}).get(key, fallback)

    def get_all_prompts(self, agent: str) -> dict[str, str]:
        """以字典形式获取指定 Agent 的所有提示词。

        如果 Agent 未找到或 YAML 被禁用，返回空字典。
        """
        if not self.is_enabled():
            return {}
        agent_data = self._cache.get(agent)
        if agent_data is None:
            return {}
        return dict(agent_data.get("prompts", {}))

    def list_agents(self) -> list[dict]:
        """列出所有已加载的 Agent 及其版本和文件名。"""
        return [
            {
                "agent": name,
                "version": data["version"],
                "file": data["file"],
                "prompt_keys": list(data["prompts"].keys()),
            }
            for name, data in sorted(self._cache.items())
        ]

    def reload(self) -> int:
        """从磁盘重新加载所有 YAML 文件。返回已加载的 Agent 数量。"""
        self._load_all()
        return len(self._cache)

    def get_agent_info(self, agent: str) -> dict | None:
        """获取指定 Agent 的元数据（版本、文件、提示词键）。"""
        data = self._cache.get(agent)
        if data is None:
            return None
        return {
            "agent": agent,
            "version": data["version"],
            "file": data["file"],
            "prompts": dict(data["prompts"]),
        }


# 模块级单例 —— 与 get_settings() 相同的模式
@lru_cache
def get_prompt_loader() -> PromptLoader:
    """返回缓存的 PromptLoader 单例。"""
    return PromptLoader()


# ============================================================================
# 客户适配 Prompt 解析
# ============================================================================


def resolve_agent_prompt(agent: str, fallback: str) -> str:
    """解析 Agent 的 System Prompt，自动适配客户数据库 Schema。

    优先级（高→低）：
      1. 客户配置（customer_schema.yaml）→ PromptBuilder 动态生成
      2. YAML Prompt（prompts/yaml/*.yaml，需 FEATURE_PROMPT_YAML=true）
      3. Python 硬编码 Prompt（fallback 参数）

    如果客户配置中该 Agent 所需的表标记为 null（客户无此模块），
    返回不可用提示文本，Agent 应据此跳过分析。

    Args:
        agent: Agent 名称（sales/crm/finance/inventory/supply_chain）
        fallback: Python 硬编码的兜底 Prompt

    Returns:
        适配后的 System Prompt 或 fallback。
    """
    # 第一优先级：客户 Schema 映射
    try:
        from app.adapters.schema_mapping import get_customer_config, CustomerConfig
        config = get_customer_config()

        # 如果是默认配置（零映射），跳过动态生成
        if config.name == "默认（开发环境）":
            pass
        else:
            from app.adapters.prompt_builder import PromptBuilder
            builder = PromptBuilder(config)
            agent_builders = {
                "sales": builder.build_sales_prompt,
                "crm": builder.build_crm_prompt,
                "finance": builder.build_finance_prompt,
                "inventory": builder.build_inventory_prompt,
                "supply_chain": builder.build_supply_chain_prompt,
            }
            if agent in agent_builders:
                dynamic_prompt = agent_builders[agent]()
                if dynamic_prompt and "不可用" not in dynamic_prompt:
                    return dynamic_prompt
    except Exception:
        pass  # 适配失败不影响主流程，回退到标准 Prompt

    # 第二优先级：YAML Prompt
    loader = get_prompt_loader()
    yaml_prompt = loader.get_prompt(agent, "system_prompt", fallback="")
    if yaml_prompt:
        return yaml_prompt

    # 第三优先级：Python 硬编码
    return fallback
