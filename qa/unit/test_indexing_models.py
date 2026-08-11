"""L1 单元测试：M24 索引存储底座模型（字段/约束/常量）。"""

import uuid

from sqlalchemy import inspect


def test_embedding_dim_contract():
    """L1M24-01：BGE-M3 维度常量必须为 1024（D2 已确认）。"""
    from app.models.indexing import EMBEDDING_DIM

    assert EMBEDDING_DIM == 1024


def test_document_chunk_model_fields():
    """L1M24-02：document_chunks 模型字段与唯一约束。"""
    from app.models.indexing import DocumentChunk

    cols = {c.name: c for c in DocumentChunk.__table__.columns}
    for name in (
        "id", "kb_id", "document_id", "chunk_id", "parent_chunk_id",
        "chunk_index", "hierarchy_path", "title", "level", "has_table",
        "semantic_label", "source_pages", "content", "content_for_embedding",
        "parent_text", "tokens", "title_vector", "content_vector",
        "bm25_tokens", "created_at", "updated_at", "deleted_at",
    ):
        assert name in cols, f"缺少字段 {name}"
    assert cols["title_vector"].type.dim == 1024
    assert cols["content_vector"].type.dim == 1024
    uq = [c for c in DocumentChunk.__table__.constraints if getattr(c, "name", "") == "uq_document_chunks_doc_chunk"]
    assert uq, "缺少 (document_id, chunk_id) 唯一约束"


def test_text_chunk_metadata_column_mapping():
    """L1M24-03：metadata 列名保留，ORM 属性名为 metadata_json（避开保留字）。"""
    from app.models.indexing import TextChunk

    col = TextChunk.__table__.columns["metadata"]
    assert col is not None
    # Base.metadata 是 DeclarativeBase 继承属性；metadata_json 才是列属性且映射到列 metadata
    assert "metadata" not in TextChunk.__dict__
    assert TextChunk.metadata_json.prop.columns[0].name == "metadata"


def test_text_chunk_foreign_keys():
    """L1M24-04：text_chunks 关联 document_chunks（级联清理链路）。"""
    from app.models.indexing import TextChunk

    fks = {fk.target_fullname for fk in TextChunk.__table__.foreign_keys}
    assert "document_chunks.id" in fks
    assert "knowledge_bases.id" in fks
    assert "documents.id" in fks


def test_kb_bm25_stats_fields():
    """L1M24-05：kb_bm25_stats 主键/乐观锁字段。"""
    from app.models.indexing import KbBm25Stats

    pk = [c.name for c in KbBm25Stats.__table__.primary_key.columns]
    assert pk == ["kb_id"]
    assert "version" in KbBm25Stats.__table__.columns
    assert "payload" in KbBm25Stats.__table__.columns


def test_document_index_status_default():
    """L1M24-06：documents.index_status 默认 not_indexed。"""
    from app.models.document import Document

    col = Document.__table__.columns["index_status"]
    assert col.default.arg == "not_indexed"
    assert "index_progress" in Document.__table__.columns
    assert "index_total" in Document.__table__.columns
    assert "index_error" in Document.__table__.columns


def test_models_registered_in_metadata():
    """L1M24-07：新模型已注册进 Base.metadata（alembic autogenerate 依赖）。"""
    from app.core.database import Base

    names = set(Base.metadata.tables)
    assert "document_chunks" in names
    assert "text_chunks" in names
    assert "kb_bm25_stats" in names
