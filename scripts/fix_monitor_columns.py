"""修复质量监控需要的缺失数据库列。"""
from sqlalchemy import text, create_engine

engine = create_engine("postgresql+psycopg2://admin:admin123@localhost:15432/enterprise_db")
with engine.connect() as conn:
    conn.execute(text("ALTER TABLE analysis_history ADD COLUMN IF NOT EXISTS followup_questions TEXT"))
    conn.execute(text("ALTER TABLE agent_trace_events ADD COLUMN IF NOT EXISTS trace_id VARCHAR(64)"))
    conn.commit()
    print("OK - columns added")
