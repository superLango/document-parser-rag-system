"""L1 单元：抽取结果简化视图（categories 仅保留 feature + result）。"""

from app.services.extraction.result_store import to_simple_view


def test_to_simple_view_keeps_only_feature_and_result():
    """L1M34-18：简化视图只保留 feature 与 result，剔除其余参数。"""
    full = {
        "schema_name": "模板",
        "status": "completed",
        "categories": [
            {
                "feature": "室温拉伸",
                "records": [{"材料牌号": "GH4169"}],
                "rejected": [{"项目名称": "噪声"}],
                "missing_fields": ["温度"],
                "hit_score": 0.5,
                "hit_count": 3,
            },
            {
                "feature": "热处理制度",
                "records": [],
                "rejected": [],
                "missing_fields": [],
                "hit_score": None,
                "hit_count": 0,
            },
        ],
        "summary": {"total_records": 1},
        "timing": {"total_sec": 10},
    }
    simple = to_simple_view(full)
    assert set(simple.keys()) == {"categories"}
    assert simple["categories"] == [
        {"feature": "室温拉伸", "result": [{"材料牌号": "GH4169"}]},
        {"feature": "热处理制度", "result": []},
    ]
    for cat in simple["categories"]:
        assert set(cat.keys()) == {"feature", "result"}


def test_to_simple_view_empty():
    """L1M34-19：无类别时返回空 categories。"""
    assert to_simple_view({}) == {"categories": []}
