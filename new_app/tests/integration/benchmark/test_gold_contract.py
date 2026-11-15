from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
GOLD_DIR = REPO_ROOT / "gold_standard_30"
SCRIPT = REPO_ROOT / "new_app" / "scripts" / "benchmark" / "gold_eval.py"
ITEM_FIELDS = {
    "项目名称",
    "材料牌号",
    "标准要求",
    "单位",
    "试验方法",
    "试验温度",
    "位置",
    "方向",
    "尺寸厚度",
    "试样状态",
    "取样数量",
    "取样说明",
    "锻件类型",
}
HEAT_FIELDS = {
    "材料牌号",
    "工序名称",
    "工艺名称",
    "项目大类",
    "保温温度",
    "保温时间",
    "升温速率",
    "降温速率",
    "装炉温度",
    "出炉温度",
    "冷却介质",
    "介质温度",
}


def load_module():
    if not SCRIPT.exists():
        pytest.skip("gold_eval.py missing")
    spec = importlib.util.spec_from_file_location("gold_eval_contract", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def gold_documents() -> list[Path]:
    if not GOLD_DIR.exists():
        pytest.skip("gold_standard_30 not checked out")
    return sorted((GOLD_DIR / "documents").glob("*.json"))


def test_registry_covers_all_gold_documents() -> None:
    registry_path = REPO_ROOT / "new_app" / "docs" / "reports" / "gold-registry.json"
    if not registry_path.exists() or not GOLD_DIR.exists():
        pytest.skip("gold registry not generated")
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    assert len(registry["documents"]) == 30
    assert all(item["run_id"] for item in registry["documents"])
    assert registry["summary"]["items"] == 25377
    assert registry["summary"]["heat_treatment"] == 261


def test_gold_rows_keep_full_schema() -> None:
    documents = gold_documents()
    assert len(documents) == 30
    for path in documents:
        payload = json.loads(path.read_text(encoding="utf-8"))
        for category in payload["categories"]:
            feature = category["feature"]
            for record in category["records"]:
                if feature == "标准信息":
                    assert set(record) == {"标准名称", "标准编号"}
                elif feature == "热处理制度":
                    assert set(record) == HEAT_FIELDS, (path.name, feature)
                else:
                    assert set(record) == ITEM_FIELDS, (path.name, feature)


def test_gold_placeholders_are_counted() -> None:
    module = load_module()
    rows, placeholders = module.load_gold_rows("gbt-1591-2018")
    assert rows
    assert placeholders > 0
    assert len(rows) + placeholders == 1735


def test_value_normalization() -> None:
    module = load_module()
    assert module.canon_req("不大于 0.20") == "≤0.2"
    assert module.canon_req("≥ 60 MPa") == "≥60"
    assert module.canon_req("0.05～0.25") == "0.05~0.25"
    assert module.canon_grade("UNS N07718") == "n07718"
    assert module.canon_grade("Alloy N06035") == "n06035"
    assert module.canon_grade("90%tantalum-10%tungsten(R05255)") == "r05255"
    assert module.canon_grade("2HB,C") == "2h"
    assert module.split_grades("Q355NB、C、D") == ["q355nb", "q355nc", "q355nd"]
    assert module.split_grades("R05200/R05400") == ["r05200", "r05400"]


def test_adapt_record_chemical_and_mechanical() -> None:
    module = load_module()
    chemical = {
        "profile": "chemical_composition",
        "grade": "Q355B",
        "conditions": {},
        "properties": {
            "C": {"raw": "0.24", "column": "C / 不大于", "unit": "%", "value": 0.24},
            "Si": {"raw": "不大于", "column": "Si / 不大于", "unit": "%", "value": None},
        },
    }
    rows = module.adapt_record(chemical)
    assert [(row["项目名称"], row["标准要求"]) for row in rows] == [("C", "≤0.24")]

    mechanical = {
        "profile": "mechanical_properties",
        "grade": "2HB,C",
        "conditions": {"厚度": ">6.00~12.50", "试样状态": "T6"},
        "properties": {
            "Rm": {
                "raw": "35",
                "column": "Tensile Strength,min / ksi",
                "unit": "ksi",
                "value": 35.0,
            },
            "A": {
                "raw": "24",
                "column": "Elongation in 2 in. or 50 mm, %",
                "unit": "%",
                "value": 24.0,
            },
        },
    }
    rows = module.adapt_record(mechanical)
    assert {row["材料牌号"] for row in rows} == {"2h"}
    assert {(row["项目名称"], row["标准要求"]) for row in rows} == {
        ("抗拉强度", "≥35"),
        ("断后伸长率", "≥24"),
    }
    assert all(row["尺寸厚度"] == ">6.00~12.50" for row in rows)
    assert all(row["试样状态"] == "T6" for row in rows)
