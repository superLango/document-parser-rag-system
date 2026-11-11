from metal_doc_agent.contracts import Page
from metal_doc_agent.method_binding import (
    extract_document_methods,
    fill_projected_methods,
)


def test_broken_standard_number_from_ocr_is_repaired() -> None:
    pages = [
        Page(
            page_no=17,
            markdown=(
                "## 3 试验方法\n"
                "1 拉伸试验应按GB/T228.\n1的规定进行。\n"
                "2 冲击试验按GB/T229的规定进行。\n"
                "按GB/T231.\n1规定的方法对锻件进行布氏硬度检验。\n"
            ),
        )
    ]
    methods = extract_document_methods(pages)
    assert methods["室温拉伸"]["method"] == "GB/T 228.1"
    assert methods["夏比冲击"]["method"] == "GB/T 229"
    assert methods["布氏硬度"]["method"] == "GB/T 231.1"


def test_chemical_analysis_reference_is_not_treated_as_test_method() -> None:
    pages = [
        Page(
            page_no=14,
            markdown="化学成分分析应按GB/T223规定的方法进行。\n",
        )
    ]
    assert extract_document_methods(pages) == {}


def test_only_empty_method_cells_are_filled() -> None:
    pages = [
        Page(
            page_no=17,
            markdown="冲击试验按GB/T229的规定进行。\n",
        )
    ]
    payload = {
        "categories": [
            {
                "feature": "夏比冲击",
                "records": [
                    {"项目名称": "冲击吸收功 KV2", "试验方法": ""},
                    {"项目名称": "冲击吸收功 KV2", "试验方法": "GB/T 229-2020"},
                ],
            },
            {
                "feature": "晶粒度",
                "records": [{"项目名称": "晶粒度", "试验方法": ""}],
            },
        ]
    }
    result = fill_projected_methods(payload, pages)
    rows = payload["categories"][0]["records"]
    assert rows[0]["试验方法"] == "GB/T 229"
    assert rows[1]["试验方法"] == "GB/T 229-2020"
    assert payload["categories"][1]["records"][0]["试验方法"] == ""
    assert result["updated"] == 1


def test_normative_reference_list_supplies_method() -> None:
    pages = [
        Page(
            page_no=4,
            markdown=(
                "GB/T229 金属材料 夏比摆锤冲击试验方法(GB/T229—2007,ISO148-1:2006,MOD)\n"
            ),
        )
    ]
    methods = extract_document_methods(pages)
    assert methods["夏比冲击"]["method"].startswith("GB/T 229")


def test_reference_list_yields_one_method_per_family() -> None:
    pages = [
        Page(
            page_no=5,
            markdown=(
                "GB/T 228 金属拉伸试验方法\n"
                "GB/T 2039 金属拉伸蠕变及持久试验方法\n"
                "GB/T 231.1 金属布氏硬度试验方法 第1部分：试验方法\n"
                "GB/T 4338 金属材料高温拉伸试验方法\n"
                "GB/T 14999.2 高温合金横向低倍组织酸浸试验法\n"
                "GB/T 6394 金属平均晶粒度测定方法\n"
                "GB/T 4162 锻轧钢棒超声波检验方法\n"
            ),
        )
    ]
    methods = extract_document_methods(pages)
    assert methods["室温拉伸"]["method"] == "GB/T 228"
    assert methods["高温拉伸"]["method"] == "GB/T 4338"
    assert methods["持久"]["method"] == "GB/T 2039"
    assert methods["布氏硬度"]["method"] == "GB/T 231.1"
    assert methods["低倍"]["method"] == "GB/T 14999.2"
    assert methods["晶粒度"]["method"] == "GB/T 6394"
    assert methods["超声波检测"]["method"] == "GB/T 4162"


def test_persistence_reference_is_not_mapped_to_room_tensile() -> None:
    pages = [
        Page(
            page_no=5,
            markdown="GB/T 2039 金属拉伸蠕变及持久试验方法\n",
        )
    ]
    methods = extract_document_methods(pages)
    assert methods["持久"]["method"] == "GB/T 2039"
    assert "室温拉伸" not in methods


def test_high_temperature_rows_are_corrected_to_specific_method() -> None:
    pages = [
        Page(
            page_no=5,
            markdown=(
                "GB/T 228 金属拉伸试验方法\n"
                "GB/T 4338 金属材料高温拉伸试验方法\n"
            ),
        )
    ]
    payload = {
        "categories": [
            {
                "feature": "高温拉伸",
                "records": [
                    {"项目名称": "抗拉强度", "试验方法": "GB/T 228"},
                    {"项目名称": "断面收缩率", "试验方法": ""},
                ],
            }
        ]
    }
    result = fill_projected_methods(payload, pages)
    rows = payload["categories"][0]["records"]
    assert [row["试验方法"] for row in rows] == ["GB/T 4338", "GB/T 4338"]
    assert result["corrected"] == {"高温拉伸": 1}
    assert result["filled"] == {"高温拉伸": 1}

