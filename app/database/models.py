"""所有数据库表的 SQLAlchemy ORM 模型。

按领域组织：
  - 分析历史（Phase 6）—— 支持向量搜索
  - RBAC（Phase 7）—— 用户、角色、权限
  - 门店访问 —— 行级安全
  - 预警（Phase 7）—— 异常检测
  - 周报（Phase 7）—— 定时报告
"""

from datetime import datetime
from typing import Any


def _utcnow():
    """返回 naive UTC 时间（兼容 TIMESTAMP WITHOUT TIME ZONE）。"""
    from datetime import timezone as _tz
    return datetime.now(_tz.utc).replace(tzinfo=None)

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Integer, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, relationship

# pgvector 仅在 PostgreSQL 中可用。开发/测试环境优雅降级。
try:
    from pgvector.sqlalchemy import Vector
except ImportError:
    # SQLite / 非 PG 降级：使用 LargeBinary 作为占位类型
    from sqlalchemy import LargeBinary as Vector  # type: ignore[assignment]


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------------------
# Phase 6 —— 分析历史（用于长期记忆的向量搜索）
# ---------------------------------------------------------------------------

class AnalysisHistory(Base):
    __tablename__ = "analysis_history"

    id = Column(Integer, primary_key=True, autoincrement=True)
    question = Column(Text, nullable=False)
    report = Column(Text, nullable=False)
    sales_result = Column(Text, nullable=True)
    crm_result = Column(Text, nullable=True)
    finance_result = Column(Text, nullable=True)
    inventory_result = Column(Text, nullable=True)       # V4: 库存分析持久化
    supply_chain_result = Column(Text, nullable=True)    # V4: 供应链分析持久化
    reflection_passed = Column(Boolean, default=False)
    reflection_issues = Column(JSON, nullable=True)
    input_tokens = Column(Integer, default=0)
    output_tokens = Column(Integer, default=0)
    llm_cost = Column(Float, default=0.0)
    create_time = Column(DateTime, default=_utcnow)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    tenant_id = Column(Integer, nullable=True)  # V4: 多租户隔离
    embedding = Column(Vector(1024), nullable=True)  # BGE-M3 嵌入
    share_token = Column(String(64), nullable=True)  # V4.6: 报告分享 token，未分享为 NULL
    share_expires_at = Column(DateTime, nullable=True)  # V4.6: 分享链接过期时间


# ---------------------------------------------------------------------------
# Phase 7 —— RBAC：用户、角色、权限
# ---------------------------------------------------------------------------

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), unique=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    display_name = Column(String(200), nullable=True)
    is_active = Column(Boolean, default=True)
    tenant_id = Column(Integer, ForeignKey("tenants.id"), nullable=True)  # V4: 多租户
    created_at = Column(DateTime, default=_utcnow)

    roles = relationship("Role", secondary="user_roles", back_populates="users")


# =============================================================================
# V4: 多租户
# =============================================================================


class Tenant(Base):
    """租户 —— 每个客户/企业一个租户。

    V4 支持 Database-per-tenant 和 Schema-per-tenant 两种模式。
    默认使用 shared-database + tenant_id 隔离（最小复杂度）。
    """

    __tablename__ = "tenants"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), unique=True, nullable=False, comment="租户名称")
    slug = Column(String(50), unique=True, nullable=False, comment="租户标识符")
    db_schema = Column(String(50), nullable=True, comment="Schema-per-tenant 模式下的 PostgreSQL schema 名")
    db_url = Column(String(500), nullable=True, comment="Database-per-tenant 模式下的独立数据库连接串")
    is_active = Column(Boolean, default=True)
    max_users = Column(Integer, default=50, comment="最大用户数")
    plan = Column(String(50), default="free", comment="套餐：free/pro/enterprise")
    created_at = Column(DateTime, default=_utcnow)


class Role(Base):
    __tablename__ = "roles"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), unique=True, nullable=False)
    description = Column(String(255), nullable=True)

    users = relationship("User", secondary="user_roles", back_populates="roles")
    permissions = relationship(
        "Permission", secondary="role_permissions", back_populates="roles"
    )


class Permission(Base):
    __tablename__ = "permissions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(100), unique=True, nullable=False)  # 例如 "analysis:create"
    description = Column(String(255), nullable=True)

    roles = relationship("Role", secondary="role_permissions", back_populates="permissions")


class UserRole(Base):
    __tablename__ = "user_roles"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    role_id = Column(Integer, ForeignKey("roles.id"), primary_key=True)


class RolePermission(Base):
    __tablename__ = "role_permissions"

    role_id = Column(Integer, ForeignKey("roles.id"), primary_key=True)
    permission_id = Column(Integer, ForeignKey("permissions.id"), primary_key=True)


# ---------------------------------------------------------------------------
# Phase 7 —— 行级安全：门店访问控制
# ---------------------------------------------------------------------------

class UserStoreAccess(Base):
    """将用户映射到其可访问的门店（行级安全）。"""

    __tablename__ = "user_store_access"

    user_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    store_id = Column(String(50), primary_key=True)
    scope_type = Column(String(20), default="store")  # V4: store/region/all
    region = Column(String(100), nullable=True)


# ---------------------------------------------------------------------------
# Phase 7 —— 异常检测与预警
# ---------------------------------------------------------------------------

