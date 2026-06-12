"""客户适配层 —— 使 Agent 能适配不同客户的数据库 Schema。

三层架构：
  1. schema_discovery  — 自动发现客户数据库的表和列
  2. schema_mapping    — 建立「逻辑概念 → 物理表/列」的映射
  3. prompt_builder    — 根据映射动态生成适配后的 Agent Prompt

用法：
    from app.adapters import SchemaDiscovery, SchemaMapping, PromptBuilder
"""
