from __future__ import annotations

from services.sandbox.runtime import builtin
from services.sandbox.runtime.clauses import extract_clauses
from services.sandbox.runtime.dictionary import (
    align_item,
    align_method,
    normalize_method,
)
from services.sandbox.runtime.inventory import build_inventory, extract_classifications
from services.sandbox.runtime.projection import apply_document_intelligence
from services.sandbox.runtime.references import extract_references

OCR = {
    "pages": [
        {
            "page_no": 1,
            "markdown": "\n".join(
                [
                    "# Page 1",
                    "1 范围",
                    "本文件适用于压力容器用钢板。",
                    "2 规范性引用文件",
                    "GB/T 228.1 金属材料 拉伸试验 第1部分：室温试验方法",
                    "5.1 化学成分",
                    "化学成分应符合表1的规定。",
                    "5.2 力学性能",
                    "室温拉伸试验按 GB/T 228.1 进行。",
                    "6.1 晶粒度",
                    "晶粒度应按",
                ]
            ),
        },
        {
            "page_no": 2,
            "markdown": "\n".join(
                [
                    "# Page 2",
                    "GB/T 6394 进行检验，晶粒度级别应不低于5级。",
                    "6.2 低倍组织",
                    "低倍组织应按 GB/T 226 进行检验，不得有裂纹。",
                ]
            ),
        },
    ],
    "tables": [],
}


def _clauses() -> dict[str, dict]:
    payload = extract_clauses(OCR)
    return {item["clause_id"]: item for item in payload["clauses"]}


def test_clause_fields_and_evidence() -> None:
    payload = extract_clauses(OCR)
    clauses = _clauses()
    assert payload["schema_version"] == "document-clauses/1"
    assert clauses["1"]["kind"] == "scope"
    assert clauses["2"]["kind"] == "normative_reference"
    # Cross-page continuation stays in the clause opened on page 1.
    requirement = clauses["6.1"]["fields"]["requirement"]["raw"]
    assert requirement.startswith("晶粒度应按 GB/T 6394")
    assert "不低于5级" in requirement
    assert clauses["6.1"]["page_no"] == 1
    assert clauses["6.1"]["fields"]["method_standard"]["raw"] == "GB/T 6394"
    assert clauses["6.2"]["fields"]["method_standard"]["raw"] == "GB/T 226"
    assert "sample_location" not in clauses["6.2"]["fields"]
    assert clauses["5.1"]["fields"]["requirement"]["raw"].startswith("化学成分应符合")
    evidence_ids = {item["evidence_id"] for item in payload["evidence"]}
    assert "ev-clause-6.1" in evidence_ids


def test_toc_entries_do_not_shadow_real_headings() -> None:
    ocr = {
        "pages": [
            {
                "page_no": 1,
                "markdown": "\n".join(
                    [
                        "3 技术要求 ..... 5",
                        "3.1 化学成分 ..... 6",
                        "3.1 化学成分",
                        "化学成分应符合表1的规定。",
                    ]
                ),
            }
        ]
    }
    clauses = extract_clauses(ocr)["clauses"]
    assert [item["clause_id"] for item in clauses] == ["3.1"]
    assert clauses[0]["text"].startswith("化学成分应符合")


def test_fullwidth_headings_and_title_gated_qualitative_items() -> None:
    ocr = {
        "pages": [
            {
                "page_no": 1,
                "markdown": "\n".join(
                    [
                        "５ 订货内容",
                        "５．１ 按本标准订购的合同应符合采购方要求，注明尺寸、外形。",
                        "６ 尺寸、外形、重量",
                        "６．１ 热轧钢棒的尺寸、外形、重量及允许偏差应符合GB/T702的规定。",
                    ]
                ),
            }
        ]
    }
    clauses = extract_clauses(ocr)["clauses"]
    assert [item["clause_id"] for item in clauses] == ["5", "5.1", "6", "6.1"]
    records: list[dict] = []
    evidence: list[dict] = []
    payloads = apply_document_intelligence(records, evidence, ocr, [])
    qualitative = {
        name for item in records if item["profile"] == "qualitative" for name in item["properties"]
    }
    assert qualitative == {"尺寸"}
    entry = next(
        item for item in payloads["inventory"]["items"] if item["feature"] == "尺寸"
    )
    assert entry["requirement"].startswith("热轧钢棒的尺寸")
    assert entry["clause_id"] == "6"


def test_english_headings_and_prose_items() -> None:
    ocr = {
        "pages": [
            {
                "page_no": 1,
                "markdown": "\n".join(
                    [
                        "1. Scope",
                        "1.1 This specification covers titanium plate.",
                        "2. Referenced Documents",
                        "2.1 ASTM Standards:3",
                        "E213 Practice for Ultrasonic Testing of Metal Pipe and Tubing",
                        "E112 Test Methods for Determining Average Grain Size",
                        "3. Technical Requirements",
                        "3.1 Composition",
                        "Shall conform to the percentages shown in Table 1.",
                        "3.2 Quality",
                        (
                            "Product shall be uniform in quality and condition, "
                            "sound, and free of foreign materials."
                        ),
                        "3.3 Tolerances",
                        "Shall conform to all applicable requirements of ANSI H35.2.",
                        "3.4 Internal Defects",
                        (
                            "When specified, plate shall be ultrasonically inspected "
                            "in accordance with ASTM B594."
                        ),
                        "3.5 Grain Size",
                        "Average grain size shall be no coarser than ASTM No. 5.",
                        "3.6 Microstructure",
                        (
                            "Microstructure shall be free of continuous alpha "
                            "at prior beta grain boundaries."
                        ),
                        "4. Dimensions",
                        (
                            "Variations in dimensions shall not exceed the amounts "
                            "prescribed in Table 5."
                        ),
                    ]
                ),
            }
        ],
        "tables": [],
    }
    clauses_payload = extract_clauses(ocr)
    clauses = {item["clause_id"]: item for item in clauses_payload["clauses"]}
    assert clauses["1"]["kind"] == "scope"
    assert clauses["2"]["kind"] == "normative_reference"
    assert clauses["3"]["kind"] == "technical_requirement"
    inventory = build_inventory([], clauses_payload, [], ocr)
    items = {item["feature"]: item for item in inventory["items"] if item["feature"]}
    for feature in ("外观", "尺寸", "超声波检测", "晶粒度", "高倍组织"):
        assert feature in items
    assert items["外观"]["requirement"].startswith("Product shall be uniform")
    assert "Variations in dimensions" in items["尺寸"]["requirement"]
    assert items["超声波检测"]["requirement"].startswith(
        "When specified, plate shall be ultrasonically inspected"
    )
    references = extract_references(ocr, clauses_payload, [])
    numbers = {item["standard_no"] for item in references["references"]}
    assert "ASTM E213" in numbers
    assert "ASTM B594" in numbers


