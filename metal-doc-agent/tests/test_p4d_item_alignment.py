from pathlib import Path

from metal_doc_agent.canonicalize.align import align_inventory
from metal_doc_agent.canonicalize.dictionary import DictionaryIndex, JsonDictionaryAdapter
from metal_doc_agent.contracts import (
    ClauseRecord,
    ExtractedValue,
    InspectionItem,
    ItemInventory,
    ItemInventoryEntry,
    TableGrid,
)
from metal_doc_agent.items.discover import _inspection_table_items
from metal_doc_agent.schema_projection import (
    _hanson_item_categories,
    _method_from_citation,
)

ROOT = Path(__file__).resolve().parents[1]


def _index() -> DictionaryIndex:
    snapshot = ROOT / "configs" / "business_dictionary.hanson.json"
    override = ROOT / "configs" / "business_dictionary.local.json"
    return DictionaryIndex.build(JsonDictionaryAdapter(snapshot, override).load())


def _entry(raw: str, family: str, **kwargs) -> ItemInventoryEntry:
    return ItemInventoryEntry(
        item_raw=raw,
        item_canonical=raw,
        item_family=family,
        evidence=[f"T22:1:{raw}"],
        status="confirmed",
        **kwargs,
    )


def test_corrosion_mechanisms_keep_their_own_category() -> None:
    inventory = ItemInventory(
        doc_id="gbt6892",
        items=[
            _entry("应力腐蚀性能", "corrosion"),
            _entry("剥落腐蚀性能", "corrosion"),
            _entry("晶间腐蚀", "corrosion"),
            _entry("耐盐雾腐蚀性", "corrosion"),
            _entry("耐冲击性", "impact", facets={"impact_type": "夏比"}),
        ],
    )
    aligned, _ = align_inventory(inventory, _index(), category_mode="strict")
    by_raw = {entry.item_raw: entry for entry in aligned.items}

    assert by_raw["应力腐蚀性能"].business_name == "应力腐蚀"
    assert by_raw["剥落腐蚀性能"].business_name == "剥落腐蚀"
    assert by_raw["晶间腐蚀"].business_name == "晶间腐蚀"
    # 膜层指标不能借用金属材料大类，严格模式下应保持不适用。
    assert by_raw["耐盐雾腐蚀性"].status == "not_applicable"
    assert by_raw["耐冲击性"].status == "not_applicable"


def test_film_performance_catalog_is_not_an_item_source() -> None:
    headers = [
        ["表面处理类别"],
        ["出厂必检项目"],
        ["供方定期检验项目"],
        ["特殊要求检验项目"],
    ]
    grid = TableGrid(
        table_id="T21",
        page_no=23,
        caption="表10 （续）",
        n_rows=2,
        n_cols=4,
        header_rows=1,
        rows=[
            ["表面处理类别", "出厂必检项目", "供方定期检验项目", "特殊要求检验项目"],
            [
                "液体喷涂",
                "膜厚、颜色及色差、耐沸水性",
                "耐盐雾腐蚀性、耐盐酸性、耐冲击性",
                "耐碱性、耐候性",
            ],
        ],
        header_paths=headers,
        profile="inspection",
    )
    assert _inspection_table_items(grid, None, []) == []


def test_sampling_table_still_yields_corrosion_items() -> None:
    headers = [
        ["检验项目"],
        ["取样规定"],
        ["要求的章条号"],
        ["试验方法的章条号"],
    ]
    grid = TableGrid(
        table_id="T22",
        page_no=24,
        caption="表11 型材的取样规定",
        n_rows=2,
        n_cols=4,
        header_rows=1,
        rows=[
            ["检验项目", "取样规定", "要求的章条号", "试验方法的章条号"],
            ["应力腐蚀性能", "每批抽取1根", "3.8", "4.7"],
        ],
        header_paths=headers,
        profile="inspection",
    )
    entries = _inspection_table_items(grid, None, [])
    assert [entry.item_raw for entry in entries] == ["应力腐蚀性能"]


