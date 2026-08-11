"""009_vector_indexing: pgvector 扩展 + 索引存储三表 + documents 索引状态列 + RLS。

S1 存储底座：
- document_chunks：双向量块主表（title_vector/content_vector + HNSW）
- text_chunks：全文溯源表（D5）
- kb_bm25_stats：KB 级 BM25 增量统计（D4，version 乐观锁）
- documents 增加 index_status/index_progress/index_total/index_error
- 所有 KB 域表启用 RLS，策略复用 005/006 已建函数
  （hansondoc_is_superuser / hansondoc_current_kb / hansondoc_current_user /
   hansondoc_kb_effective_role）
"""

import sqlalchemy as sa
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from alembic import op

revision = "009_vector_indexing"
down_revision = "008_documents_progress_pages"
branch_labels = None
depends_on = None

# 与 006 修复后的策略一致：空 app.user_id 经 hansondoc_current_user() 兜底
ROLE = "hansondoc_kb_effective_role(kb_id, hansondoc_current_user())"

TABLES = ("document_chunks", "text_chunks", "kb_bm25_stats")


def _drop_policies(table: str, prefix: str) -> None:
    for name in (
        f"{prefix}_select",
        f"{prefix}_insert",
        f"{prefix}_update",
        f"{prefix}_delete",
    ):
        op.execute(f"DROP POLICY IF EXISTS {name} ON {table};")


def _create_policies(table: str, prefix: str) -> None:
    # 读：当前 KB 有效成员（含 viewer）
    op.execute(
        f"""
        CREATE POLICY {prefix}_select ON {table} FOR SELECT USING (
            hansondoc_is_superuser()
            OR (hansondoc_current_kb() = kb_id AND {ROLE} IS NOT NULL)
        );
        """
    )
    # 写：当前 KB owner/admin/editor（worker 以超管身份执行不受限）
    for command, clause in (
        ("INSERT", "WITH CHECK"),
        ("UPDATE", "USING"),
        ("DELETE", "USING"),
    ):
        op.execute(
            f"""
            CREATE POLICY {prefix}_{command.lower()} ON {table} FOR {command} {clause} (
                hansondoc_is_superuser()
                OR (hansondoc_current_kb() = kb_id AND {ROLE} IN ('owner', 'admin', 'editor'))
            );
            """
        )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector;")

    # ---------- document_chunks ----------
    op.create_table(
        "document_chunks",
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", PgUUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", PgUUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_id", sa.String(128), nullable=False),
        sa.Column("parent_chunk_id", sa.String(128), nullable=True),
        sa.Column("chunk_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hierarchy_path", sa.Text(), nullable=False, server_default=""),
        sa.Column("title", sa.Text(), nullable=False, server_default=""),
        sa.Column("level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("has_table", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("semantic_label", sa.String(64), nullable=False, server_default=""),
        sa.Column("source_pages", JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("content_for_embedding", sa.Text(), nullable=True),
        sa.Column("parent_text", sa.Text(), nullable=True),
        sa.Column("tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("title_vector", Vector(1024), nullable=True),
        sa.Column("content_vector", Vector(1024), nullable=True),
        sa.Column("bm25_tokens", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("document_id", "chunk_id", name="uq_document_chunks_doc_chunk"),
    )
    op.create_index("idx_chunks_kb_doc", "document_chunks", ["kb_id", "document_id"], postgresql_where=sa.text("deleted_at IS NULL"))
    op.execute("CREATE INDEX idx_chunks_title_vec ON document_chunks USING hnsw (title_vector vector_cosine_ops);")
    op.execute("CREATE INDEX idx_chunks_content_vec ON document_chunks USING hnsw (content_vector vector_cosine_ops);")
    op.execute("CREATE INDEX idx_chunks_bm25_tokens ON document_chunks USING gin (bm25_tokens);")

    # ---------- text_chunks ----------
    op.create_table(
        "text_chunks",
        sa.Column("id", PgUUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("kb_id", PgUUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_id", PgUUID(as_uuid=True), sa.ForeignKey("documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("document_chunk_id", PgUUID(as_uuid=True), sa.ForeignKey("document_chunks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("chunk_id", sa.String(128), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("heading", sa.Text(), nullable=False, server_default=""),
        sa.Column("tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("metadata", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("document_id", "chunk_id", name="uq_text_chunks_doc_chunk"),
    )
    op.create_index("idx_text_chunks_kb_doc", "text_chunks", ["kb_id", "document_id"])
    op.create_index("idx_text_chunks_chunk_ref", "text_chunks", ["document_chunk_id"])

    # ---------- kb_bm25_stats ----------
    op.create_table(
        "kb_bm25_stats",
        sa.Column("kb_id", PgUUID(as_uuid=True), sa.ForeignKey("knowledge_bases.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )

    # ---------- documents 索引状态列 ----------
    op.add_column("documents", sa.Column("index_status", sa.String(32), nullable=False, server_default="not_indexed"))
    op.add_column("documents", sa.Column("index_progress", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("index_total", sa.Integer(), nullable=True))
    op.add_column("documents", sa.Column("index_error", JSONB(), nullable=True))

    # ---------- RLS ----------
    for table, prefix in (("document_chunks", "chunk"), ("text_chunks", "tchunk"), ("kb_bm25_stats", "bm25")):
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY;")
        _create_policies(table, prefix)


def downgrade() -> None:
    for table, prefix in (("document_chunks", "chunk"), ("text_chunks", "tchunk"), ("kb_bm25_stats", "bm25")):
        _drop_policies(table, prefix)
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY;")

    op.drop_table("text_chunks")
    op.drop_table("document_chunks")
    op.drop_table("kb_bm25_stats")

    op.drop_column("documents", "index_error")
    op.drop_column("documents", "index_total")
    op.drop_column("documents", "index_progress")
    op.drop_column("documents", "index_status")

    # 扩展不随迁移删除（避免影响其他功能/回滚复杂度），由运维按需处理