def test_chinese_list_qualitative_items() -> None:
    ocr = {
        "pages": [
            {
                "page_no": 1,
                "markdown": "\n".join(
                    [
                        "6 技术要求",
                        "6.1 表面质量",
                        "钢管的内外表面不应有裂纹、折叠和结疤。",
                        "6.2 其他特殊要求",
                        "需方有下述其他特殊要求时,由供需双方协商,并在合同中注明:",
                        "a) 晶粒度;",
                        "b) 非金属夹杂物;",
                    ]
                ),
            }
        ]
    }
    clauses_payload = extract_clauses(ocr)
    inventory = build_inventory([], clauses_payload, [], ocr)
    items = {item["feature"]: item for item in inventory["items"] if item["feature"]}
    assert items["外观"]["requirement"].startswith("钢管的内外表面不应有裂纹")
    # 清单导语只说明“需方提出时才适用”，具体项目名才是该项要求。
    assert items["晶粒度"]["requirement"] == "晶粒度"
    assert items["非金属夹杂"]["requirement"] == "非金属夹杂物"


def test_table_footnote_prose_items() -> None:
    ocr = {
        "pages": [
            {
                "page_no": 1,
                "markdown": "\n".join(
                    [
                        "TABLE 3 Metallurgical Properties",
                        "<table border=\"1\"><tr><td>Grain Size</td><td>ASTM 5</td></tr></table>",
                        (
                            "A The structure of all material shall be uniform "
                            "throughout the thickness."
                        ),
                        (
                            "The grain size in individual areas shall not vary "
                            "more than 2 ASTM numbers."
                        ),
                    ]
                ),
            }
        ]
    }
    clauses_payload = extract_clauses(ocr)
    inventory = build_inventory([], clauses_payload, [], ocr)
    items = {item["feature"]: item for item in inventory["items"] if item["feature"]}
    assert items["高倍组织"]["requirement"].startswith("The structure of all material")
    assert items["晶粒度"]["requirement"].startswith("The grain size in individual areas")


def test_english_chemical_analysis_methods_from_clause() -> None:
    prose = builtin._prose_methods(
        "7.1.4 Methods and practices relating to chemical analysis required by "
        "this specification shall be in accordance with Test Methods E539, "
        "E1409, E1447, E1941, E2371, and/or E2994, or other analytical methods "
        "as agreed upon between the purchaser and the supplier."
    )
    assert prose["化学成分"].startswith("ASTM E539")
    assert "ASTM E2371" in prose["化学成分"]
    meta = builtin._metadata_for("化学成分", [], prose, {}, "", "")
    assert meta["试验方法"].startswith("ASTM E539")


def test_english_chemical_analysis_pointer_resolves_reference_list() -> None:
    prose = builtin._prose_methods(
        "\n".join(
            [
                "2.1 ASTM Standards:",
                "E8 Test Methods for Tension Testing of Metallic Materials",
                (
                    "E539 Test Method for Analysis of Titanium Alloys by "
                    "X-Ray Fluorescence Spectrometry"
                ),
                (
                    "E1409 Test Method for Determination of Oxygen and Nitrogen "
                    "in Titanium and Titanium Alloys"
                ),
                "E1447 Test Method for Determination of Hydrogen in Titanium",
                (
                    "10.1 The chemical analysis shall normally be conducted using "
                    "the ASTM standard test methods referenced in 2.1."
                ),
            ]
        )
    )
    assert prose["化学成分"] == "ASTM E539、ASTM E1409、ASTM E1447"


def test_chemical_method_stays_empty_without_source_statement() -> None:
    prose = builtin._prose_methods(
        "5.1 The grades covered by this specification shall conform to the "
        "chemical composition requirements prescribed in Table 1."
    )
    assert "化学成分" not in prose


def test_room_temperature_default_for_room_tensile() -> None:
    meta = builtin._metadata_for("室温拉伸", [], {}, {}, "", "")
    assert meta["试验温度"] == "室温"
    assert "试验温度" not in builtin._metadata_for("高温拉伸", [], {}, {}, "", "")
    records = [
        {
            "record_id": "T1",
            "table_id": "T1",
            "profile": "mechanical_properties",
            "grade": "Q355B",
            "conditions": {},
            "properties": {
                "Rm": {
                    "raw": "500",
                    "value": 500,
                    "unit": "MPa",
                    "meta": {"试验温度": "350℃"},
                }
            },
        }
    ]
    builtin.apply_document_metadata(
        records,
        {"markdown": "室温拉伸试验按 GB/T 228.1 进行。", "pages": [], "tables": []},
        [],
    )
    assert records[0]["properties"]["Rm"]["meta"]["试验温度"] == "350℃"


def test_html_markup_is_stripped_from_record_fields() -> None:
    records: list[dict] = [
        {
            "record_id": "T1-R1",
            "table_id": "T1",
            "page_no": 3,
            "row_index": 0,
            "profile": "mechanical_properties",
            "grade": "Q355B",
            "conditions": {"取样说明": "~0.50</td><td>125~175</td></tr>"},
            "condition_key": "",
            "properties": {
                "Rm": {
                    "value": 470,
                    "unit": "MPa",
                    "raw": "<td>470</td>",
                    "meta": {"取样说明": "</td></tr><tr><td colspan=\"6\">a说明"},
                }
            },
            "evidence_refs": ["T1-R1"],
        }
    ]
    evidence: list[dict] = [
        {"evidence_id": "T1-R1", "table_id": "T1", "quote": "<td>470</td>"}
    ]
    apply_document_intelligence(records, evidence, OCR, [])
    prop = records[0]["properties"]["Rm"]
    assert prop["raw"] == "470"
    assert "<" not in prop["meta"]["取样说明"]
    assert "<" not in records[0]["conditions"]["取样说明"]
    assert evidence[0]["quote"] == "470"


