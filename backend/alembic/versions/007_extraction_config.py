"""抽取配置中心：6 张配置表。

Revision ID: 007_extraction_config
Revises: 006_schema_templates
Create Date: 2026-08-04

新增表（均带 kb_id，RLS 按 kb_id 隔离）：
- kb_extraction_config：全局抽取配置（每 KB 一条）
- kb_prompt_templates：Prompt 模板
- kb_extraction_rules：抽取规则（前/后处理开关）
- kb_validation_rules：验证规则
- kb_term_bindings：Schema 字段 ↔ 术语集 / 数据集 绑定
- kb_domain_config_versions：领域配置版本快照

命名规范：全局配置区块使用 retrieval / llm / post_process，不使用 phase 前缀；
类别级 top_k / confidence_threshold 通过 Schema 模板类别节点设置，不设全局专用字段。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision = "007_extraction_config"
down_revision = "006_schema_templates"
branch_labels = None
depends_on = None


def _enable_rls(table: str) -> None:
    """为指定表启用 RLS + kb_isolation 策略。"""
    op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY kb_isolation ON {table}
        FOR ALL
        USING (kb_id::text = current_setting('app.current_kb', true))
        WITH CHECK (kb_id::text = current_setting('app.current_kb', true))
        """
    )


def upgrade() -> None:
    # ---------- kb_extraction_config 表 ----------
    op.create_table(
        "kb_extraction_config",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, unique=True, index=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("content", sa.JSON, nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("version", sa.Integer, nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("kb_id", name="uq_kb_extraction_config_kb"),
        comment="全局抽取配置表（RLS 按 kb_id）",
    )

    # ---------- kb_prompt_templates 表 ----------
    op.create_table(
        "kb_prompt_templates",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("template_type", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("variables", sa.JSON, nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("kb_id", "name", name="uq_kb_prompt_templates_kb_name"),
        comment="Prompt 模板表（RLS 按 kb_id）",
    )

    # ---------- kb_extraction_rules 表 ----------
    op.create_table(
        "kb_extraction_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("stage", sa.String(10), nullable=False, server_default="post"),
        sa.Column("rule_key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("params", sa.JSON, nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("kb_id", "rule_key", name="uq_kb_extraction_rules_kb_key"),
        comment="抽取规则表（RLS 按 kb_id）",
    )

    # ---------- kb_validation_rules 表 ----------
    op.create_table(
        "kb_validation_rules",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("rule_key", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("config", sa.JSON, nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("kb_id", "rule_key", name="uq_kb_validation_rules_kb_key"),
        comment="验证规则表（RLS 按 kb_id）",
    )

    # ---------- kb_term_bindings 表 ----------
    op.create_table(
        "kb_term_bindings",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("schema_id", UUID(as_uuid=True), sa.ForeignKey("schema_configs.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("field_name", sa.String(100), nullable=False),
        sa.Column("binding_type", sa.String(20), nullable=False, server_default="term"),
        sa.Column("term_base_id", UUID(as_uuid=True), sa.ForeignKey("term_bases.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("dataset_id", UUID(as_uuid=True), sa.ForeignKey("kb_datasets.id", ondelete="CASCADE"), nullable=True, index=True),
        sa.Column("config", sa.JSON, nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("kb_id", "schema_id", "field_name", name="uq_kb_term_bindings_schema_field"),
        comment="术语绑定表（RLS 按 kb_id）",
    )

    # ---------- kb_domain_config_versions 表 ----------
    op.create_table(
        "kb_domain_config_versions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", UUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("version", sa.Integer, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.String(500), nullable=True),
        sa.Column("snapshot", sa.JSON, nullable=False, server_default=sa.text("'{}'::json")),
        sa.Column("created_by", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("kb_id", "version", name="uq_kb_domain_version_kb_ver"),
        comment="领域配置版本快照表（RLS 按 kb_id）",
    )

    # ---------- 启用 RLS ----------
    for table in (
        "kb_extraction_config",
        "kb_prompt_templates",
        "kb_extraction_rules",
        "kb_validation_rules",
        "kb_term_bindings",
        "kb_domain_config_versions",
    ):
        _enable_rls(table)


def downgrade() -> None:
    for table in (
        "kb_domain_config_versions",
        "kb_term_bindings",
        "kb_validation_rules",
        "kb_extraction_rules",
        "kb_prompt_templates",
        "kb_extraction_config",
    ):
        op.execute(f"DROP POLICY IF EXISTS kb_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
        op.drop_table(table)