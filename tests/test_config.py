"""应用配置的冒烟测试。"""

import os


def test_settings_load_from_env():
    """验证 Settings 可以从环境变量中加载配置。"""
    os.environ["DEEPSEEK_API_KEY"] = "test-deepseek-key"
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://localhost/test"
    os.environ["DATABASE_URL_SYNC"] = "postgresql+psycopg2://localhost/test"
    os.environ["JWT_SECRET_KEY"] = "test-secret"

    from app.config import get_settings

    # 清除 lru_cache 以获取新的环境变量
    get_settings.cache_clear()
    settings = get_settings()

    assert settings.deepseek_api_key == "test-deepseek-key"
    assert "deepseek" in settings.deepseek_model_name
    assert settings.deepseek_base_url == "https://api.deepseek.com/v1"
    assert settings.embedding_provider == "ollama"
    assert settings.embedding_model_name == "bge-m3:latest"
    assert settings.ollama_base_url == "http://localhost:11434"
    assert settings.llm_max_tokens == 8192  # V2 修复：从 4096 提升以支持 100 行表格
    assert settings.max_sql_rows == 1000
    assert settings.embedding_dimension == 1024


def test_settings_defaults():
    """验证默认值正确生效。"""
    os.environ["DEEPSEEK_API_KEY"] = "test-deepseek-key"
    os.environ["DATABASE_URL"] = "postgresql+asyncpg://localhost/test"
    os.environ["DATABASE_URL_SYNC"] = "postgresql+psycopg2://localhost/test"
    os.environ["JWT_SECRET_KEY"] = "test-secret"

    from app.config import get_settings

    get_settings.cache_clear()
    settings = get_settings()

    assert settings.redis_url == "redis://localhost:6379/0"
    assert settings.jwt_algorithm == "HS256"
    assert settings.jwt_expire_minutes == 480
    assert settings.log_level == "INFO"