def test_inventory_merges_table_inspection_and_clause() -> None:
    records = [
        {
            "record_id": "T1-R1",
            "table_id": "T1",
            "page_no": 3,
            "profile": "mechanical_properties",
            "grade": "Q355B",
            "conditions": {},
            "properties": {"Rm": {"value": 470, "unit": "MPa"}},
        }
    ]
    inspections = [
        {
            "item": "室温拉伸",
            "quantity": "每批1个",
            "location": "按 GB/T 2975",
            "method": "GB/T 228.1",
            "clause": "",
            "note": "",
            "combined": "",
        },
        {"item": "说明", "quantity": "", "location": "", "method": "", "clause": "", "note": ""},
    ]
    inventory = build_inventory(records, extract_clauses(OCR), inspections)
    items = {item["feature"] or item["item"]: item for item in inventory["items"]}
    assert items["室温拉伸"]["status"] == "confirmed"
    assert "property_table" in items["室温拉伸"]["sources"]
    assert "inspection_table" in items["室温拉伸"]["sources"]
    assert items["晶粒度"]["status"] == "probable"
    assert items["晶粒度"]["clause_id"] == "6.1"
    assert items["晶粒度"]["method"] == "GB/T 6394"
    assert "说明" not in items
    assert inventory["coverage"]["aligned_ratio"] == 1.0


def test_projection_adds_qualitative_records_with_traceability() -> None:
    records: list[dict] = [
        {
            "record_id": "T1-R1",
            "table_id": "T1",
            "page_no": 3,
            "row_index": 0,
            "profile": "mechanical_properties",
            "grade": "Q355B",
            "conditions": {},
            "condition_key": "",
            "properties": {"Rm": {"value": 470, "unit": "MPa", "raw": "470"}},
            "evidence_refs": ["T1-R1"],
        }
    ]
    evidence: list[dict] = [{"evidence_id": "T1-R1", "table_id": "T1"}]
    diagnostics: list[dict] = []
    payloads = apply_document_intelligence(records, evidence, OCR, diagnostics)

    qualitative = [item for item in records if item["profile"] == "qualitative"]
    features = {name for item in qualitative for name in item["properties"]}
    assert features == {"晶粒度", "低倍"}
    grain = next(item for item in qualitative if "晶粒度" in item["properties"])
    prop = grain["properties"]["晶粒度"]
    assert prop["value"] is None
    assert prop["raw"].startswith("晶粒度应按 GB/T 6394")
    assert prop["meta"]["试验方法"] == "GB/T 6394-2017"
    assert prop["meta"]["试验方法原文"] == "GB/T 6394"
    assert grain["source"]["clause_id"] == "6.1"
    evidence_ids = {item["evidence_id"] for item in evidence}
    assert set(grain["evidence_refs"]) <= evidence_ids
    assert payloads["intelligence"]["stats"]["qualitative_records"] == 2
    assert payloads["inventory"]["coverage"]["aligned_ratio"] == 1.0
    assert payloads["references"]["stats"]["total"] >= 1
    assert payloads["intelligence"]["stats"]["dictionary"]["items_checked"] > 0
    # Existing numeric metadata backfill must keep working.
    assert records[0]["properties"]["Rm"]["meta"]["试验方法"] == "GB/T 228.1-2021"
    assert records[0]["properties"]["Rm"]["meta"]["试验方法原文"] == "GB/T 228.1"
    assert records[0]["properties"]["Rm"]["business_category"] == "室温拉伸"
    assert records[0]["properties"]["Rm"]["business_item"] == "抗拉强度"
    assert records[0]["properties"]["Rm"]["feature_in_dictionary"] is True


def test_dictionary_alignment_exact_alias_and_misses() -> None:
    assert align_item("KU2", "夏比冲击")["category"] == "冲击试验"
    assert align_item("Rm", "室温拉伸")["status"] == "alias"
    assert align_item("Rm", "室温拉伸")["item"] == "抗拉强度"
    assert align_item("晶粒度", "晶粒度")["category"] == "晶粒度Average Grain Size"
    assert align_item("尺寸", "尺寸")["category"] == "尺寸"
    assert align_item("完全不存在的项目", "")["status"] == "miss"
    assert align_item("弯曲压头直径", "弯曲")["item"] == ""
    aligned = align_method("GB/T 228.1-2010")
    assert aligned is not None
    assert aligned["standard_no"] == "GB/T 228.1-2021"
    newest = normalize_method("GB/T 5168-85")
    assert newest["matched"] is True
    assert newest["standard_no"] == "GB/T 5168-2020"
    missing = normalize_method("GB/T 99999-2020")
    assert missing["matched"] is False
    assert missing["text"] == "GB/T 99999"


def test_sampling_rule_extracts_quantity_and_direction() -> None:
    rule = "每批任取2卷（盘、根），各取1个纵向试样"
    assert builtin._sample_count(rule) == 2
    assert builtin._sample_direction(rule) == "纵向"
    assert builtin._sample_direction("各取1个横向试样") == "横向"
    assert builtin._sample_count("每批任取1份") == 1


def test_inspection_sampling_column_keeps_rule_and_direction() -> None:
    ocr = {
        "tables": [
            {
                "table_id": "T9",
                "page_no": 9,
                "header_paths": [
                    "检验项目",
                    "取样规定",
                    "技术要求的章条号",
                    "试验方法的章条号",
                ],
                "rows": [
                    ["检验项目", "取样规定", "技术要求的章条号", "试验方法的章条号"],
                    ["拉伸性能", "每批任取2卷（盘、根），各取1个纵向试样", "5.2", "6.2"],
                ],
                "header_rows": 1,
            }
        ]
    }
    items = builtin._inspection_items(ocr)
    assert items
    assert items[0]["quantity"].startswith("每批任取2卷")
    assert items[0]["direction"] == "纵向"
    assert "每批" in items[0]["note"]


