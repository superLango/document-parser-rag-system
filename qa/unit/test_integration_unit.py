"""L1 单元：系统对接（schema 过滤 / 任务视图 / prompt 校验）。"""

import uuid

import pytest

from app.core.exceptions import BusinessException
from app.services import integration_service


def _apply_schema_filter(schema_templates: list[dict], schema_template_id):
    """复刻 pipeline.run 的 schema 过滤逻辑。"""
    if schema_template_id:
        return [
            t for t in schema_templates
            if str(t.get("id")) == str(schema_template_id)
        ]
    return schema_templates


async def test_pipeline_schema_filter():
    """L1IT-01：指定 schema_template_id 时仅保留该模板类别。"""
    t1 = {"id": str(uuid.uuid4()), "name": "A", "categories": [{"id": "c1"}]}
    t2 = {"id": str(uuid.uuid4()), "name": "B", "categories": [{"id": "c2"}]}
    kept = _apply_schema_filter([t1, t2], t1["id"])
    assert [t["id"] for t in kept] == [t1["id"]]
    # 不传时保留全部
    assert len(_apply_schema_filter([t1, t2], None)) == 2


async def test_integration_view_fields():
    """L1IT-02：任务视图包含双阶段状态与错误字段。"""
    from types import SimpleNamespace

    itask = SimpleNamespace(
        task_id=uuid.uuid4(), kb_id=uuid.uuid4(), document_id=uuid.uuid4(),
        prompt_id=uuid.uuid4(), schema_template_id=uuid.uuid4(),
        filename="a.pdf", ocr_status="completed", ocr_progress=100,
        extract_status="queued", extract_progress=0, error="",
        result_version=None, created_at=None, updated_at=None,
    )
    v = integration_service.to_view(itask)
    assert v["ocr_status"] == "completed"
    assert v["extract_status"] == "queued"
    assert v["document_id"] is not None
    assert "error" in v and "result_version" in v


async def test_prompt_schema_validation(monkeypatch):
    """L1IT-03：prompt 不存在或未绑定 Schema 时抛业务异常。"""

    class _FakePrompt:
        def __init__(self, schema_template_id):
            self.schema_template_id = schema_template_id

    async def fake_execute(statement):
        class _R:
            def scalar_one_or_none(self):
                return None  # prompt 不存在
        return _R()

    from types import SimpleNamespace

    db = SimpleNamespace(execute=fake_execute)
    with pytest.raises(BusinessException):
        await integration_service._get_prompt_schema(
            db, uuid.uuid4(), uuid.uuid4()
        )


async def test_apply_extract_result_status(monkeypatch):
    """L1IT-04：抽取结果回写按 status 区分成功/失败。"""
    from app.tasks import arq_worker

    calls: list[dict] = []

    async def fake_update(db, document_id, **patch):
        calls.append(patch)

    monkeypatch.setattr(arq_worker, "_update_integration_task", fake_update)
    # 成功：取 version
    await arq_worker._apply_extract_result(None, "doc1", {"status": "completed", "version": 3})
    assert calls[-1]["extract_status"] == "completed"
    assert calls[-1]["result_version"] == 3
    # 失败：回写 failed + 错误原因（不抛异常）
    await arq_worker._apply_extract_result(None, "doc1", {"status": "failed", "error": "LLM 不可用"})
    assert calls[-1]["extract_status"] == "failed"
    assert "LLM 不可用" in calls[-1]["error"]


async def test_extraction_result_update_schema():
    """L1IT-05：结果保存 Schema 接受人工编辑后的 categories。"""
    from pydantic import ValidationError

    from app.schemas.extraction import ExtractionResultUpdate

    payload = ExtractionResultUpdate(categories=[
        {"feature": "室温拉伸", "records": [{"材料牌号": "GH4169", "项目名称": "抗拉强度(Rm)"}], "rejected": [], "missing_fields": []},
        {"feature": "化学成分", "records": []},
    ])
    assert len(payload.categories) == 2
    assert payload.categories[0]["feature"] == "室温拉伸"
    with pytest.raises(ValidationError):
        ExtractionResultUpdate(categories="not-a-list")
