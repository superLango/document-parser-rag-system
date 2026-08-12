"""L1 单元测试：M33-S1 术语集模型。"""

import uuid

from app.models.glossary import (
    SOURCE_TYPES,
    TERM_STATUSES,
    TERM_STATUS_ACTIVE,
    TERM_STATUS_PENDING,
    Term,
    TermBase,
)


def test_term_base_fields():
    """L1M33-S1-01：TermBase 字段与默认值。"""
    cols = TermBase.__table__.columns
    for name in ("id", "kb_id", "name", "description", "source_type",
                 "source_config", "columns", "column_aliases", "sync_enabled",
                 "last_synced_at", "status", "created_by", "created_at",
                 "updated_at", "deleted_at"):
        assert name in cols
    assert cols["source_type"].default.arg == "manual"
    assert cols["sync_enabled"].default.arg is False


def test_term_fields():
    """L1M33-S1-02：Term 字段与默认值。"""
    cols = Term.__table__.columns
    for name in ("id", "kb_id", "term_base_id", "term_name", "standard_name",
                 "english_term", "definition", "category", "standard_number",
                 "synonyms", "aliases", "extras", "status", "reviewed_by",
                 "reviewed_at", "created_by", "created_at", "updated_at", "deleted_at"):
        assert name in cols
    assert cols["status"].default.arg == TERM_STATUS_ACTIVE


def test_source_and_status_constants():
    """L1M33-S1-03：来源类型与状态常量。"""
    assert SOURCE_TYPES == {"manual", "api", "db"}
    assert TERM_STATUSES == {"active", "pending", "rejected"}
    assert TERM_STATUS_PENDING == "pending"


def test_partial_unique_indexes():
    """L1M33-S1-04：软删场景的部分唯一索引存在。"""
    names = {i.name for i in TermBase.__table__.indexes}
    assert "uq_term_bases_kb_name" in names
    term_names = {i.name for i in Term.__table__.indexes}
    assert "uq_terms_kb_base_name" in term_names


def test_models_registered():
    """L1M33-S1-05：模型注册进 Base.metadata。"""
    from app.core.database import Base

    assert "term_bases" in Base.metadata.tables
    assert "terms" in Base.metadata.tables