def test_cross_standard_candidates_only_content_references() -> None:
    clauses = {
        "clauses": [
            {
                "clause_id": "5.1",
                "title": "化学成分",
                "text": "板材的化学成分应符合 GB/T 3620.1 的规定。",
                "kind": "technical",
                "page_no": 6,
            },
            {
                "clause_id": "5.1.2",
                "title": "化学成分",
                "text": "成品化学成分允许偏差应符合 GB/T 222 的规定。",
                "kind": "technical",
                "page_no": 6,
            },
            {
                "clause_id": "6.2",
                "title": "室温拉伸",
                "text": "产品的室温拉伸性能检验按 GB/T 228.1 的规定进行。",
                "kind": "technical",
                "page_no": 8,
            },
            {
                "clause_id": "1",
                "title": "范围",
                "text": "本文件规定了产品的化学成分要求，应符合 GB/T 9999 的规定。",
                "kind": "scope",
                "page_no": 1,
            },
        ]
    }
    payload = extract_references({}, clauses)
    candidates = payload["cross_standard_candidates"]
    standards = {item["standard_no"] for item in candidates}
    assert standards == {"GB/T 3620.1", "GB/T 222"}
    parameter = next(item for item in candidates if item["standard_no"] == "GB/T 222")
    assert parameter["scope"] == "parameter"
    assert parameter["parameter"] == "化学成分允许偏差"
    assert payload["stats"]["cross_standard_candidates"] == 2


def test_references_parse_normative_list_and_bind_methods() -> None:
    ocr = {
        "pages": [
            {
                "page_no": 1,
                "markdown": "\n".join(
                    [
                        "2 规范性引用文件",
                        "GB/T 228.1-2010 金属材料 拉伸试验 第1部分：室温试验方法",
                        "GB/T 229 金属材料 夏比摆锤冲击试验方法",
                        "3 技术要求",
                        "拉伸试验应按 GB/T 228.1 的规定进行。冲击试验应符合 GB/T 229 的要求。",
                        "高温拉伸试验还应符合 GB/T 4338 的规定。",
                    ]
                ),
            }
        ]
    }
    payload = extract_references(ocr, extract_clauses(ocr), [])
    references = {item["standard_no"]: item for item in payload["references"]}
    assert references["GB/T 228.1"]["relation"] == "normative"
    assert references["GB/T 228.1"]["resolved"] is True
    assert references["GB/T 4338"]["resolved"] is False
    assert payload["stats"]["normative"] == 2
    assert payload["stats"]["unresolved"] >= 1
    assert payload["bindings"]["室温拉伸"]["method"] == "GB/T 228.1"
    assert payload["bindings"]["夏比冲击"]["method"] == "GB/T 229"


def test_classification_tables_are_extracted() -> None:
    ocr = {
        "tables": [
            {
                "table_id": "T9",
                "page_no": 3,
                "header_rows": 1,
                "header_paths": [["牌号"], ["状态"], ["含义"]],
                "n_cols": 3,
                "rows": [
                    ["牌号", "状态", "含义"],
                    ["GH4169", "固溶", "固溶处理状态"],
                    ["GH4169", "时效", "时效处理状态"],
                ],
            },
            {
                "table_id": "T10",
                "page_no": 4,
                "header_rows": 1,
                "header_paths": [["中国牌号"], ["美国ASTM"]],
                "n_cols": 2,
                "rows": [
                    ["中国牌号", "美国ASTM"],
                    ["Q355B", "A572 Gr.50"],
                ],
            },
        ]
    }
    items = extract_classifications(ocr)
    states = [item for item in items if item["kind"] == "grade_state"]
    crosswalk = [item for item in items if item["kind"] == "grade_crosswalk"]
    assert len(states) == 2
    assert states[0]["grade"] == "GH4169"
    assert states[0]["state"] == "固溶"
    assert crosswalk[0]["crosswalk"]["美国ASTM"] == "A572 Gr.50"
    assert crosswalk[0]["page_no"] == 4

def _inventory(markdown: str) -> dict[str, dict]:
    ocr = {"pages": [{"page_no": 1, "markdown": markdown}], "tables": []}
    payload = build_inventory([], extract_clauses(ocr), [], ocr)
    return {
        item["feature"]: item
        for item in payload["items"]
        if item.get("feature")
    }


def test_surface_defect_enumeration_stays_appearance() -> None:
    items = _inventory(
        "\n".join(
            [
                "5 技术要求",
                "5.6 外观质量",
                "5.6.4 板材表面不应有裂纹、针孔、起皮、压折、金属或非金属夹杂物等缺陷。",
            ]
        )
    )
    assert "外观" in items
    assert items["外观"]["requirement"].startswith("板材表面不应有")
    assert "非金属夹杂" not in items


def test_delta_ferrite_is_not_microstructure() -> None:
    items = _inventory(
        "\n".join(
            [
                "3 技术要求",
                "3.7 δ-铁素体",
                "0Cr13Ni8Mo2Al 和0Cr15Ni5Cu4Nb 钢锻件显微组织中δ-铁素体的含量应不超过2%。",
            ]
        )
    )
    assert items["铁素体"]["requirement"].startswith("0Cr13Ni8Mo2Al")
    assert "高倍组织" not in items


def test_method_section_does_not_override_requirement() -> None:
    items = _inventory(
        "\n".join(
            [
                "5 技术要求",
                "5.5 外观质量",
                "5.5.2 丝材表面应清洁、无氧化色，不应有裂纹、起皮和夹杂等。",
                "6 试验方法",
                "6.5 外观质量",
                "产品的外观质量用目视检测的方法进行。",
            ]
        )
    )
    assert items["外观"]["requirement"].startswith("丝材表面应清洁")


def test_decimal_grain_size_is_not_truncated() -> None:
    items = _inventory(
        "\n".join(
            [
                "5 技术要求",
                "5.5 晶粒度",
                "板材的晶粒度应不低于4. 0级。",
            ]
        )
    )
    assert items["晶粒度"]["requirement"] == "板材的晶粒度应不低于4.0级。"


def test_beta_transus_process_permission_is_not_a_test_item() -> None:
    items = _inventory(
        "\n".join(
            [
                "3 技术要求",
                "3.3 热处理",
                "Unless prohibited by purchaser, bars may be solution heat treated below the beta transus prior to annealing.",
            ]
        )
    )
    assert "相变温度" not in items


