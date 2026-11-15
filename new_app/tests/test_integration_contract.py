from types import SimpleNamespace

from services.orchestration.integration_api import (
    _display_requirement,
    _filename_standard,
    _heat_rows,
    _item_rows,
    _state_values,
)


def _run(status: str, progress: int):
    return SimpleNamespace(status=status, progress=progress, error_code=None)


def test_state_mapping_matches_legacy_pair() -> None:
    assert _state_values(None) == ("pending", "pending", 0, 0, "")
    assert _state_values(_run("RECEIVED", 0)) == ("pending", "pending", 0, 0, "")
    assert _state_values(_run("OCR_RUNNING", 10)) == ("processing", "pending", 40, 0, "")
    assert _state_values(_run("OCR_DONE", 25)) == ("completed", "pending", 100, 0, "")
    assert _state_values(_run("SANDBOX_RUNNING", 60)) == (
        "completed",
        "running",
        100,
        50,
        "",
    )
    assert _state_values(_run("HUMAN_REVIEW", 95)) == (
        "completed",
        "completed",
        100,
        100,
        "",
    )
    assert _state_values(_run("FAILED", 10))[0:2] == ("failed", "pending")


def test_item_rows_keep_legacy_columns() -> None:
    records = [
        {
            "profile": "chemical_composition",
            "grade": "Q355B",
            "conditions": {"试验方法": "GB/T 223"},
            "properties": {
                "C": {
                    "raw": "0.20",
                    "operator": "≤",
                    "unit": "%",
                    "business_category": "化学成分",
                    "business_item": "C",
                    "meta": {},
                }
            },
        }
    ]
    categories = _item_rows(records)
    assert [item["feature"] for item in categories] == ["化学成分"]
    row = categories[0]["records"][0]
    assert row["项目名称"] == "C"
    assert row["材料牌号"] == "Q355B"
    assert row["标准要求"] == "≤0.20"
    assert row["单位"] == "%"
    assert row["试验方法"] == "GB/T 223"
    assert "锻件类型" in row


def test_heat_rows_use_heat_columns() -> None:
    records = [
        {
            "profile": "heat_treatment",
            "grade": "TC4",
            "conditions": {"工序名称": "退火", "项目大类": "热处理制度"},
            "properties": {
                "保温温度": {"raw": "750", "unit": "℃"},
                "保温时间": {"raw": "2", "unit": "h"},
            },
        }
    ]
    categories = _heat_rows(records)
    assert categories[0]["feature"] == "热处理制度"
    row = categories[0]["records"][0]
    assert row["工序名称"] == "退火"
    assert row["保温温度"] == "750 ℃"
    assert row["材料牌号"] == "TC4"


def test_filename_standard_and_requirement() -> None:
    assert _filename_standard("GB_T 1591-2018 低合金高强度结构钢.pdf") == (
        "GB/T 1591-2018",
        "低合金高强度结构钢",
    )
    assert _display_requirement({"raw": "0.20", "operator": "≤"}) == "≤0.20"
    assert _display_requirement({"raw": "355~470", "operator": "~"}) == "355~470"
