"""L1 单元：M34 全局配置（默认结构 / 合并 / Schema 校验）。"""

import pytest
from app.schemas.extraction import GlobalConfigContent, GlobalConfigSave
from app.services.extraction_config_service import (
    DEFAULT_GLOBAL_CONFIG,
    _deep_merge,
    _default_global_config,
)
from pydantic import ValidationError


async def test_default_config_structure():
    """L1G-01：默认全局配置包含 retrieval/llm/kb_tool 三大区块且叶子齐全。"""
    cfg = _default_global_config()
    assert set(cfg) == {"retrieval", "llm", "kb_tool"}
    assert cfg["retrieval"]["top_k"] == 15
    assert cfg["retrieval"]["data_route_top_k"] == 10
    assert cfg["retrieval"]["meta_route_top_k"] == 5
    assert cfg["retrieval"]["hybrid"]["rrf_k"] == 60.0
    # context 仅保留接线项（chars_per_token/sort_mode/retry_rerank_on_empty），无摆设键
    assert set(cfg["retrieval"]["context"]) == {"chars_per_token", "sort_mode", "retry_rerank_on_empty"}
    assert cfg["llm"]["engine"] == "BaseExtract"
    assert set(cfg["llm"]["engines"]) == {"BaseExtract", "LangExtractPkg"}
    assert cfg["kb_tool"]["script_timeout"] == 60


async def test_deep_merge_partial_override():
    """L1G-02：部分覆盖合并，未覆盖项保留默认值。"""
    base = _default_global_config()
    merged = _deep_merge(base, {
        "retrieval": {"top_k": 30},
        "kb_tool": {"script_timeout": 20},
    })
    assert merged["retrieval"]["top_k"] == 30
    assert merged["retrieval"]["hybrid"]["rrf_k"] == 60.0
    assert merged["kb_tool"]["script_timeout"] == 20
    assert merged["kb_tool"]["embed_batch_size"] == 16


async def test_schema_accepts_full_content():
    """L1G-03：默认内容可通过 GlobalConfigSave 校验。"""
    payload = GlobalConfigSave(content=GlobalConfigContent.model_validate(DEFAULT_GLOBAL_CONFIG))
    assert payload.content.retrieval.top_k == 15
    assert payload.content.retrieval.data_route_top_k == 10
    assert payload.content.retrieval.meta_route_top_k == 5
    assert payload.content.retrieval.context.chars_per_token == 1.5
    assert payload.content.llm.engines["LangExtractPkg"].format_type == "JSON"


async def test_schema_rejects_invalid_values():
    """L1G-04：非法数值（top_k=0、阈值>1）被拒绝。"""
    with pytest.raises(ValidationError):
        GlobalConfigSave.model_validate({
            "enabled": True,
            "content": {"retrieval": {"top_k": 0}},
        })
    with pytest.raises(ValidationError):
        GlobalConfigSave.model_validate({
            "enabled": True,
            "content": {"retrieval": {"default_confidence_threshold": 1.5}},
        })
    with pytest.raises(ValidationError):
        GlobalConfigSave.model_validate({
            "enabled": True,
            "content": {"llm": {"engine": "Unknown"}},
        })