def test_eddy_flow_is_not_eddy_current_test() -> None:
    items = _inventory(
        "\n".join(
            [
                "3 技术要求",
                "3.5 低倍组织",
                "模锻件的流线还应基本符合锻件的结构外形，且不应有穿流和严重的涡流。",
            ]
        )
    )
    assert "低倍" in items
    assert "涡流检测" not in items

def test_table_wrapped_clause_headings_are_recovered() -> None:
    """GLM-OCR 把“5.5 β转变温度”包进单行表格时不能丢标题。"""
    ocr = {
        "pages": [
            {
                "page_no": 1,
                "markdown": "\n".join(
                    [
                        "5 技术要求",
                        '<table border="1"><tr><td>5.4</td><td>弯曲性能</td></tr></table>',
                        "板材应进行弯曲试验,弯曲部位应无裂纹。",
                        '<table border="1"><tr><td>5.5</td><td>β</td><td>转变温度</td></tr></table>',
                        "需方要求并在订货单中注明时,板材可按熔炼炉号提供β转变温度实测值。",
                        '<table border="1"><tr><td>5.6</td><td>外观质量</td></tr></table>',
                        '<table border="1"><tr><td>5.6.1</td><td>板材应以酸洗、水磨或机加工表面供货。</td></tr></table>',
                    ]
                ),
            }
        ],
        "tables": [],
    }
    payload = extract_clauses(ocr)
    ids = {clause["clause_id"] for clause in payload["clauses"]}
    assert {"5.4", "5.5", "5.6", "5.6.1"} <= ids
    inventory = build_inventory([], payload, [], ocr)
    items = {item["feature"]: item for item in inventory["items"] if item.get("feature")}
    assert items["相变温度"]["requirement"].startswith("需方要求")
    assert items["外观"]["requirement"].startswith("板材应以酸洗")


def test_microstructure_heading_grain_size_becomes_grain_size() -> None:
    """GB 24627 的“显微结构”条款正文实际要求平均晶粒度。"""
    items = _inventory(
        "\n".join(
            [
                "9.1 显微结构",
                "根据GB/T 6394的试验方法进行检验,产品的平均晶粒度(G)应不粗于4级。",
            ]
        )
    )
    assert items["晶粒度"]["requirements"][0]["text"].startswith("根据GB/T 6394")
    assert "高倍组织" not in items


def test_grain_size_under_macro_heading_is_not_duplicated() -> None:
    """“低倍组织上的晶粒度”“显微组织中的晶粒度”只建晶粒度项。"""
    items = _inventory(
        "\n".join(
            [
                "3.8 低倍组织",
                "3.8.5 对棒材低倍组织上的晶粒度有要求时,应供需双方商定,并在订货单(或合同)中注明。",
                "3.9 显微组织",
                "3.9.3 对显微组织中的晶粒度有特殊要求时,应供需双方协商,并在订货单(或合同)中注明。",
            ]
        )
    )
    assert [row["text"] for row in items["晶粒度"]["requirements"]] == [
        "对棒材低倍组织上的晶粒度有要求时,应供需双方商定,并在订货单(或合同)中注明。",
        "对显微组织中的晶粒度有特殊要求时,应供需双方协商,并在订货单(或合同)中注明。",
    ]
    assert "低倍" not in items or not items["低倍"].get("requirements")
    assert "高倍组织" not in items or not items["高倍组织"].get("requirements")


def test_decarburization_layer_is_not_ferrite() -> None:
    items = _inventory(
        "\n".join(
            [
                "6.9 脱碳层",
                "采用金相法检验每边总脱碳层深度(铁素体+过渡层)不大于钢棒直径或厚度的1.5%。",
            ]
        )
    )
    assert "铁素体" not in items


def test_alpha_phase_measurement_step_is_not_a_requirement() -> None:
    items = _inventory(
        "\n".join(
            [
                "7.2.4 显微组织",
                "考虑到试样不同部位的微观成分波动对显微组织的影响,应在试样的中心和二分之一半径处"
                "至少观察5个视场,选择有代表性的视场测定α相含量。",
                "7.2.5 铁素体",
                "α相含量的测定可采用图片比较法、图像分析软件或计算法。",
            ]
        )
    )
    assert "铁素体" not in items or not items["铁素体"].get("requirements")
    assert "高倍组织" not in items or not items["高倍组织"].get("requirements")


def test_method_standard_cover_produces_no_qualitative_items() -> None:
    ocr = {
        "pages": [
            {
                "page_no": 1,
                "markdown": "\n".join(
                    [
                        "中华人民共和国国家标准",
                        "钛合金β转变温度测定方法",
                        "Determination of β transus temperature of titanium alloys",
                    ]
                ),
            },
            {
                "page_no": 2,
                "markdown": "\n".join(
                    [
                        "7.2.4 试样制备及检验",
                        "考虑到试样不同部位的微观成分波动对显微组织的影响,应在试样的中心和"
                        "二分之一半径处至少观察5个视场,选择有代表性的视场测定α相含量。",
                        "7.2.5 α相含量的测定可采用图片比较法、图像分析软件或计算法。",
                    ]
                ),
            },
        ],
        "tables": [],
    }
    payload = extract_clauses(ocr)
    inventory = build_inventory([], payload, [], ocr)
    features = {item["feature"] for item in inventory["items"] if item.get("feature")}
    assert "铁素体" not in features
    assert "高倍组织" not in features


def test_concession_and_certificate_rules_are_not_requirements() -> None:
    items = _inventory(
        "\n".join(
            [
                "3.8 低倍组织",
                "3.8.1 棒材的低倍试样上不准许有裂纹、缩尾、气孔存在。",
                "3.8.2 因成层、缩尾、粗晶环不合格时,允许从棒材挤压尾端切去一段重复试验,直至合格,合格者交货。",
                "6.3 质量证明书",
                "每批板材应附有质量证明书,注明: b) 产品的晶粒度检验(有要求时)",
            ]
        )
    )
    texts = [row["text"] for row in items["低倍"]["requirements"]]
    assert texts == ["棒材的低倍试样上不准许有裂纹、缩尾、气孔存在。"]
    assert "晶粒度" not in items or not items["晶粒度"].get("requirements")


