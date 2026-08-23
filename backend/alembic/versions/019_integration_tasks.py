"""019_integration_tasks: 系统对接任务（上传→OCR→结构化抽取 一站式）。

- integration_tasks：统一 task_id 贯穿 OCR 解析与结构化抽取；
  记录 kb_id / document_id / prompt_id / schema_template_id 与双阶段状态；
- RLS 沿用既有策略，无认证对接端点内部使用 superuser 会话。
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID as PgUUID

revision = "019_integration_tasks"
down_revision = "018_term_sync_cron"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "integration_tasks",
        sa.Column("task_id", PgUUID(as_uuid=True), primary_key=True),
        sa.Column("kb_id", PgUUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("document_id", PgUUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="SET NULL"), nullable=True, index=True),
        sa.Column("prompt_id", PgUUID(as_uuid=True), nullable=True),
        sa.Column("schema_template_id", PgUUID(as_uuid=True), nullable=True),
        sa.Column("filename", sa.String(255), nullable=False, server_default=""),
        sa.Column("ocr_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("ocr_progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("extract_status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("extract_progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("result_version", sa.Integer(), nullable=True),
        sa.Column("created_by", PgUUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now(), nullable=True),
    )
    op.create_index("idx_integration_tasks_doc", "integration_tasks", ["document_id"])


def downgrade() -> None:
    op.drop_index("idx_integration_tasks_doc", table_name="integration_tasks")
    op.drop_table("integration_tasks")
