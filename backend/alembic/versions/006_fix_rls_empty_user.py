"""006_fix_rls_empty_user: RLS 空 app.user_id 不再报错（REG-15）。

修复：hansondoc_kb_effective_role 调用处直接对 current_setting('app.user_id')
做 ::uuid 强转，空字符串触发 invalid input syntax；新增 hansondoc_current_user()
返回 NULL 并替换全部策略引用。
"""

from alembic import op

revision = "006_fix_rls_empty_user"
down_revision = "005_documents_phase1"
branch_labels = None
depends_on = None

ROLE = "hansondoc_kb_effective_role(kb_id, hansondoc_current_user())"


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION hansondoc_current_user() RETURNS uuid AS $$
            SELECT NULLIF(current_setting('app.user_id', true), '')::uuid
        $$ LANGUAGE sql STABLE;
        """
    )

    for name in ("doc_select", "doc_insert", "doc_update", "doc_delete"):
        op.execute(f"DROP POLICY IF EXISTS {name} ON documents;")
    for name in ("task_select", "task_insert", "task_update", "task_delete"):
        op.execute(f"DROP POLICY IF EXISTS {name} ON document_tasks;")

    op.execute(
        f"""
        CREATE POLICY doc_select ON documents FOR SELECT USING (
            hansondoc_is_superuser()
            OR (hansondoc_current_kb() = kb_id AND {ROLE} IS NOT NULL)
        );
        """
    )
    op.execute(
        f"""
        CREATE POLICY doc_insert ON documents FOR INSERT WITH CHECK (
            hansondoc_is_superuser()
            OR (hansondoc_current_kb() = kb_id AND {ROLE} IN ('owner', 'admin', 'editor'))
        );
        """
    )
    op.execute(
        f"""
        CREATE POLICY doc_update ON documents FOR UPDATE USING (
            hansondoc_is_superuser()
            OR (hansondoc_current_kb() = kb_id AND {ROLE} IN ('owner', 'admin', 'editor'))
        ) WITH CHECK (
            hansondoc_is_superuser()
            OR (hansondoc_current_kb() = kb_id AND {ROLE} IN ('owner', 'admin', 'editor'))
        );
        """
    )
    op.execute(
        f"""
        CREATE POLICY doc_delete ON documents FOR DELETE USING (
            hansondoc_is_superuser()
            OR (hansondoc_current_kb() = kb_id AND {ROLE} IN ('owner', 'admin', 'editor'))
        );
        """
    )
    op.execute(
        f"""
        CREATE POLICY task_select ON document_tasks FOR SELECT USING (
            hansondoc_is_superuser()
            OR (hansondoc_current_kb() = kb_id AND {ROLE} IS NOT NULL)
        );
        """
    )
    op.execute(
        f"""
        CREATE POLICY task_insert ON document_tasks FOR INSERT WITH CHECK (
            hansondoc_is_superuser()
            OR (hansondoc_current_kb() = kb_id AND {ROLE} IS NOT NULL)
        );
        """
    )
    op.execute(
        f"""
        CREATE POLICY task_update ON document_tasks FOR UPDATE USING (
            hansondoc_is_superuser()
            OR (hansondoc_current_kb() = kb_id AND {ROLE} IS NOT NULL)
        );
        """
    )
    op.execute(
        f"""
        CREATE POLICY task_delete ON document_tasks FOR DELETE USING (
            hansondoc_is_superuser()
            OR (hansondoc_current_kb() = kb_id AND {ROLE} IS NOT NULL)
        );
        """
    )


def downgrade() -> None:
    for name in ("doc_select", "doc_insert", "doc_update", "doc_delete"):
        op.execute(f"DROP POLICY IF EXISTS {name} ON documents;")
    for name in ("task_select", "task_insert", "task_update", "task_delete"):
        op.execute(f"DROP POLICY IF EXISTS {name} ON document_tasks;")
    op.execute("DROP FUNCTION IF EXISTS hansondoc_current_user();")