class AlertRule(Base):
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(200), nullable=False)
    metric = Column(String(100), nullable=False)  # "refund_rate"、"sales_growth" 等
    threshold = Column(Float, nullable=False)
    direction = Column(String(10), nullable=False)  # "above" 或 "below"
    enabled = Column(Boolean, default=True)
    notify_channels = Column(JSON, default=list)  # ["feishu", "email"] 等
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    created_at = Column(DateTime, default=_utcnow)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    rule_id = Column(Integer, ForeignKey("alert_rules.id"), nullable=False)
    metric = Column(String(100), nullable=False)
    actual_value = Column(Float, nullable=False)
    threshold = Column(Float, nullable=False)
    detail = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    acknowledged = Column(Boolean, default=False)
    acknowledged_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    acknowledged_at = Column(DateTime, nullable=True)


# ---------------------------------------------------------------------------
# Phase 7 —— 周报
# ---------------------------------------------------------------------------

class WeeklyReport(Base):
    __tablename__ = "weekly_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    week_start = Column(DateTime, nullable=False)
    week_end = Column(DateTime, nullable=False)
    report_content = Column(Text, nullable=False)
    summary = Column(Text, nullable=True)
    created_at = Column(DateTime, default=_utcnow)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)


# ---------------------------------------------------------------------------
# 业务数据 —— 门店、订单、会员、员工绩效
# ---------------------------------------------------------------------------

class Store(Base):
    __tablename__ = "store"

    id = Column(Integer, primary_key=True, autoincrement=True)
    store_name = Column(String(200), nullable=False)
    region = Column(String(50), nullable=False)  # 华东/华北/华南/华中/西南/西北/东北
    manager = Column(String(100), nullable=True)
    status = Column(String(20), default="active")  # active（营业）/suspended（暂停）/closed（关闭）
    create_time = Column(DateTime, default=_utcnow)


class Order(Base):
    __tablename__ = "orders"

    order_id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(Integer, ForeignKey("store.id"), nullable=False)
    member_id = Column(Integer, ForeignKey("member.member_id"), nullable=True)
    amount = Column(Float, nullable=False, default=0)
    refund_amount = Column(Float, nullable=False, default=0)
    create_time = Column(DateTime, nullable=False, default=_utcnow)


class Member(Base):
    __tablename__ = "member"

    member_id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100), nullable=False)
    level = Column(String(50), nullable=False, default="普通会员")  # 普通会员/银卡会员/金卡会员/钻石会员
    phone = Column(String(20), nullable=True)
    email = Column(String(200), nullable=True)
    channel = Column(String(50), nullable=True)  # 注册渠道
    age_group = Column(String(20), nullable=True)  # 年龄段
    gender = Column(String(10), nullable=True)
    register_date = Column(DateTime, nullable=False, default=_utcnow)
    last_consume_date = Column(DateTime, nullable=True)
    total_amount = Column(Float, nullable=False, default=0)


class EmployeePerformance(Base):
    __tablename__ = "employee_performance"
    __table_args__ = (
        UniqueConstraint("store_id", "employee_name", "month", name="uq_emp_perf_month"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    store_id = Column(Integer, ForeignKey("store.id"), nullable=False)
    employee_name = Column(String(100), nullable=False)
    month = Column(String(7), nullable=False)  # 格式：YYYY-MM
    sales_amount = Column(Float, nullable=False, default=0)
    orders_count = Column(Integer, nullable=False, default=0)


# =============================================================================
# V4: 审计日志
# =============================================================================


class AuditLog(Base):
    """操作审计日志 —— 满足合规审计要求。

    记录谁在什么时候通过什么方式访问了什么资源。
    审计日志保留策略：默认 180 天，可配置。
    """

    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, comment="操作用户")
    tenant_id = Column(Integer, nullable=True, comment="租户 ID")
    action = Column(String(10), nullable=False, comment="HTTP 方法：GET/POST/PUT/DELETE")
    resource = Column(String(200), nullable=False, comment="访问资源路径")
    detail = Column(Text, nullable=True, comment="额外详情（JSON）")
    ip_address = Column(String(45), nullable=True, comment="客户端 IP")
    session_id = Column(String(100), nullable=True)
    user_agent = Column(String(500), nullable=True)
    status_code = Column(Integer, nullable=True, comment="HTTP 响应状态码")
    elapsed_ms = Column(Integer, nullable=True, comment="请求处理耗时（毫秒）")
    trace_id = Column(String(12), nullable=True, comment="全链路追踪 ID，关联分析请求", index=True)
    created_at = Column(DateTime, default=_utcnow, index=True)


# ---------------------------------------------------------------------------
# V4.6: 微信小程序登录绑定
# ---------------------------------------------------------------------------

class UserWechatBinding(Base):
    """微信小程序用户绑定 —— openid 与系统用户的映射。

    微信一键登录后首次绑定系统账号，后续可直接微信登录。
    """

    __tablename__ = "user_wechat_bindings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    openid = Column(String(128), unique=True, nullable=False, comment="微信 openid")
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, comment="系统用户 ID")
    created_at = Column(DateTime, default=_utcnow)
    updated_at = Column(DateTime, default=_utcnow, onupdate=_utcnow)