def test_beta_transus_method_rationale_is_not_a_requirement() -> None:
    items = _inventory(
        "\n".join(
            [
                "8.1 相变温度",
                "由于镍-钛形状记忆合金的镍、钛含量测量的精确度不能达到保证形状记忆或超弹性能的"
                "要求,必须使用热分析法或等效的热机械试验法测量合金的相变温度,根据相变温度保证合金成分。",
                "8.3 相变温度",
                "按照YY/T 0641规定的热分析法测量相变温度时,As点的测量值允许偏差应符合表3的规定。",
            ]
        )
    )
    texts = [row["text"] for row in items["相变温度"]["requirements"]]
    assert len(texts) == 1
    assert texts[0].startswith("按照YY/T 0641")


def test_ultrasonic_method_assignment_is_not_a_requirement() -> None:
    items = _inventory(
        "\n".join(
            [
                "4.10 超声检测",
                "厚度不大于6.0 mm板材的超声检测按YS/T 1001进行,厚度大于6.0 mm板材的超声检测按GB/T 5193进行。",
            ]
        )
    )
    assert "超声波检测" not in items or not items["超声波检测"].get("requirements")


def test_acceptance_sentences_are_preferred_over_sampling_steps() -> None:
    """GB 24627 的洁净度条款先写取样截面，真正的指标在后面。"""
    items = _inventory(
        "\n".join(
            [
                "9.2 冶金微观洁净度",
                "孔隙和非金属夹杂的评价应在轧制产品5.5mm~94.0mm的截面上进行。",
                "对于As≤30℃轧制产品,孔隙和非金属夹杂颗粒的最大允许尺寸为39.0μm。",
                "放大400倍~500倍观察,在任何视野内,孔隙和非金属夹杂的面积百分比应在2.8%以下。",
            ]
        )
    )
    text = items["非金属夹杂"]["requirements"][0]["text"]
    assert "39.0μm" in text
    assert "2.8%以下" in text
    assert "应在轧制产品" not in text


def test_ocr_duplicated_criteria_sentence_is_removed() -> None:
    items = _inventory(
        "\n".join(
            [
                "3.3.3.2.1 尺寸",
                "丝材直径允许偏差应符合表9的规定。",
                "G9 丝材直径允许偏差应符合表9的规定。",
            ]
        )
    )
    text = items["尺寸"]["requirements"][0]["text"]
    assert text.count("丝材直径允许偏差") == 1


def test_gjb_ocr_comma_subclauses_are_parsed() -> None:
    """GJB OCR 把“3.5.3”写成“3.5 , 3”时不能丢掉低倍条款。"""
    markdown = "\n".join(
        [
            "3.5 低倍组织",
            "3.5 , 1 锻件流线的方向一般应沿锻件的最大外廓尺寸分布。",
            "3.5 , 3 锻件的横向酸浸低倩试片上不允许有肉眼可见的缩孔、气泡、裂纹和夹杂。",
        ]
    )
    ocr = {"pages": [{"page_no": 1, "markdown": markdown}], "tables": []}
    payload = extract_clauses(ocr)
    ids = {clause["clause_id"] for clause in payload["clauses"]}
    assert {"3.5.1", "3.5.3"} <= ids
    inventory = build_inventory([], payload, [], ocr)
    items = {item["feature"]: item for item in inventory["items"] if item.get("feature")}
    texts = [row["text"] for row in items["低倍"]["requirements"]]
    assert any(text.startswith("锻件的横向酸浸低倍试片上不允许有") for text in texts)


def test_microstructure_and_grain_size_in_same_clause_are_both_kept() -> None:
    """ISO 5832-2 的 Microstructure 条款同时要求组织均匀和晶粒度。"""
    items = _inventory(
        "\n".join(
            [
                "5 Microstructure",
                "The microscopic structure of the titanium in the annealed condition shall be uniform.",
                "The grain size, determined as specified in Clause 7, shall be no coarser than grain size No. 5.",
            ]
        )
    )
    assert items["高倍组织"]["requirements"][0]["text"].startswith(
        "The microscopic structure"
    )
    assert items["晶粒度"]["requirements"][0]["text"].startswith("The grain size")


def test_table_reference_with_dimensions_is_split_by_row() -> None:
    """牌号×厚度×晶粒度表必须逐行拆开，不能压成一句话。"""
    ocr = {
        "pages": [
            {
                "page_no": 1,
                "markdown": "\n".join(
                    [
                        "5.5 晶粒度",
                        "板材的晶粒度应符合表B.1的规定。",
                    ]
                ),
            }
        ],
        "tables": [
            {
                "table_id": "T1",
                "page_no": 1,
                "caption": "表B.1 晶粒度级别",
                "header_rows": 1,
                "header_paths": [
                    ["牌号"],
                    ["厚度mm"],
                    ["晶粒度级别"],
                ],
                "n_cols": 3,
                "rows": [
                    ["牌号", "厚度mm", "晶粒度级别"],
                    ["Q355B", "≤16", "≥5级"],
                    ["Q355B", ">16~40", "≥4级"],
                ],
                "units": [],
            }
        ],
    }
    payload = extract_clauses(ocr)
    inventory = build_inventory([], payload, [], ocr)
    item = next(
        entry for entry in inventory["items"] if entry.get("feature") == "晶粒度"
    )
    texts = [row["text"] for row in item["requirements"]]
    assert len(texts) == 2
    assert all("表B.1" in text for text in texts)
    assert "厚度mm=≤16" in texts[0]
    assert "厚度mm=>16~40" in texts[1]


def test_simple_inclusion_table_is_merged_into_one_sentence() -> None:
    """非金属夹杂这类简单级别表适合合并成一句话。"""
    ocr = {
        "pages": [
            {
                "page_no": 1,
                "markdown": "\n".join(
                    [
                        "5.6 非金属夹杂物",
                        "非金属夹杂物应符合表5的规定。",
                    ]
                ),
            }
        ],
        "tables": [
            {
                "table_id": "T5",
                "page_no": 1,
                "caption": "表5 非金属夹杂物级别",
                "header_rows": 1,
                "header_paths": [["类别"], ["要求"]],
                "n_cols": 2,
                "rows": [
                    ["类别", "要求"],
                    ["A类", "≤2.0级"],
                    ["B类", "≤1.5级"],
                ],
                "units": [],
            }
        ],
    }
    payload = extract_clauses(ocr)
    inventory = build_inventory([], payload, [], ocr)
    item = next(
        entry for entry in inventory["items"] if entry.get("feature") == "非金属夹杂"
    )
    requirement = item["requirements"][0]["text"]
    assert "表5" in requirement
    assert "A类" in requirement
    assert "B类" in requirement


