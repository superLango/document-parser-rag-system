"""015_global_extraction_config: 知识库级结构化抽取全局配置表 + RLS。

每 KB 一行（kb_id 唯一）：enabled + content(JSONB) + version。
RLS 复用 012 模式：SELECT=成员，写=owner/admin/editor。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision = "015_global_extraction_config"
down_revision = "014_rule_item_script_binding"
branch_labels = None
depends_on = None

ROLE = "hansondoc_kb_effective_role(kb_id, hansondoc_current_user())"
TABLE = "kb_extraction_config"
PREFIX = "gcfg"


def _drop_policies() -> None:
    for name in (
        f"{PREFIX}_select",
        f"{PREFIX}_insert",
        f"{PREFIX}_update",
        f"{PREFIX}_delete",
    ):
        op.execute(f"DROP POLICY IF EXISTS {name} ON {TABLE};")


def _create_policies() -> None:
    op.execute(
        f"""
        CREATE POLICY {PREFIX}_select ON {TABLE} FOR SELECT USING (
            hansondoc_is_superuser()
            OR (hansondoc_current_kb() = kb_id AND {ROLE} IS NOT NULL)
        );
        """
    )
    for command, clause in (
        ("INSERT", "WITH CHECK"),
        ("UPDATE", "USING"),
        ("DELETE", "USING"),
    ):
        op.execute(
            f"""
            CREATE POLICY {PREFIX}_{command.lower()} ON {TABLE} FOR {command} {clause} (
                hansondoc_is_superuser()
                OR (hansondoc_current_kb() = kb_id AND {ROLE} IN ('owner', 'admin', 'editor'))
            );
            """
        )


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", PgUUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("content", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_kb_extraction_config_kb", TABLE, ["kb_id"])
    op.create_unique_constraint("uq_kb_extraction_config_kb", TABLE, ["kb_id"])
    op.execute(f"ALTER TABLE {TABLE} ENABLE ROW LEVEL SECURITY;")
    op.execute(f"ALTER TABLE {TABLE} FORCE ROW LEVEL SECURITY;")
    _create_policies()


def downgrade() -> None:
    _drop_policies()
    op.execute(f"ALTER TABLE {TABLE} DISABLE ROW LEVEL SECURITY;")
    op.drop_table(TABLE)
