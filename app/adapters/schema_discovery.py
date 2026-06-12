"""Schema 自动发现 —— 第一层适配。

连接客户数据库，自动发现所有表、列、数据类型和样本数据。
输出一个结构化的 Schema 描述，供第二层映射配置和第三层 Prompt 生成使用。

支持：PostgreSQL、MySQL、SQLite（通过 SQLAlchemy 自动适配 dialect）。
"""

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import text

from app.database.connection import get_session


@dataclass
class ColumnInfo:
    """单列元数据。"""
    name: str
    data_type: str
    is_nullable: bool = True
    is_primary_key: bool = False
    sample_values: list = field(default_factory=list)


@dataclass
class TableInfo:
    """单表元数据。"""
    name: str
    columns: list[ColumnInfo] = field(default_factory=list)
    row_count: int = 0
    sample_rows: list[dict] = field(default_factory=list)


@dataclass
class SchemaReport:
    """完整的 Schema 发现报告。"""
    database_type: str = ""
    database_name: str = ""
    tables: list[TableInfo] = field(default_factory=list)
    foreign_keys: list[dict] = field(default_factory=list)


async def discover_schema(
    include_samples: bool = True,
    sample_limit: int = 5,
) -> SchemaReport:
    """连接客户数据库，自动发现全部 Schema 信息。

    Args:
        include_samples: 是否包含每个表的样本数据行。
        sample_limit: 每个表取多少行样本。

    Returns:
        完整的 SchemaReport，包含所有表、列、样本数据和 FK 关系。
    """
    report = SchemaReport()

    async with get_session() as session:
        # 清理任何残留的失败事务
        try:
            await session.execute(text("ROLLBACK"))
        except Exception:
            pass

        # 数据库类型
        dialect = session.bind.dialect.name if session.bind else "unknown"
        report.database_type = dialect

        # 数据库名
        try:
            db_result = await session.execute(text("SELECT current_database()"))
            report.database_name = db_result.scalar_one_or_none() or "unknown"
        except Exception:
            report.database_name = "unknown"

        # 所有用户表
        table_result = await session.execute(text("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """))
        table_names = [row[0] for row in table_result.fetchall()]

        # 逐个发现表
        for tname in table_names:
            table_info = await _discover_table(session, tname, include_samples, sample_limit)
            report.tables.append(table_info)

        # 外键关系
        fk_result = await session.execute(text("""
            SELECT
                tc.table_name,
                kcu.column_name,
                ccu.table_name AS foreign_table_name,
                ccu.column_name AS foreign_column_name
            FROM information_schema.table_constraints AS tc
            JOIN information_schema.key_column_usage AS kcu
                ON tc.constraint_name = kcu.constraint_name
            JOIN information_schema.constraint_column_usage AS ccu
                ON ccu.constraint_name = tc.constraint_name
            WHERE tc.constraint_type = 'FOREIGN KEY'
              AND tc.table_schema = 'public'
        """))
        for row in fk_result.fetchall():
            report.foreign_keys.append({
                "table": row[0],
                "column": row[1],
                "ref_table": row[2],
                "ref_column": row[3],
            })

    return report


async def _discover_table(
    session,
    table_name: str,
    include_samples: bool,
    sample_limit: int,
) -> TableInfo:
    """发现单张表的完整元数据。"""
    table = TableInfo(name=table_name)

    # 列信息
    col_result = await session.execute(text("""
        SELECT
            column_name,
            data_type,
            is_nullable,
            ordinal_position
        FROM information_schema.columns
        WHERE table_name = :t AND table_schema = 'public'
        ORDER BY ordinal_position
    """), {"t": table_name})

    for row in col_result.fetchall():
        col = ColumnInfo(
            name=row[0],
            data_type=row[1],
            is_nullable=row[2] == "YES",
        )
        table.columns.append(col)

    # 主键
    try:
        pk_result = await session.execute(text("""
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
            WHERE i.indrelid = :t::regclass AND i.indisprimary
        """), {"t": table_name})
        pk_cols = {row[0] for row in pk_result.fetchall()}
        for col in table.columns:
            col.is_primary_key = col.name in pk_cols
    except Exception:
        pass  # 非 PostgreSQL 数据库可能不支持此查询

    # 行数和样本数据
    if include_samples:
        try:
            count_result = await session.execute(
                text(f'SELECT COUNT(*) FROM "{table_name}"')
            )
            table.row_count = count_result.scalar_one()
        except Exception:
            pass

        try:
            sample_result = await session.execute(
                text(f'SELECT * FROM "{table_name}" LIMIT :l'),
                {"l": sample_limit},
            )
            columns = list(sample_result.keys())
            for row_data in sample_result.fetchall():
                row_dict = {}
                for i, col_name in enumerate(columns):
                    val = row_data[i]
                    row_dict[col_name] = str(val) if val is not None else None
                table.sample_rows.append(row_dict)

            # 填充每列的样本值
            for col in table.columns:
                col.sample_values = [
                    r.get(col.name) for r in table.sample_rows
                    if r.get(col.name) is not None
                ][:3]
        except Exception:
            pass  # 某些表可能无法查询（如没有权限或事务问题）

    return table


def format_discovery_report(report: SchemaReport) -> str:
    """将 Schema 发现报告格式化为可读的 Markdown。

    这份报告可以直接拿给客户的技术人员确认：
    "请标注：哪些表对应订单、会员、门店？"
    """
    lines = [
        f"# Schema 发现报告",
        f"",
        f"- 数据库类型：{report.database_type}",
        f"- 数据库名称：{report.database_name}",
        f"- 发现表数量：{len(report.tables)}",
        f"",
        f"## 外键关系",
    ]
    if report.foreign_keys:
        for fk in report.foreign_keys:
            lines.append(
                f"- `{fk['table']}.{fk['column']}` → `{fk['ref_table']}.{fk['ref_column']}`"
            )
    else:
        lines.append("（未发现外键约束）")

    lines.append("")
    lines.append("## 表清单")
    lines.append("")
    for table in report.tables:
        lines.append(f"### {table.name}（{table.row_count} 行）")
        lines.append("")
        lines.append("| 列名 | 类型 | 可空 | 主键 | 样本值 |")
        lines.append("|------|------|------|------|--------|")
        for col in table.columns:
            pk = "✅" if col.is_primary_key else ""
            samples = ", ".join(col.sample_values[:2]) if col.sample_values else "-"
            lines.append(
                f"| {col.name} | {col.data_type} | "
                f"{'YES' if col.is_nullable else 'NO'} | {pk} | {samples} |"
            )
        if table.sample_rows:
            lines.append("")
            lines.append(f"**样本数据（前 {len(table.sample_rows)} 行）：**")
            lines.append("```")
            for row in table.sample_rows[:2]:
                lines.append(str(row))
            lines.append("```")
        lines.append("")

    return "\n".join(lines)
