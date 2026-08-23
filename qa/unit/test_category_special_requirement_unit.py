"""L1 单元：术语类别特殊要求（Schema 配置 → 展开 → Prompt 组装）。"""

from types import SimpleNamespace

from app.services.extraction import category_builder, prompt_renderer
from app.services.extraction.extraction_models import ExtractionTarget
from app.services.extraction_config_service import _clean_special_requirements


async def test_prompt_renderer_special_requirement():
    """L1SR-01：${special_requirement}/${category_requirement} 渲染与空值。"""
    cfg = SimpleNamespace(prompt_templates=[{
        "schema_template_id": "t1",
        "categories": [{
            "category_id": "c1",
            "user_prompt": "[特殊要求]:${special_requirement} ${category_requirement}",
            "system_prompt": "sys",
        }],
    }])
    target = ExtractionTarget(
        feature="室温拉伸", category_id="c1", template_id="t1",
        special_requirement="注意按纵向取样",
    )
    _, user = prompt_renderer.render_category(cfg, target, "ctx")
    assert "[特殊要求]:注意按纵向取样 注意按纵向取样" == user

    empty = ExtractionTarget(
        feature="晶粒度", category_id="c1", template_id="t1", special_requirement="",
    )
    _, user2 = prompt_renderer.render_category(cfg, empty, "ctx")
    assert "[特殊要求]: " == user2


async def test_clean_special_requirements():
    """L1SR-02：清洗过滤空值/非字符串/超长文本。"""
    assert _clean_special_requirements(None) == {}
    assert _clean_special_requirements({}) == {}
    assert _clean_special_requirements({"a": "  x  ", "b": "", "c": 123, "d": None}) == {"a": "x"}
    long_v = _clean_special_requirements({"a": "x" * 2000})["a"]
    assert len(long_v) == 1000


async def test_build_targets_term_base_special_req(monkeypatch):
    """L1SR-03：术语集展开时按类别名挂载特殊要求，未配置的为空。"""
    rows = [
        {"term_name": "室温拉伸"},
        {"term_name": "化学成分"},
        {"term_name": "晶粒度"},
    ]

    async def _fake_load(db, kb, tb):
        return rows

    monkeypatch.setattr(category_builder, "load_term_base", _fake_load)
    cfg = SimpleNamespace(
        schema_templates=[{
            "id": "t1", "name": "T", "is_active": True,
            "categories": [{
                "id": "c1", "name": "", "description": "", "return_type": "array",
                "extraction_strategy": "auto", "fixed_query": "", "query_sources": [],
                "top_k": None, "max_tokens": None, "confidence_threshold": None,
                "fields": [], "name_source": "term_base",
                "name_term_base_id": "00000000-0000-0000-0000-000000000001", "name_term_field": "term_name",
                "special_requirements": {
                    "室温拉伸": "注意按纵向取样",
                    "化学成分": "仅抽取各元素含量，不合并",
                },
                "is_active": True,
            }],
        }],
        term_bases=[{"id": "00000000-0000-0000-0000-000000000001", "name": "项目大类"}],
    )
    targets, skipped = await category_builder._build_targets(cfg, None, "kb1")
    by_feature = {t.feature: t for t in targets}
    assert by_feature["室温拉伸"].special_requirement == "注意按纵向取样"
    assert by_feature["化学成分"].special_requirement == "仅抽取各元素含量，不合并"
    assert by_feature["晶粒度"].special_requirement == ""
    assert skipped == []


async def test_build_targets_manual_special_req():
    """L1SR-04：手动类别按自身名称匹配特殊要求。"""
    cfg = SimpleNamespace(
        schema_templates=[{
            "id": "t1", "name": "T", "is_active": True,
            "categories": [{
                "id": "c1", "name": "标准信息", "description": "", "return_type": "object",
                "extraction_strategy": "always", "fixed_query": "", "query_sources": [],
                "top_k": None, "max_tokens": None, "confidence_threshold": None,
                "fields": [], "name_source": "manual",
                "name_term_base_id": None, "name_term_field": "",
                "special_requirements": {"标准信息": "只输出标准名称和标准编号"},
                "is_active": True,
            }],
        }],
        term_bases=[],
    )
    targets, _ = await category_builder._build_targets(cfg, None, "kb1")
    assert len(targets) == 1
    assert targets[0].special_requirement == "只输出标准名称和标准编号"