def test_single_column_table_prose_is_restored() -> None:
    """XX454 把整段低倍/显微组织要求包进了单列表格，不能丢。"""
    ocr = {
        "pages": [
            {
                "page_no": 1,
                "markdown": "\n".join(
                    [
                        "3.6 低倍组织",
                        '<table border="1"><tr><td></td><td></td></tr>'
                        "<tr><td>型材的低倍组织中不允许有裂纹、疏松、成层和缩尾。</td><td></td></tr></table>",
                        "3.7 显微组织",
                        '<table border="1"><tr><td>型材的显微组织不允许有过烧；晶粒度级别指数应不小于4级。</td></tr></table>',
                    ]
                ),
            }
        ],
        "tables": [],
    }
    payload = extract_clauses(ocr)
    clauses = {item["clause_id"]: item for item in payload["clauses"]}
    assert "低倍组织中不允许有裂纹" in clauses["3.6"]["text"]
    assert "不允许有过烧" in clauses["3.7"]["text"]
    inventory = build_inventory([], payload, [], ocr)
    items = {item["feature"]: item for item in inventory["items"] if item.get("feature")}
    assert items["低倍"]["requirements"][0]["text"].startswith("型材的低倍组织")
    assert items["高倍组织"]["requirements"][0]["text"].startswith("型材的显微组织")


def test_qualitative_records_inherit_single_document_grade() -> None:
    ocr = {
        "pages": [
            {
                "page_no": 1,
                "markdown": "\n".join(
                    [
                        "9.1 晶粒度",
                        "产品的平均晶粒度不应粗于4级。",
                    ]
                ),
            }
        ],
        "tables": [],
    }
    records = [
        {
            "record_id": "T1-R1",
            "table_id": "T1",
            "page_no": 1,
            "row_index": 0,
            "profile": "mechanical_properties",
            "grade": "NiTi",
            "conditions": {},
            "properties": {"Rm": {"value": 900, "raw": "900", "unit": "MPa"}},
        }
    ]
    apply_document_intelligence(records, [], ocr, [])
    qualitative = [item for item in records if item["profile"] == "qualitative"]
    assert qualitative
    assert all(item["grade"] == "NiTi" for item in qualitative)


def test_heat_treatment_categories_come_from_dictionary_and_split() -> None:
    table = {
        "table_id": "TH1",
        "page_no": 1,
        "caption": "室温拉伸和高温拉伸热处理制度",
        "header_rows": 1,
        "header_paths": [["牌号"], ["室温拉伸"], ["高温拉伸"]],
        "n_cols": 3,
        "rows": [
            ["牌号", "室温拉伸", "高温拉伸"],
            ["GH4169", "950℃±10℃，1h，空冷", "720℃±10℃，8h，空冷"],
        ],
        "column_units": ["", "", ""],
        "column_conditions": ["", "", ""],
        "column_elements": ["", "", ""],
    }
    records, _evidence, _summary = builtin.parse_table(
        table, {"profile": "heat_treatment"}, None, []
    )
    assert [record["conditions"]["项目大类"] for record in records] == [
        "室温拉伸",
        "高温拉伸",
    ]
    assert all("、" not in record["conditions"]["项目大类"] for record in records)


def test_minimum_caption_sets_operator_for_tensile_table() -> None:
    table = {
        "table_id": "TM1",
        "page_no": 5,
        "caption": None,
        "context": "Table 2A - Minimum room temperature tensile properties\n",
        "header_rows": 1,
        "header_paths": [
            ["Specimen Orientation"],
            ["Tensile Strength ksi"],
            ["Elongation %"],
        ],
        "n_cols": 3,
        "rows": [
            ["Specimen Orientation", "Tensile Strength ksi", "Elongation %"],
            ["Longitudinal", "185", "12"],
        ],
        "column_units": ["", "ksi", "%"],
        "column_conditions": ["方向", "", ""],
        "column_elements": ["", "", ""],
    }
    records, _evidence, _summary = builtin.parse_table(
        table,
        {
            "profile": "mechanical_properties",
            "bindings": {"measures": {"Rm": {}, "A": {}}},
        },
        None,
        [],
    )
    assert records
    assert records[0]["properties"]["Rm"]["operator"] == "≥"
    assert records[0]["properties"]["A"]["operator"] == "≥"


def test_merged_element_header_is_split_for_astm_composition() -> None:
    """B348 Table 1 merges "Nickel Molybdenum" but data keeps both columns."""
    table = {
        "table_id": "T1",
        "page_no": 3,
        "caption": None,
        "header_rows": 1,
        "header_paths": [
            [""],
            ["Grade"],
            ["UNS Number"],
            ["Carbon max."],
            ["Oxygen range or max."],
            ["Nitrogen max."],
            ["Hydrogen max."],
            ["Iron range or max."],
            ["Aluminum"],
            ["Vanadium"],
            ["Nickel Molybdenum"],
            ["Other Elements, Elements, max. each"],
            ["Other Elements, Elements, max. total"],
        ],
        "n_cols": 13,
        "rows": [
            [
                "",
                "Grade",
                "UNS Number",
                "Carbon max.",
                "Oxygen range or max.",
                "Nitrogen max.",
                "Hydrogen max.",
                "Iron range or max.",
                "Aluminum",
                "Vanadium",
                "Nickel Molybdenum",
                "Other Elements, Elements, max. each",
                "Other Elements, Elements, max. total",
            ],
            [
                "1",
                "R50250",
                "0.08",
                "0.18",
                "0.03",
                "0.015",
                "0.20",
                "--",
                "--",
                "--",
                "--",
                "0.1",
                "0.4",
            ],
        ],
        "column_units": [""] * 13,
        "column_conditions": [""] * 13,
        "column_elements": [""] * 13,
    }
    records, _evidence, _summary = builtin.parse_table(
        table,
        {
            "profile": "chemical_composition",
            "bindings": {
                "measures": {
                    "C": {},
                    "O": {},
                    "N": {},
                    "H": {},
                    "Fe": {},
                    "其他元素（单一）": {"aliases": ["otherelements"]},
                    "其他元素（总和）": {"aliases": ["otherelements"]},
                }
            },
        },
        None,
        [],
    )
    assert records
    properties = records[0]["properties"]
    assert properties["C"]["raw"] == "0.08"
    assert properties["Fe"]["raw"] == "0.20"
    assert properties["其他元素（单一）"]["value"] == 0.1
    assert properties["其他元素（单一）"]["operator"] == "≤"
    assert properties["其他元素（总和）"]["value"] == 0.4


