"""011_hard_delete_glossary: 术语集/词条删除改为硬删，清理存量软删脏数据。

背景：术语模块删除语义对齐原项目（硬删），避免 deleted_at 脏数据留存。
- 清理 terms / term_bases 中已软删的行（先 terms 后 term_bases）；
- 后续删除走数据库 DELETE，FK ON DELETE CASCADE 级联删除词条；
- 部分唯一索引（deleted_at IS NULL）保留：新数据 deleted_at 恒 NULL，
  索引语义等价于普通唯一约束，无需重建。
"""

from alembic import op

revision = "011_hard_delete_glossary"
down_revision = "010_term_glossary"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DELETE FROM terms WHERE deleted_at IS NOT NULL")
    op.execute("DELETE FROM term_bases WHERE deleted_at IS NOT NULL")


def downgrade() -> None:
    # 硬删数据不可恢复，降级仅回退版本号
    pass