def _tables() -> dict:
    return {
        "T11": {
            "table_id": "T11",
            "caption": "表6 应力腐蚀性能",
            "profile": "inspection",
            "header_rows": 1,
            "header_paths": [
                ["牌号"],
                ["状态"],
                ["壁厚a/mm"],
                ["试样受力方向"],
                ["试验应力/MPa"],
                ["试验时间/d"],
                ["结果要求"],
            ],
            "rows": [
                ["牌号", "状态", "壁厚a/mm", "试样受力方向", "试验应力/MPa", "试验时间/d", "结果要求"],
                ["7075", "T73", "≥20", "高向", "170", "≥20", "不出现裂纹"],
            ],
        }
    }


def _corrosion_item(raw: str, category: str) -> ItemInventoryEntry:
    return ItemInventoryEntry(
        item_raw=raw,
        item_canonical=category,
        item_family="corrosion",
        business_name=category,
        business_category_name=category,
        evidence=[f"T22:6:{raw}"],
        status="confirmed",
    )


def test_stress_corrosion_verdict_outranks_table_reference() -> None:
    inventory = ItemInventory(
        doc_id="gbt6892",
        items=[_corrosion_item("应力腐蚀性能", "应力腐蚀")],
    )
    inspections = [InspectionItem(item="应力腐蚀性能", requirement_clause="3.8")]
    clauses = [
        ClauseRecord(
            clause_id="3.8",
            title="应力腐蚀性能",
            fields={
                "requirement": ExtractedValue(
                    raw="型材的应力腐蚀性能应符合表6的规定。",
                    text="型材的应力腐蚀性能应符合表6的规定。",
                    comparator="text",
                )
            },
        )
    ]
    categories, _ = _hanson_item_categories(
        inventory,
        [],
        inspections,
        [],
        clauses,
        _tables(),
        index=None,
        standard_name="GBT 6892-2015 一般工业用铝及铝合金挤压型材",
        qualitative={},
    )
    stress = next(row for row in categories if row["feature"] == "应力腐蚀")
    assert stress["records"][0]["标准要求"] == "不出现裂纹"


def test_exfoliation_corrosion_keeps_clause_verdict() -> None:
    inventory = ItemInventory(
        doc_id="gbt6892",
        items=[_corrosion_item("剥落腐蚀性能", "剥落腐蚀")],
    )
    inspections = [InspectionItem(item="剥落腐蚀性能", requirement_clause="3.9")]
    text = (
        "订货单（或合同）中注明检验剥落腐蚀性能的7075、7178合金的T76状态型材，"
        "经剥落腐蚀试验时，型材不应出现EB~ED级的剥落腐蚀。"
    )
    clauses = [
        ClauseRecord(
            clause_id="3.9",
            title="剥落腐蚀性能",
            fields={
                "requirement": ExtractedValue(
                    raw=text, text=text, comparator="text"
                )
            },
        )
    ]
    categories, _ = _hanson_item_categories(
        inventory,
        [],
        inspections,
        [],
        clauses,
        _tables(),
        index=None,
        standard_name="GBT 6892-2015 一般工业用铝及铝合金挤压型材",
        qualitative={},
    )
    exfoliation = next(row for row in categories if row["feature"] == "剥落腐蚀")
    requirement = exfoliation["records"][0]["标准要求"]
    assert "不应出现EB~ED级的剥落腐蚀" in requirement


def test_method_citation_falls_back_to_child_clauses() -> None:
    parent = ClauseRecord(clause_id="4.7", title="应力腐蚀性能")
    first = ClauseRecord(
        clause_id="4.7.1",
        fields={
            "method_standard": ExtractedValue(
                raw="GB/T22640", text="GB/T22640", comparator="text"
            )
        },
    )
    second = ClauseRecord(
        clause_id="4.7.2",
        fields={
            "method_standard": ExtractedValue(
                raw="GB/T15970.7", text="GB/T15970.7", comparator="text"
            )
        },
    )
    assert (
        _method_from_citation("4.7", [parent, first, second])
        == "GB/T22640、GB/T15970.7"
    )