def test_proof_stress_and_shear_strength_aliases() -> None:
    table = {
        "table_id": "T22",
        "page_no": 3,
        "caption": None,
        "header_rows": 1,
        "header_paths": [
            ["牌号"],
            ["规定残余伸长应力σr0.2MPa"],
            ["剪切强度tauMPa"],
        ],
        "n_cols": 3,
        "rows": [
            ["牌号", "规定残余伸长应力σr0.2MPa", "剪切强度tauMPa"],
            ["TC4", "1000", "665"],
        ],
        "column_units": ["", "MPa", "MPa"],
        "column_conditions": ["", "", ""],
        "column_elements": ["", "", ""],
    }
    records, _evidence, _summary = builtin.parse_table(
        table,
        {
            "profile": "mechanical_properties",
            "bindings": {"measures": {"Rp0.2": {"unit": "MPa"}, "剪切强度": {"unit": "MPa"}}},
        },
        None,
        [],
    )
    assert records
    properties = records[0]["properties"]
    assert properties["Rp0.2"]["raw"] == "1000"
    assert properties["剪切强度"]["raw"] == "665"
    assert "持久应力" not in properties


def test_duplicate_merged_header_is_dropped_before_parsing() -> None:
    headers = [
        "序号",
        "牌号",
        "状态",
        "检验制度",
        "检验制度",
        "检验制度",
        "检验制度",
        "取样方向",
        "RmMPa",
        "Rp0.2MPa",
        "A%",
        "Z%",
        "KU2J",
        "K1C",
        "HRC",
        "",
        "",
    ]
    data = [
        [
            "1",
            "0Cr12Mn5Ni4Mo3Al",
            "RH520",
            "1050℃",
            "-78℃",
            "520℃",
            "纵向",
            "1570",
            "1400",
            "10",
            "45",
            "39",
            "-",
            "≥48",
            "",
            "",
        ]
    ]
    meta = (
        [""] * 17,
        ["", "", "状态", "状态", "状态", "状态", "状态", "方向", "", "", "", "", "", "", "", "", ""],
        ["", "", "", "", "", "", "", "", "", "", "", "", "K", "", "", "", ""],
    )
    repaired, repaired_data, _meta = builtin._repair_shifted_header(headers, data, meta)
    assert repaired.index("取样方向") == 6
    assert repaired[7] == "RmMPa"
    assert repaired_data[0][6] == "纵向"


def test_english_requirement_is_translated_to_chinese() -> None:
    from services.sandbox.runtime.translate import translate_requirement

    translated = translate_requirement(
        "The grain size, determined as specified in Clause 7, "
        "shall be no coarser than grain size No. 5."
    )
    assert translated == "按第7章规定测定的晶粒度不应粗于5级。"
    assert translate_requirement("板材的晶粒度应不低于4级。") == "板材的晶粒度应不低于4级。"


def test_table_reference_with_budiyu_is_merged_and_trailing_kou_removed() -> None:
    ocr = {
        "pages": [
            {
                "page_no": 1,
                "markdown": "\n".join(
                    [
                        "3.5.3 锻件的低倍组织应不低于表8 的要求口",
                    ]
                ),
            }
        ],
        "tables": [
            {
                "table_id": "T8",
                "page_no": 1,
                "caption": "表8 低倍组织缺陷允许级别",
                "header_rows": 2,
                "header_paths": [
                    ["序号"],
                    ["牌号"],
                    ["缺陷类型", "暗斑"],
                    ["缺陷类型", "白斑"],
                ],
                "n_cols": 4,
                "rows": [
                    ["序号", "牌号", "缺陷类型", "缺陷类型"],
                    ["序号", "牌号", "暗斑", "白斑"],
                    ["1", "0Cr12Mn5Ni4Mo3Al", "B", "B"],
                ],
                "units": [],
            }
        ],
    }
    payload = extract_clauses(ocr)
    inventory = build_inventory([], payload, [], ocr)
    item = next(entry for entry in inventory["items"] if entry.get("feature") == "低倍")
    text = item["requirements"][0]["text"]
    assert "口" not in text
    assert "0Cr12Mn5Ni4Mo3Al" in text
    assert "暗斑=B" in text


def test_microstructure_evaluation_does_not_duplicate_grain_size() -> None:
    items = _inventory(
        "\n".join(
            [
                "9.1 显微结构",
                (
                    "在热加工态或退火态评价显微组织,产品的截面尺寸应介于5.5mm~94.0mm。"
                    "按照GB/T 6394的试验方法进行检验,产品的平均晶粒度不应粗于4级。"
                ),
            ]
        )
    )
    assert "晶粒度" in items
    assert "高倍组织" not in items


def test_missing_leading_category_cell_is_restored() -> None:
    headers = ["组织类型", "序号", "统一数字代号", "牌号", "Rm", "Rp0.2", "A"]
    previous = ["奥氏体", "23", "S34778", "06Cr18Ni11Nb", "520", "205", "35"]
    row = ["24", "S34779", "07Cr18Ni11Nb", "520", "520", "205", "35", ""]
    repaired = builtin._repair_row_missing_leading(row, previous, headers)
    assert repaired[0] == "奥氏体"
    assert repaired[1] == "24"
    assert repaired[3] == "07Cr18Ni11Nb"




def test_english_max_min_marks_become_operators() -> None:
    from services.sandbox.runtime.projection import _normalize_value_marks

    records = [{"properties": {
        "H": {"raw": "2 ppm max.", "value": 2.0, "operator": None, "unit": "%"},
        "Rm": {"raw": "800 Min.", "value": 800.0, "operator": None, "unit": "MPa"},
    }}]
    _normalize_value_marks(records)
    props = records[0]["properties"]
    assert (props["H"]["raw"], props["H"]["unit"], props["Rm"]["raw"]) == ("≤2", "ppm", "≥800")
