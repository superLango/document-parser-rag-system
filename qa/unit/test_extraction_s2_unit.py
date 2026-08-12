"""L1 单元测试：M34-S2 抽取配置服务辅助逻辑。"""

from app.services import extraction_config_service as svc


def test_script_io_registry():
    """L1M34-S2-01：脚本 IO 注册包含 post/validation 目录与工具。"""
    data = svc.script_io_registry()
    assert set(data["folders"]) == {"post", "validation"}
    for folder in ("post", "validation"):
        assert data["folders"][folder]["input"]
        assert data["folders"][folder]["output"]
        assert any("get_term_records" in t for t in data["folders"][folder]["tools"])


def test_qs_to_dict():
    """L1M34-S2-02：QuerySource 对象与 dict 统一转 dict。"""
    assert svc._qs_to_dict({"a": 1}) == {"a": 1}

    class FakeQS:
        def model_dump(self):
            return {"label": "x", "value_field": "name"}

    assert svc._qs_to_dict(FakeQS()) == {"label": "x", "value_field": "name"}


def test_run_template_contract():
    """L1M34-S2-03：脚本运行模板包含 kb_tools 桩与 def run 调用。"""
    assert "kb_tools = _KbTools()" in svc._RUN_TEMPLATE
    assert "result = run(args)" in svc._RUN_TEMPLATE
    assert "TERM_DATA = {term_data}" in svc._RUN_TEMPLATE


def test_serializers_exist():
    """L1M34-S2-04：Schema/Prompt 序列化函数存在且返回关键字段。"""
    from datetime import datetime, timezone

    from app.models.extraction import SchemaTemplate

    t = SchemaTemplate(id="1", kb_id="2", name="T", description="", is_active=True, sort_order=0,
                       created_at=datetime.now(timezone.utc))
    d = svc._serialize_template(t)
    assert d["name"] == "T" and d["categories"] == []
