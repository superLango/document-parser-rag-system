"""L1 单元：Prompt 预览统一渲染（与真实抽取同一套 prompt_renderer）。"""

import uuid

import pytest

from app.services import extraction_config_service as svc
from app.services.extraction import term_base_loader


def _category() -> dict:
    return {
        "id": str(uuid.uuid4()),
        "template_id": str(uuid.uuid4()),
        "name": "项目大类",
        "description": "",
        "return_type": "array",
        "extraction_strategy": "auto",
        "fixed_query": "",
        "top_k": None,
        "max_tokens": None,
        "confidence_threshold": None,
        "name_source": "term_base",
        "name_term_base_id": str(uuid.uuid4()),
        "name_term_field": "NAME",
        "query_sources": [{
            "label": "检测项目", "term_base_id": str(uuid.uuid4()),
            "group_field": "NAME", "value_field": "NAME",
        }],
        "special_requirements": {"热膨胀": "注意区分线膨胀与体膨胀"},
        "is_active": True,
        "sort_order": 0,
        "fields": [{
            "id": str(uuid.uuid4()), "name": "材料牌号", "type": "string",
            "description": "材料牌号", "example": "GH4169", "required": True,
        }],
    }


async def test_preview_prompt_special_requirement(monkeypatch):
    """L1PV-01：预览渲染 ${special_requirement} 按展开类别名取值，术语集按 group_field 过滤。"""
    tpl_id = str(uuid.uuid4())
    cat = _category()

    async def fake_get_template(db, kb_id, template_id):
        return {"id": tpl_id, "name": "T", "categories": [cat]}

    async def fake_load(db, kb_id, term_base_id):
        return [
            {"term_name": "x", "extras": {"NAME": "热膨胀"}},
            {"term_name": "y", "extras": {"NAME": "相变点"}},
        ]

    monkeypatch.setattr(svc, "get_schema_template", fake_get_template)
    monkeypatch.setattr(term_base_loader, "load_term_base", fake_load)
    system = "你是抽取助手"
    user = "[任务类别]:${feature}\n[特殊要求]:${special_requirement}\n[项目列表]:${检测项目.NAME}"
    res = await svc.preview_prompt(
        None, "kb1",
        schema_template_id=tpl_id, category_id=cat["id"],
        group_value="热膨胀",
        system_prompt=system, user_prompt=user,
    )
    assert "[任务类别]:热膨胀" in res["user"]
    assert "[特殊要求]:注意区分线膨胀与体膨胀" in res["user"]
    # group_field=NAME 过滤后只保留热膨胀
    assert "[项目列表]:[热膨胀]" in res["user"]


async def test_preview_prompt_unconfigured_empty(monkeypatch):
    """L1PV-02：未配置特殊要求的展开类别渲染为空串。"""
    tpl_id = str(uuid.uuid4())
    cat = _category()

    async def fake_get_template(db, kb_id, template_id):
        return {"id": tpl_id, "name": "T", "categories": [cat]}

    async def fake_load(db, kb_id, term_base_id):
        return [{"term_name": "x", "extras": {"NAME": "相变点"}}]

    monkeypatch.setattr(svc, "get_schema_template", fake_get_template)
    monkeypatch.setattr(term_base_loader, "load_term_base", fake_load)
    res = await svc.preview_prompt(
        None, "kb1",
        schema_template_id=tpl_id, category_id=cat["id"],
        group_value="相变点",
        system_prompt="s", user_prompt="[特殊要求]:${special_requirement}",
    )
    assert res["user"] == "[特殊要求]:"


async def test_preview_prompt_simple_mode_no_category(monkeypatch):
    """L1PV-03：无类别（simple 模式）不抛错，context 占位说明。"""
    res = await svc.preview_prompt(
        None, "kb1",
        system_prompt="s", user_prompt="内容：${context}",
    )
    assert "文档上下文将在实际抽取时注入" in res["user"]
