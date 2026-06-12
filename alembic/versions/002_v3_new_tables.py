"""V3 新表 —— 仅向后兼容的增量添加。

修订 ID: 002_v3_new_tables
创建日期: 2026-06-09

所有表使用 IF NOT EXISTS —— 可安全地在运行中的 V2 数据库上执行。
无 ALTER/DROP/RENAME 操作。V2 代码完全不受影响。
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002_v3_new_tables"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- 用户反馈 (P1-2) ----
    op.execute("""
        CREATE TABLE IF NOT EXISTS user_feedback (
            id SERIAL PRIMARY KEY,
            analysis_history_id INT REFERENCES analysis_history(id),
            user_id INT REFERENCES users(id),
            rating VARCHAR(10) NOT NULL,
            reason TEXT,
            agent_issues JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # ---- Agent 性能追踪 (P2-1) ----
    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_trace_events (
            id BIGSERIAL PRIMARY KEY,
            session_id VARCHAR(64),
            node_name VARCHAR(50) NOT NULL,
            question_hash INT,
            elapsed_ms INT NOT NULL,
            error TEXT,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_trace_node
        ON agent_trace_events(node_name, created_at)
    """)

    # ---- 对话会话 (P0-2) —— Redis 为主存储，此为可选的数据库备份 ----
    op.execute("""
        CREATE TABLE IF NOT EXISTS conversation_sessions (
            id SERIAL PRIMARY KEY,
            session_key VARCHAR(64) UNIQUE NOT NULL,
            user_id INT REFERENCES users(id),
            turn_count INT DEFAULT 0,
            entity_memory JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)

    # ---- 提示词版本追踪 (P1-3) ----
    op.execute("""
        CREATE TABLE IF NOT EXISTS prompt_versions (
            id SERIAL PRIMARY KEY,
            agent VARCHAR(50) NOT NULL,
            version VARCHAR(20) NOT NULL,
            status VARCHAR(20) DEFAULT 'production',
            config_yaml TEXT,
            created_at TIMESTAMP DEFAULT NOW(),
            UNIQUE(agent, version)
        )
    """)


def downgrade() -> None:
    # 按逆序删除（遵循外键约束）
    op.execute("DROP TABLE IF EXISTS prompt_versions CASCADE")
    op.execute("DROP TABLE IF EXISTS conversation_sessions CASCADE")
    op.execute("DROP TABLE IF EXISTS agent_trace_events CASCADE")
    op.execute("DROP TABLE IF EXISTS user_feedback CASCADE")
