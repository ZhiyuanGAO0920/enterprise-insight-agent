"""工具包 —— SQL 执行器、检查器、记忆、嵌入、异常检测。"""

from app.tools.anomaly_detector import check_metric, run_alert_checks
from app.tools.embedding import get_embedding, get_embeddings
from app.tools.memory import find_similar_analyses, get_history_by_user, save_analysis_history
from app.tools.schema_provider import get_table_schema
from app.tools.sql_checker import check_sql_safety
from app.tools.sql_runner import run_sql

__all__ = [
    "run_sql",
    "check_sql_safety",
    "get_table_schema",
    "get_embedding",
    "get_embeddings",
    "save_analysis_history",
    "find_similar_analyses",
    "get_history_by_user",
    "check_metric",
    "run_alert_checks",
]
