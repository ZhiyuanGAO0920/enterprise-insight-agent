"""通过 pydantic-settings 进行应用配置。

使用 @lru_cache 单例模式确保配置只加载一次。
所有配置从 .env 文件和环境变量中读取。
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- DeepSeek (LLM only) ---
    deepseek_api_key: str
    deepseek_model_name: str = "deepseek-v4-pro"  # 可选：deepseek-v4-flash（思考模式，不支持 tool_choice）
    deepseek_base_url: str = "https://api.deepseek.com/v1"
    llm_temperature: float = 0.0
    llm_max_tokens: int = 8192  # 必须大于推理 tokens；100 行表格需要约 5K tokens

    # --- 嵌入向量提供商 ---
    # "ollama" —— Ollama 本地 BGE-M3（http://localhost:11434，1024 维）
    # "openai" —— OpenAI text-embedding-3-small（1536 维）
    embedding_provider: str = "ollama"
    embedding_model_name: str = "bge-m3:latest"
    ollama_base_url: str = "http://localhost:11434"
    openai_api_key: str = ""  # 仅在 embedding_provider="openai" 时需要

    # --- Database ---
    database_url: str
    database_url_sync: str
    database_url_test: str = "sqlite+aiosqlite:///./test.db"

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- JWT Auth ---
    jwt_secret_key: str
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 480

    # --- System user for scheduled tasks (n8n webhook, cron) ---
    system_user_id: int = 0  # 系统用户 ID，用于周报生成等定时任务

    # --- Logging ---
    log_level: str = "INFO"
    log_format: str = "console"  # "console" | "json"（生产环境设置 LOG_FORMAT=json）

    # --- n8n ---
    n8n_webhook_secret: str = "whsec-default"

    # --- pgvector ---
    embedding_dimension: int = 1024  # BGE-M3 维度

    # --- Server ---
    server_port: int = 8002  # V4 default（V2:8000, V3:8001）

    # --- WeChat Mini Program ---
    wechat_appid: str = ""
    wechat_secret: str = ""
    # Demo 后门开关：未配置 WECHAT_APPID 时，_wechat_code2session 返回固定 openid
    # （demo_wechat_dev_user）——任何请求方可用任意 code 换取该 openid 绑定账号的 JWT。
    # 仅允许单用户 Demo/本地开发使用；生产必须置 false 并配置真实 WECHAT_APPID/SECRET。
    wechat_demo_mode: bool = True

    # --- CORS ---
    cors_origins: str = "http://localhost:5173,http://localhost:3000"  # 逗号分隔，"*" 表示全部允许（仅开发）

    # --- Customer Schema Adapter ---
    customer_schema_yaml: str = "customer_schema.yaml"  # 客户 Schema 映射配置文件路径

    # --- Analysis limits ---
    max_sql_rows: int = 1000
    max_parallel_agents: int = 3

    # --- Fallback LLM Provider（当 DeepSeek 不可用时自动切换） ---
    fallback_api_key: str = ""
    fallback_base_url: str = "https://api.xiaomimimo.com/v1"
    fallback_model_name: str = "mimo-v2.5"

    # =========================================================================
    # V3 Feature Flags — 全部功能已通过测试验证，默认开启
    # =========================================================================
    # P0: Core experience upgrades
    feature_chart: bool = True               # ECharts 可视化图表
    feature_multi_turn: bool = True          # 多轮对话上下文
    feature_data_trace: bool = True          # 数据来源可追溯
    # P1: Quality of life
    feature_mobile_ui: bool = True           # 移动端适配 UI
    feature_feedback: bool = True            # 用户反馈闭环
    feature_prompt_yaml: bool = True         # Prompt YAML 外部化
    # P2: Operations
    feature_apm: bool = True                 # Agent 执行性能追踪
    feature_friendly_errors: bool = True     # 用户友好错误消息

    # =========================================================================
    # V4.1 通知 Webhook（预留，空字符串 = 不发送）
    # =========================================================================
    feishu_webhook_url: str = ""             # 飞书机器人 webhook URL
    dingtalk_webhook_url: str = ""           # 钉钉机器人 webhook URL
    wecom_webhook_url: str = ""              # 企业微信机器人 webhook URL


@lru_cache
def get_settings() -> Settings:
    """返回缓存的 Settings 单例。"""
    return Settings()
