"""schema_configs 表启用 RLS 策略。

Revision ID: 008_schema_config_rls
Revises: 007_extraction_config
Create Date: 2026-08-05

schema_configs 表已有 kb_id 列但缺少 RLS 策略，此迁移补全：
- 为 schema_configs 启用 ROW LEVEL SECURITY
- 添加 kb_isolation 策略按 kb_id 隔离
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "008_schema_config_rls"
down_revision = "007_extraction_config"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 检查 schema_configs 是否已启用 RLS，若未启用则补全
    op.execute("ALTER TABLE IF EXISTS schema_configs ENABLE ROW LEVEL SECURITY")
    # 先删除可能存在的旧策略再创建（幂等）
    op.execute("DROP POLICY IF EXISTS kb_isolation ON schema_configs")
    op.execute(
        """
        CREATE POLICY kb_isolation ON schema_configs
        FOR ALL
        USING (kb_id::text = current_setting('app.current_kb', true))
        WITH CHECK (kb_id::text = current_setting('app.current_kb', true))
        """
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS kb_isolation ON schema_configs")
    op.execute("ALTER TABLE schema_configs DISABLE ROW LEVEL SECURITY")
