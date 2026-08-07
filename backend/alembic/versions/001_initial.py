"""001_initial: 初始基线（当前系统作为最初版本）

一次性基线迁移，由当前 ORM 模型 + 数据库层隔离策略生成：

- 通过 ``Base.metadata.create_all`` 创建当前系统全部业务表（不含已移除的
  数据集 / 基础三表 / 字典等历史概念表）。
- 精确复刻现网库的行级安全（RLS）隔离策略：
  - 20 张携带 ``kb_id`` 的表启用 ``kb_isolation`` 策略
    （``USING (kb_id::text = current_setting('app.current_kb', true))``）；
  - ``qa_messages`` 无 ``kb_id``，通过 ``session_id → qa_sessions.kb_id``
    子查询间接隔离（与现网库一致）；
  - ``kb_members`` / ``kb_category_enums`` / ``term_bases`` 等全局表不隔离。
- 重建 ``documents.search_vector`` 的 GIN 全文索引（数据库层，非 ORM 定义）。

revision: 001_initial
down_revision: None
"""

from alembic import op

# 加载全部模型，确保 create_all 覆盖所有业务表
import app.models  # noqa: F401
from app.core.database import Base

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


# 需启用 RLS 的 kb 级表（与现网库精确一致；全局表不入列）
RLS_TABLES = [
    "documents",
    "kb_backups",
    "kb_categories",
    "kb_domain_config_versions",
    "kb_extraction_config",
    "kb_field_templates",
    "kb_prompt_categories",
    "kb_prompt_templates",
    "kb_regex_rules",
    "kb_rule_group_items",
    "kb_rule_groups",
    "kb_rules",
    "kb_scripts",
    "kb_term_bindings",
    "qa_sessions",
    "schema_configs",
    "schema_templates",
    "tasks",
    "term_mappings",
    "terms",
]


def _enable_rls(table: str) -> None:
    """为指定表启用 RLS + kb_isolation 策略（与历史迁移同款策略）。"""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY kb_isolation ON {table}
        FOR ALL
        USING (kb_id::text = current_setting('app.current_kb', true))
        WITH CHECK (kb_id::text = current_setting('app.current_kb', true))
        """
    )


def _disable_rls(table: str) -> None:
    op.execute(f"DROP POLICY IF EXISTS kb_isolation ON {table}")
    op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")


# qa_messages 无 kb_id，通过 session_id → qa_sessions.kb_id 子查询间接隔离
QA_MESSAGES_RLS = (
    "CREATE POLICY kb_isolation ON qa_messages\n"
    "FOR ALL\n"
    "USING (session_id IN (SELECT qa_sessions.id FROM qa_sessions "
    "WHERE qa_sessions.kb_id::text = current_setting('app.current_kb', true)))\n"
    "WITH CHECK (session_id IN (SELECT qa_sessions.id FROM qa_sessions "
    "WHERE qa_sessions.kb_id::text = current_setting('app.current_kb', true)))"
)


def upgrade() -> None:
    # 1. 创建全部业务表（含 search_vector 生成列及 ORM 内联索引）
    Base.metadata.create_all(bind=op.get_bind())

    # 2. 重建全文搜索 GIN 索引（数据库层，不在 ORM 定义内）
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_documents_search_vector "
        "ON documents USING GIN(search_vector)"
    )

    # 3. 为 kb 级表启用 RLS 隔离策略
    for table in RLS_TABLES:
        _enable_rls(table)
    # qa_messages：session 间接隔离
    op.execute("ALTER TABLE qa_messages ENABLE ROW LEVEL SECURITY")
    op.execute(QA_MESSAGES_RLS)


def downgrade() -> None:
    # 1. 关闭 RLS 并删除策略
    for table in RLS_TABLES:
        _disable_rls(table)
    _disable_rls("qa_messages")

    # 2. 删除全文索引
    op.execute("DROP INDEX IF EXISTS idx_documents_search_vector")

    # 3. 删除全部业务表
    Base.metadata.drop_all(bind=op.get_bind())
