from __future__ import annotations

from app_v3.normalize.pipeline import normalize_record, normalize_records, summarize


def test_normalize_record_v2_sample():
    record = {
        "record_id": "T9-1-3",
        "category": "室温拉伸",
        "item": "抗拉强度Rm",
        "grade": "N4、N5",
        "requirement": "≥345",
        "unit": "MPa",
        "conditions": {"试验温度": "室温", "试样状态": "M", "尺寸厚度": "0.1~1.5", "方向": "L"},
        "source_table": "T9",
        "page_no": 9,
    }
    result = normalize_record(record, aliases={"M": "软态(M)"})
    assert result["item"] == "抗拉强度(Rm)"
    assert result["grade"] == "N4"
    assert "N5" in result["grade_aliases"]
    assert result["conditions"]["试样状态"] == "软态(M)"
    assert result["conditions"]["尺寸厚度"] == "0.1~1.5mm"
    assert result["conditions"]["方向"] == "纵向"
    assert result["operator"] == "≥"
    assert result["status"] == "ok"
    assert result["schema_version"] == "record.v1"


def test_normalize_english_item_and_grade():
    record = {
        "record_id": "r1",
        "category": "室温拉伸",
        "item": "Tensile strength",
        "grade": "Ti-6Al-4V",
        "requirement": "≥931",
        "unit": "MPa",
        "evidence": {"source": "table", "table_id": "T1"},
    }
    result = normalize_record(record)
    assert result["item"] == "抗拉强度(Rm)"
    assert result["grade"] == "Ti-6Al-4V"
    assert "6Al-4V" in result["grade_aliases"]
    assert result["unit"] == "MPa"


def test_chemical_element_not_mismapped():
    from app_v3.normalize.items import normalize_item

    assert normalize_item("Al")[0] == "Al"
    assert normalize_item("C")[0] == "C"
    assert normalize_item("Tensile strength")[0] == "抗拉强度(Rm)"


def test_grade_phrase_rejected():
    record = {
        "record_id": "r2",
        "category": "室温拉伸",
        "item": "抗拉强度(Rm)",
        "grade": "Up to 2.000,incl(1)",
        "requirement": "135",
        "unit": "MPa",
        "evidence": {"source": "table", "table_id": "T1"},
    }
    result = normalize_record(record)
    codes = {diagnostic["code"] for diagnostic in result["diagnostics"]}
    assert "grade_rejected" in codes
    assert result["grade"] == ""
    assert result["status"] == "warn"


def test_missing_fields_unresolved():
    result = normalize_record({"record_id": "r3", "requirement": "1"})
    assert result["status"] == "unresolved"
    codes = {diagnostic["code"] for diagnostic in result["diagnostics"]}
    assert "missing_category" in codes
    assert "missing_item" in codes


def test_standard_info_allowed():
    result = normalize_record({
        "record_id": "meta",
        "category": "标准信息",
        "item": "标准名称",
        "requirement": "镍及镍合金板",
        "unit": "",
        "evidence": {"source": "metadata"},
    })
    assert result["status"] == "ok"


def test_summarize():
    records = [
        normalize_record({"record_id": "a", "category": "室温拉伸", "item": "抗拉强度Rm",
                          "grade": "N4", "requirement": "≥345", "unit": "MPa",
                          "evidence": {"source": "table", "table_id": "T1"}}),
        normalize_record({"record_id": "b"}),
    ]
    summary = summarize(records)
    assert summary["total"] == 2
    assert summary["status"]["ok"] == 1
    assert summary["status"]["unresolved"] == 1
    assert summary["grade_resolved"] == 1
