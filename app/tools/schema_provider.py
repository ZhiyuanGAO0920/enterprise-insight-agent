"""Schema 提供器 —— 向 LLM Agent 暴露数据库元数据。

Agent 调用此工具来发现表名、列名、数据类型
和可空性，以便编写 SQL 查询。
"""

from typing import Optional

from sqlalchemy import text

from app.database.connection import get_session


async def get_table_schema(table_name: Optional[str] = None) -> str:
    """返回分析型数据库的 schema 元数据。

    Args:
        table_name: 如果提供，返回该表的列级详情。
                    如果为 None，返回所有公共表的列表。

    Returns:
        用管道分隔的文本格式 schema 信息。
    """
    async with get_session() as session:
        if table_name:
            result = await session.execute(
                text(
                    """
                    SELECT column_name, data_type, is_nullable
                    FROM information_schema.columns
                    WHERE table_name = :t
                    ORDER BY ordinal_position
                    """
                ),
                {"t": table_name},
            )
        else:
            result = await session.execute(
                text(
                    """
                    SELECT table_name, table_type
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    ORDER BY table_name
                    """
                ),
            )

        rows = result.fetchall()
        if not rows:
            return "(no tables found)"

        return "\n".join(" | ".join(str(c) for c in row) for row in rows)
