"""phase2 新表 RLS 策略：qa_sessions / qa_messages / kb_backups。

Revision ID: 003_phase2_rls
Revises: 002_phase2_tables
Create Date: 2026-08-02

为阶段 2 新增的 KB 范围表启用行级安全（RLS）并添加 kb_isolation 策略，
与 documents/tasks 保持一致：``kb_id::text = current_setting('app.current_kb', true)``。

- qa_sessions：直接含 kb_id 列，启用 RLS + kb_isolation
- kb_backups：直接含 kb_id 列，启用 RLS + kb_isolation
- qa_messages：通过 session_id 关联 qa_sessions，无 kb_id 列；
  采用会话级隔离策略——仅允许访问当前 KB 内会话的消息。
  实现：在 qa_messages 上基于 session_id 子查询过滤（session 属于当前 KB）。
- notifications：按 user_id 隔离，不走 KB RLS（不在此迁移处理）。
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "003_phase2_rls"
down_revision = "002_phase2_tables"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ---------- qa_sessions：启用 RLS + kb_isolation ----------
    op.execute("ALTER TABLE qa_sessions ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY kb_isolation ON qa_sessions
        FOR ALL
        USING (kb_id::text = current_setting('app.current_kb', true))
        WITH CHECK (kb_id::text = current_setting('app.current_kb', true))
        """
    )

    # ---------- kb_backups：启用 RLS + kb_isolation ----------
    op.execute("ALTER TABLE kb_backups ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY kb_isolation ON kb_backups
        FOR ALL
        USING (kb_id::text = current_setting('app.current_kb', true))
        WITH CHECK (kb_id::text = current_setting('app.current_kb', true))
        """
    )

    # ---------- qa_messages：启用 RLS + 会话级隔离 ----------
    # qa_messages 无 kb_id 列，通过 session_id 关联 qa_sessions 实现隔离。
    # 仅允许访问「属于当前 KB 的会话」下的消息。
    op.execute("ALTER TABLE qa_messages ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY kb_isolation ON qa_messages
        FOR ALL
        USING (
            session_id IN (
                SELECT id FROM qa_sessions
                WHERE kb_id::text = current_setting('app.current_kb', true)
            )
        )
        WITH CHECK (
            session_id IN (
                SELECT id FROM qa_sessions
                WHERE kb_id::text = current_setting('app.current_kb', true)
            )
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS kb_isolation ON qa_messages")
    op.execute("ALTER TABLE qa_messages DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS kb_isolation ON kb_backups")
    op.execute("ALTER TABLE kb_backups DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS kb_isolation ON qa_sessions")
    op.execute("ALTER TABLE qa_sessions DISABLE ROW LEVEL SECURITY")
