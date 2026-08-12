"""L1 单元测试：M34-S1 抽取配置模型。"""


from app.models.extraction import (
    EXTRACTION_STRATEGIES,
    FIELD_TYPES,
    NAME_SOURCES,
    PROMPT_SCOPES,
    RETURN_TYPES,
    SCRIPT_FOLDERS,
    KbScript,
    PromptContent,
    PromptTemplate,
    RuleGroup,
    RuleGroupItem,
    SchemaCategory,
    SchemaField,
    SchemaTemplate,
)


def test_schema_template_fields():
    """L1M34-S1-01：SchemaTemplate 字段与默认值。"""
    cols = SchemaTemplate.__table__.columns
    for name in ("id", "kb_id", "name", "description", "is_active", "sort_order",
                 "created_by", "created_at", "updated_at"):
        assert name in cols
    assert cols["is_active"].default.arg is True
    assert cols["sort_order"].default.arg == 0


def test_schema_category_fields():
    """L1M34-S1-02：SchemaCategory 字段与术语集联动默认值。"""
    cols = SchemaCategory.__table__.columns
    for name in ("id", "kb_id", "template_id", "name", "description", "return_type",
                 "extraction_strategy", "fixed_query", "confidence_threshold", "top_k",
                 "rerank_top_k", "max_tokens", "name_source", "name_term_base_id",
                 "name_term_field", "query_sources", "is_active", "sort_order"):
        assert name in cols
    assert cols["return_type"].default.arg == "array"
    assert cols["extraction_strategy"].default.arg == "auto"
    assert cols["name_source"].default.arg == "manual"


def test_schema_field_prompt_rule_script_fields():
    """L1M34-S1-03：字段/Prompt/规则/脚本模型字段齐全。"""
    assert "type" in SchemaField.__table__.columns
    assert "example" in SchemaField.__table__.columns
    assert "scope" in PromptTemplate.__table__.columns
    assert "category_ids" in PromptTemplate.__table__.columns
    assert "system_prompt" in PromptContent.__table__.columns
    assert "user_prompt" in PromptContent.__table__.columns
    assert "script_id" in RuleGroupItem.__table__.columns
    assert "stage" in RuleGroupItem.__table__.columns
    assert "category_name" in RuleGroupItem.__table__.columns
    assert "params" in RuleGroupItem.__table__.columns
    assert "folder" in KbScript.__table__.columns
    assert "code" in KbScript.__table__.columns


def test_constants():
    """L1M34-S1-04：枚举常量。"""
    assert RETURN_TYPES == {"array", "object"}
    assert EXTRACTION_STRATEGIES == {"auto", "always", "never"}
    assert NAME_SOURCES == {"manual", "term_base"}
    assert FIELD_TYPES == {"string", "number", "boolean", "array"}
    assert PROMPT_SCOPES == {"simple", "schema"}
    assert SCRIPT_FOLDERS == {"post", "validation"}


def test_unique_indexes_exist():
    """L1M34-S1-05：关键唯一索引存在。"""
    names = {i.name for i in SchemaTemplate.__table__.indexes}
    assert "uq_schema_templates_kb_name" in names
    fnames = {i.name for i in SchemaField.__table__.indexes}
    assert "uq_schema_fields_category_name" in fnames
    pnames = {i.name for i in PromptTemplate.__table__.indexes}
    assert "uq_prompt_templates_kb_name" in pnames
    rnames = {i.name for i in RuleGroup.__table__.indexes}
    assert "uq_rule_groups_kb_name" in rnames
    snames = {i.name for i in KbScript.__table__.indexes}
    assert "uq_kb_scripts_folder_name" in snames
    cnames = {i.name for i in PromptContent.__table__.indexes}
    assert "uq_prompt_content_prompt_category" in cnames
    assert "uq_prompt_content_simple" in cnames


def test_models_registered():
    """L1M34-S1-06：模型注册进 Base.metadata。"""
    from app.core.database import Base

    for table in ("schema_templates", "schema_categories", "schema_fields",
                  "prompt_templates", "prompt_content", "rule_groups",
                  "rule_group_items", "kb_scripts"):
        assert table in Base.metadata.tables
