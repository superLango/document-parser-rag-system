from metal_doc_agent.schema_projection import (
    _augment_requirements_with_tables,
    _fill_missing_grades,
)


def test_missing_grades_are_forward_and_back_filled() -> None:
    categories = [
        {
            "feature": "化学成分",
            "records": [
                {"材料牌号": "", "项目名称": "C"},
                {"材料牌号": "06Cr19Ni10", "项目名称": "Mn"},
                {"材料牌号": "", "项目名称": "Si"},
            ],
        },
        {
            "feature": "室温拉伸",
            "records": [
                {"材料牌号": "", "项目名称": "抗拉强度 Rm"},
                {"材料牌号": "", "项目名称": "断后伸长率A"},
            ],
        },
    ]
    _fill_missing_grades(categories)
    chemical = categories[0]["records"]
    tensile = categories[1]["records"]
    assert [row["材料牌号"] for row in chemical] == ["06Cr19Ni10"] * 3
    assert [row["材料牌号"] for row in tensile] == ["06Cr19Ni10"] * 2


def test_bogus_grade_falls_back_to_all_grades() -> None:
    categories = [
        {
            "feature": "化学成分",
            "records": [
                {"材料牌号": "", "项目名称": "C"},
                {"材料牌号": "要求值", "项目名称": "Mn"},
            ],
        }
    ]
    _fill_missing_grades(categories)
    assert [row["材料牌号"] for row in categories[0]["records"]] == ["全部牌号", "全部牌号"]


def test_table_inline_is_capped_and_kept_in_expansions() -> None:
    table = {
        "table_id": "T2",
        "caption": "表1 化学成分",
        "header_rows": 1,
        "rows": [["牌号", "C", "Mn"]]
        + [[f"G{index}", "0.10", "0.50"] for index in range(30)],
    }
    groups = {
        "化学成分": [
            {
                "项目名称": "C",
                "材料牌号": "全部牌号",
                "标准要求": "应符合表1的规定",
            }
        ]
    }
    expansions = _augment_requirements_with_tables(groups, {"T2": table})
    requirement = groups["化学成分"][0]["标准要求"]
    assert len(requirement) <= 300
    assert requirement.startswith("应符合表1的规定")
    assert expansions
    assert expansions[0]["table"] == "表1 化学成分"
    assert "G29" in expansions[0]["text"]
