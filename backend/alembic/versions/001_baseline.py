"""baseline 反映阶段 1 已落库的 schema。

Revision ID: 001_baseline
Revises:
Create Date: 2026-08-02

本基线迁移将 alembic 版本表标记为已就绪。阶段 1 的全部表
（users/knowledge_bases/kb_members/documents/tasks/schema_configs/terms/
audit_logs/password_reset_tokens/password_history/kb_domain_config
等）已通过手动 ALTER TABLE / CREATE TABLE 落库，此处不再重复创建，
仅作为后续迁移的起点。

⚠️ 不可逆：downgrade 将拒绝执行（阶段 1 表为系统基石）。
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "001_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """基线升级：标记版本，不执行任何 DDL（表已存在）。"""
    # 阶段 1 表已通过手动 DDL 落库，此处仅建立 alembic 版本锚点。
    pass


def downgrade() -> None:
    """基线不可降级：阶段 1 表为系统基石，不允许回滚。"""
    raise RuntimeError("baseline 不可 downgrade（阶段 1 表为系统基石）")
