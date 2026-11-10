"""Build the three-document mini golden set (goldset/v0/docs).

Labels are transcribed from the OCR markdown tables and clause text. They are
serialization helpers, not model output: every value carries a cell or clause
locator. Domain review upgrades ``annotation.status`` from draft to verified.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.goldset import (  # noqa: E402
    AnnotationMeta,
    GoldClassificationItem,
    GoldClause,
    GoldDocument,
    GoldEvidence,
    GoldInspectionItem,
    GoldRecord,
    GoldTable,
    GoldValue,
)

OUT_DIR = ROOT / "goldset" / "v0" / "docs"


def ev(page: int, quote: str, table: str | None = None, row: int | None = None, col: int | None = None, clause: str | None = None) -> GoldEvidence:
    return GoldEvidence(
        page_no=page,
        table_id=table,
        row=row,
        col=col,
        clause_id=clause,
        quote=quote,
    )


def value(
    raw: str,
    evidence: GoldEvidence,
    comparator: str = "eq",
    *,
    number: float | None = None,
    lower: float | None = None,
    upper: float | None = None,
    text: str | None = None,
    unit: str | None = None,
    condition: str | None = None,
) -> GoldValue:
    return GoldValue(
        raw=raw,
        value=number,
        text=text,
        unit=unit,
        comparator=comparator,
        lower=lower,
        upper=upper,
        condition=condition,
        evidence=evidence,
    )


def numeric(raw: str, unit: str, evidence: GoldEvidence, comparator: str = "max") -> GoldValue:
    compact = raw.replace("≤", "").replace("≥", "").replace(" ", "").replace("%", "")
    if "~" in compact or "～" in compact:
        lower, upper = compact.replace("～", "~").split("~")
        return value(raw, evidence, "range", lower=float(lower), upper=float(upper), unit=unit)
    symbol = raw.strip()[:1]
    kind = "max" if symbol == "≤" else "min" if symbol == "≥" else comparator
    return value(raw, evidence, kind, number=float(compact), unit=unit)


def textv(raw: str, unit: str | None, evidence: GoldEvidence) -> GoldValue:
    return value(raw, evidence, "text", text=raw, unit=unit)


# --------------------------------------------------------------------------
# Q/Du 302-2015
# --------------------------------------------------------------------------


def build_qdu302() -> GoldDocument:
    page = 5
    mechanical_rows = [
        (2, "切向", ["430", "350", "10", "120", "提供实测数据"]),
        (3, "径向", ["400", "315", "4", "120", "提供实测数据"]),
        (4, "轴向", ["390", "300", "4", "120", "提供实测数据"]),
    ]
    records = []
    for row, direction, cells in mechanical_rows:
        condition = f"T6或T651或T652 / {direction}"
        records.append(
            GoldRecord(
                record_id=f"qdu302-T2-2A14-{direction}",
                grade="2A14",
                condition=condition,
                facets={"heat_treatment": "T6或T651或T652", "direction": direction},
                properties={
                    "Rm": numeric(cells[0], "MPa", ev(page, cells[0], "T2", row, 3), "min"),
                    "Rp0.2": numeric(cells[1], "MPa", ev(page, cells[1], "T2", row, 4), "min"),
                    "A": numeric(cells[2], "%", ev(page, cells[2], "T2", row, 5), "min"),
                    "HB": numeric(cells[3], "HB", ev(page, cells[3], "T2", row, 6), "min"),
                    "E": textv(cells[4], "GPa", ev(page, cells[4], "T2", row, 7)),
                },
            )
        )

    inspection = [
        ("硬度", "逐件", "逐件", "逐件", "轧制锻件本体", "4.5", "5.2.6.1"),
        ("力学性能", "逐件", "每批抽2件", "-", "轧制锻件本体", "4.5", "5.2.6.2"),
        ("显微组织", "每热处理炉批抽1件", "每热处理炉批抽1件", "每热处理炉批抽1件", "轧制锻件本体", "4.6", "5.2.6.3"),
        ("低倍组织", "每批抽1件", "每批抽1件", "-", "轧制锻件本体", "4.7", "5.2.6.4"),
        ("超声波检测", "逐件", "逐件", "逐件", "轧制锻件本体", "4.8", "5.2.6.5"),
        ("形状和尺寸", "逐件", "逐件", "逐件", "轧制锻件本体", "4.4.2", "5.2.6.6"),
        ("表面质量", "逐件", "逐件", "逐件", "轧制锻件本体", "4.9", "5.2.6.7"),
    ]
    inspection_items = [
        GoldInspectionItem(
            item=item,
            quantities={"Ⅰ类": one, "Ⅱ类": two, "Ⅲ类": three},
            sample_location=location,
            requirement_clause=requirement,
            method_clause=method,
            evidence=ev(6, item, "T3", row, 0),
        )
        for row, (item, one, two, three, location, requirement, method) in enumerate(
            inspection, start=2
        )
    ]

    classification = [
        ("2A14", "LD10", "T6", "CS", "固溶处理加工时效", 2),
        ("2A14", "LD10", "T651", "CYS", "固溶处理加冷变形加工时效", 3),
        ("2A14", "LD10", "T652", "CYS", "固溶处理加冷变形加工时效", 4),
    ]
    classification_items = [
        GoldClassificationItem(
            grade=grade,
            old_grade=old_grade,
            state=state,
            old_state=old_state,
            meaning=meaning,
            evidence=ev(4, state, "T1", row, 2),
        )
        for grade, old_grade, state, old_state, meaning, row in classification
    ]

    clauses = [
        GoldClause(
            clause_id="4.2.2",
            title="毛坯材料氢含量",
            page_no=4,
            kind="technical_requirement",
            fields={
                "hydrogen_content": value(
                    "不大于 0.18ml/100g",
                    ev(4, "氢含量应不大于 0.18ml / 100g", clause="4.2.2"),
                    "max",
                    number=0.18,
                    unit="ml/100g",
                )
            },
            evidence=ev(4, "氢含量应不大于 0.18ml / 100g", clause="4.2.2"),
        ),
        GoldClause(
            clause_id="4.4.1",
            title="热处理状态",
            page_no=4,
            kind="delivery",
            fields={
                "requirement": textv(
                    "轧制锻件的热处理状态应符合表1的规定。当需以其他热处理状态供应时，由订货方与承制方双方商定，并在专用文件中注明。",
                    None,
                    ev(4, "轧制锻件的热处理状态应符合表1的规定。", clause="4.4.1"),
                )
            },
            applies_to=["2A14"],
            evidence=ev(4, "轧制锻件的热处理状态应符合表1的规定。", clause="4.4.1"),
        ),
        GoldClause(
            clause_id="4.8.3",
            title="超声波检测级别",
            page_no=5,
            kind="technical_requirement",
            fields={
                "acceptance_level": textv(
                    "GB/T6519 中规定的A级标准",
                    None,
                    ev(5, "轧制锻件超声波检测应符合GB/T6519中规定的A级标准。", clause="4.8.3"),
                )
            },
            evidence=ev(5, "轧制锻件超声波检测应符合GB/T6519中规定的A级标准。", clause="4.8.3"),
        ),
        GoldClause(
            clause_id="5.2.3.2.1",
            title="力学性能取样数量",
            page_no=6,
            kind="sampling",
            fields={
                "sample_quantity_I": textv(
                    "每批逐件取样；上端面圆周3个位置分别取切向、径向、轴向试样，共9个；复验9个；归档9个",
                    None,
                    ev(6, "在上端面圆周上均匀分布的3", clause="5.2.3.2.1"),
                ),
                "sample_quantity_II": textv(
                    "每批随机抽两件，取样方式和数量同I类件",
                    None,
                    ev(6, "II类件应每批随机抽两件检查力学性能，取样方式和数量同I类件。", clause="5.2.3.2.1"),
                ),
                "sample_quantity_III": textv(
                    "不做力学性能检查",
                    None,
                    ev(6, "Ⅲ类件不做力学性能检查。", clause="5.2.3.2.1"),
                ),
            },
            applies_to=["2A14"],
            evidence=ev(6, "II类件应每批随机抽两件检查力学性能，取样方式和数量同I类件。", clause="5.2.3.2.1"),
        ),
        GoldClause(
            clause_id="5.2.3.4.1",
            title="低倍组织取样",
            page_no=7,
            kind="sampling",
            fields={
                "sample_location": textv(
                    "轧制锻件本体的上端面圆周上",
                    None,
                    ev(7, "在轧制锻件本体的上端面圆周上切取1个试样。", clause="5.2.3.4.1"),
                ),
                "sample_quantity": textv(
                    "1个",
                    None,
                    ev(7, "在轧制锻件本体的上端面圆周上切取1个试样。", clause="5.2.3.4.1"),
                ),
            },
            evidence=ev(7, "在轧制锻件本体的上端面圆周上切取1个试样。", clause="5.2.3.4.1"),
        ),
    ]

    return GoldDocument(
        doc_id="qdu302_2015",
        standard_no="Q/Du 302-2015",
        title="舱段用铝合金锥/筒形轧制锻件技术条件",
        doc_type="enterprise",
        material="2A14铝合金",
        product_form="锥/筒形轧制锻件",
        source_type="scanned",
        annotation=AnnotationMeta(
            status="draft",
            annotator="agent-draft",
            updated_at="2026-10-25",
            notes=[
                "标注依据 OCR Markdown；PDF 为扫描件，未做页图目视复核。",
                "表2 的比较符为『不小于』，值按 min 标注。",
            ],
        ),
        tables=[
            GoldTable(
                table_id="T1",
                page_no=4,
                caption="表1 轧制锻件的热处理状态",
                profile="classification",
                scope="full",
                classification_items=classification_items,
            ),
            GoldTable(
                table_id="T2",
                page_no=5,
                caption="表2 轧制锻件室温力学性能",
                profile="mechanical_properties",
                scope="full",
                records=records,
            ),
            GoldTable(
                table_id="T3",
                page_no=6,
                caption="表3 质量一致性检验项目",
                profile="inspection",
                scope="full",
                inspection_items=inspection_items,
            ),
        ],
        clauses=clauses,
        notes=["T4/T5 未标注：T4 为试样编号表，T5 为工艺偏差记录表。"],
    )


# --------------------------------------------------------------------------
# GB/T 40303-2021
# --------------------------------------------------------------------------

CHEM_BLOCK_1 = (
    ["C", "Cr", "Ni", "Co", "Nb", "Mo", "Al", "Ti", "Fe", "P", "S"],
    [
        (
            "普通级*",
            2,
            ["0.015~0.060", "17.00~21.00", "50.00~55.00", "≤1.00", "4.75~5.50",
             "2.80~3.30", "0.30~0.70", "0.75~1.15", "余量", "≤0.015", "≤0.008"],
            "eq",
        ),
        (
            "优质级",
            3,
            ["0.015~0.060", "17.00~21.00", "50.00~55.00", "≤1.00", "5.00~5.50",
             "2.80~3.30", "0.30~0.70", "0.75~1.15", "余量", "≤0.015", "≤0.002 0"],
            "eq",
        ),
        (
            "高纯级",
            4,
            ["0.012~0.036", "17.00~19.00", "52.00~55.00", "≤1.00", "5.20~5.55",
             "2.80~3.15", "0.35~0.65", "0.75~1.15", "16.00~19.00", "0.007~0.015",
             "≤0.001 0"],
            "eq",
        ),
    ],
)

CHEM_BLOCK_2 = (
    ["B", "Mg", "Mn", "Si", "Cu", "Ca", "Bi", "Sn", "Pb", "Ag", "Se"],
    [
        (
            "普通级*",
            8,
            ["0.006", "0.01", "0.35", "0.35", "0.30", "-", "-", "-", "-", "-", "-"],
        ),
        (
            "优质级",
            9,
            ["0.006", "0.005", "0.35", "0.35", "0.30", "0.005", "0.000 03",
             "0.005", "0.000 5", "0.000 5", "0.000 3"],
        ),
        (
            "高纯级",
            10,
            ["0.006", "0.003", "0.35", "0.35", "0.30", "0.005", "0.000 03",
             "0.005", "0.000 5", "0.000 5", "0.000 3"],
        ),
    ],
)

CHEM_BLOCK_3 = (
    ["Te", "Tl", "N", "O", "Ta"],
    [
        ("普通级*", 14, ["-", "-", "-", "-", "0.10"]),
        ("优质级", 15, ["0.000 05", "0.000 1", "0.01", "0.005", "0.10"]),
        ("高纯级", 16, ["0.000 05", "0.000 1", "0.01", "0.002 5", "0.10"]),
    ],
)


def build_gbt40303() -> GoldDocument:
    chem_rows: dict[str, dict[str, GoldValue]] = {}
    for elements, rows in (CHEM_BLOCK_1, CHEM_BLOCK_2, CHEM_BLOCK_3):
        for level, row, cells, *rest in rows:
            default = rest[0] if rest else "max"
            bucket = chem_rows.setdefault(level, {})
            for offset, (element, raw) in enumerate(zip(elements, cells)):
                if raw.strip() in {"", "-"}:
                    continue
                if "余量" in raw:
                    bucket[element] = textv(raw, "%", ev(8, raw, "T3", row, offset + 1))
                else:
                    bucket[element] = numeric(
                        raw, "%", ev(8, raw, "T3", row, offset + 1), default
                    )

    records = [
        GoldRecord(
            record_id=f"gbt40303-T3-{level}",
            grade_level=level,
            facets={"quality_level": level},
            properties=properties,
        )
        for level, properties in chem_rows.items()
    ]

    inspection_specs = [
        ("T9", 12, [
            ("化学成分", "2个/炉", "按GB/T 20066的规定，相当于合金锭头部、尾部", None, "见8.1", None, 1),
            ("室温拉伸", "2个/批", "GB/T 2975，相当于合金锭头、尾部不同棒材", None, None, "GB/T 228.1", 2),
            ("高温拉伸", "2个/批", "GB/T 2975，相当于合金锭头、尾部不同棒材", None, None, "GB/T 228.2", 3),
            ("低温拉伸", "2个/批", "GB/T 2975，相当于合金锭头、尾部不同棒材", None, None, "GB/T 228.3", 4),
            ("室温冲击", "2个/批", "GB/T 2975，相当于合金锭头、尾部不同棒材", None, None, "GB/T 229", 5),
            ("蠕变", "2个/批", "GB/T 2975，相当于合金锭头、尾部不同棒材", None, None, "GB/T 2039", 6),
            ("剪切", "2个/批", "相当于合金锭头、尾部", None, None, "HB 5148", 7),
            ("硬度", "1~2个/批", "相当于合金锭头、尾部", None, None, "GB/T 230.1、GB/T 231.1", 8),
            ("低倍组织", "2个/批", "相当于合金锭头、尾部", None, None, "GB/T 14999.2、B.2.4、附录C", 9),
            ("显微组织", "2个/批", "相当于合金锭头、尾部棒材的半径二分之一处", None, None, "GB/T 13298、B.2.5、附录C", 10),
            ("晶粒度", "2个/批", "相当于合金锭头、尾部棒材的半径二分之一处", None, None, "GB/T 6394", 11),
        ]),
        ("T10", 13, [
            ("超声检测", "逐支", None, None, None, "GB/T 4162-2008", 1),
            ("渗透检测", "逐支", None, None, None, "JB/T 9218-2015", 2),
            ("尺寸、外形", "逐支", None, None, None, "符合精度要求的测量工具", 3),
            ("表面质量", "逐支", None, None, None, "目视，表面粗糙度采用标块目测", 4),
            ("产品标识", "逐支", None, None, None, "目视", 5),
        ]),
    ]
    tables = [
        GoldTable(
            table_id="T3",
            page_no=8,
            caption="表2 化学成分",
            profile="chemical_composition",
            scope="full",
            records=records,
        )
    ]
    for table_id, page, specs in inspection_specs:
        items = []
        for item, quantity, location, requirement, method_clause, standard, row in specs:
            items.append(
                GoldInspectionItem(
                    item=item,
                    quantities={"default": quantity},
                    sample_location=location,
                    requirement_clause=requirement,
                    method_clause=method_clause,
                    method_standard=standard,
                    evidence=ev(page, item, table_id, row, 1),
                )
            )
        tables.append(
            GoldTable(
                table_id=table_id,
                page_no=page,
                caption="表6 检验项目、取样数量、取样部位及取样方法、试验方法",
                profile="inspection",
                scope="full",
                inspection_items=items,
            )
        )

    clauses = [
        GoldClause(
            clause_id="7.3.1",
            title="冷拉棒材交货级别",
            page_no=7,
            kind="delivery",
            fields={
                "level_I_deformation": value(
                    "变形量为8%~12%的冷拉变形",
                    ev(7, "I级：变形量为 8 %～12 % 的冷拉变形，必要时磨光", clause="7.3.1"),
                    "range",
                    lower=8.0,
                    upper=12.0,
                    unit="%",
                ),
                "level_II_deformation": value(
                    "变形量为8%~12%的冷拉变形",
                    ev(7, "Ⅱ级：变形量为 8%～12% 的冷拉变形", clause="7.3.1"),
                    "range",
                    lower=8.0,
                    upper=12.0,
                    unit="%",
                ),
                "level_II_annealing": textv(
                    "955℃±10℃，保温不小于1h，空冷或更快冷却",
                    None,
                    ev(7, "955℃±10℃，保温不小于1h，空冷或更快冷却", clause="7.3.1"),
                ),
                "level_III_deformation": value(
                    "变形量为12%~30%的冷拉变形",
                    ev(7, "Ⅲ级：变形量为 12 %～ 30 % 的冷拉变形，磨光", clause="7.3.1"),
                    "range",
                    lower=12.0,
                    upper=30.0,
                    unit="%",
                ),
            },
            evidence=ev(7, "冷拉棒材的交货状态分为以下三个级别", clause="7.3.1"),
        ),
        GoldClause(
            clause_id="7.3.2",
            title="热轧棒材交货状态",
            page_no=7,
            kind="delivery",
            fields={
                "delivery_state": textv(
                    "热轧状态、经磨光或车光后交货",
                    None,
                    ev(7, "热轧棒材以热轧状态、经磨光或车光后交货。", clause="7.3.2"),
                )
            },
            evidence=ev(7, "热轧棒材以热轧状态、经磨光或车光后交货。", clause="7.3.2"),
        ),
        GoldClause(
            clause_id="7.4.1",
            title="力学性能",
            page_no=7,
            kind="technical_requirement",
            fields={
                "mechanical_requirement": textv(
                    "经热处理后试样的纵向力学性能应符合表3的规定",
                    None,
                    ev(7, "经热处理后试样的纵向力学性能应符合表3的规定。", clause="7.4.1"),
                )
            },
            evidence=ev(7, "经热处理后试样的纵向力学性能应符合表3的规定。", clause="7.4.1"),
        ),
        GoldClause(
            clause_id="9.2",
            title="组批规则",
            page_no=13,
            kind="inspection",
            fields={
                "batch_rule": textv(
                    "每批由同一合金牌号、同一熔炼子炉号、同一规格、同一交货状态的棒材组成；油气用棒材可按母炉号组批，子炉号管理",
                    None,
                    ev(13, "每批应由同一合金牌号、同一熔炼子炉号、同一规格、同一交货状态的棒材组成。", clause="9.2"),
                )
            },
            evidence=ev(13, "每批应由同一合金牌号、同一熔炼子炉号、同一规格、同一交货状态的棒材组成。", clause="9.2"),
        ),
        GoldClause(
            clause_id="9.3",
            title="取样数量和取样部位",
            page_no=13,
            kind="sampling",
            fields={
                "sampling_reference": textv(
                    "取样数量和取样部位应符合表6的规定",
                    None,
                    ev(13, "取样数量和取样部位应符合表6的规定。", clause="9.3"),
                )
            },
            evidence=ev(13, "取样数量和取样部位应符合表6的规定。", clause="9.3"),
        ),
    ]

    return GoldDocument(
        doc_id="gbt40303_2021",
        standard_no="GB/T 40303-2021",
        title="GH4169合金棒材通用技术条件",
        doc_type="gb_t",
        material="GH4169镍基高温合金",
        product_form="棒材",
        source_type="scanned",
        annotation=AnnotationMeta(
            status="draft",
            annotator="agent-draft",
            updated_at="2026-10-25",
            notes=[
                "表2 为三块并列表头，按块合并为 3 条级别记录。",
                "未标注表3 力学性能：OCR 行/列错位严重，列入 M1.5 困难表。",
            ],
        ),
        tables=tables,
        clauses=clauses,
        notes=["T3 化学表普通级 Ca/Bi/Sn/Pb/Ag/Se 为『-』，按未规定处理，不进入标注值。"],
    )


# --------------------------------------------------------------------------
# GJB 2057A-2018
# --------------------------------------------------------------------------


def build_gjb2057a() -> GoldDocument:
    rows = [
        (2, "模锻件", "≤100", "T6", "平行于流线", ["400", "265", "7", "100"]),
        (3, "模锻件", "≤100", "T6", "非平行于流线", ["385", "250", "4", "100"]),
        (4, "自由锻件", "≤100", "T6", "纵向", ["400", "276", "6", "100"]),
        (5, "自由锻件", "≤100", "T6", "横向", ["380", "255", "4", "100"]),
        (6, "自由锻件", "≤100", "T6", "高向", ["365", "240", "2", "100"]),
        (7, "自由锻件", ">100~150", "T6", "纵向", ["390", "275", "5", "100"]),
    ]
    records = []
    for row, form, thickness, state, direction, cells in rows:
        condition = f"{form} / {thickness} / {state} / {direction}"
        records.append(
            GoldRecord(
                record_id=f"gjb2057-T2-{form}-{thickness}-{state}-{direction}",
                grade="2219",
                condition=condition,
                facets={
                    "product_form": form,
                    "thickness": thickness,
                    "heat_treatment": state,
                    "direction": direction,
                },
                properties={
                    "Rm": numeric(cells[0], "MPa", ev(4, cells[0], "T2", row, 4), "min"),
                    "Rp0.2": numeric(cells[1], "MPa", ev(4, cells[1], "T2", row, 5), "min"),
                    "A": numeric(cells[2], "%", ev(4, cells[2], "T2", row, 6), "min"),
                    "HB": numeric(cells[3], "HBW", ev(4, cells[3], "T2", row, 7), "min"),
                },
            )
        )

    inspection_specs = [
        ("化学成分", None, {"Ⅰ类": "每批(或熔次)1个", "Ⅱ类": "每批(或熔次)1个"}, "3.1", "4.3.1", 2),
        ("氢含量", None, {"Ⅰ类": "每批(或熔次)1个", "Ⅱ类": "每批(或熔次)1个"}, "3.2", "4.3.2", 3),
        ("超声检测", None, {"Ⅰ类": "100%", "Ⅱ类": "100%"}, "3.4", "4.3.4", 6),
        ("低倍组织", None, {"Ⅰ类": "每批抽检1件", "Ⅱ类": "每批抽检1件"}, "3.5", "4.3.5", 7),
        ("断口组织", None, {"Ⅰ类": "每批抽检1件", "Ⅱ类": "每批抽检1件"}, "3.6", "4.3.6", 8),
        ("显微组织", None, {"Ⅰ类": "每批(或热处理炉次)抽检1件", "Ⅱ类": "每批(或热处理炉次)抽检1件"}, "3.7", "4.3.7", 9),
        ("尺寸及外形", None, {"Ⅰ类": "100%", "Ⅱ类": "100%"}, "3.8", "4.3.8", 10),
        ("外观质量", None, {"Ⅰ类": "100%", "Ⅱ类": "100%"}, "3.9", "4.3.9", 11),
        ("产品标志", None, {"Ⅰ类": "100%", "Ⅱ类": "100%"}, "3.11", "4.3.10", 12),
    ]
    inspection_items = [
        GoldInspectionItem(
            item=item,
            category=category,
            quantities=quantities,
            requirement_clause=requirement,
            method_clause=method,
            evidence=ev(6, item, "T4", row, 0),
        )
        for item, category, quantities, requirement, method, row in inspection_specs
    ]
    inspection_items.extend(
        [
            GoldInspectionItem(
                item="拉伸性能",
                category="力学性能",
                quantities={"Ⅰ类": "3.4", "Ⅱ类": "每炉次1件"},
                requirement_clause="3.3",
                method_clause="4.3.3",
                status="ambiguous",
                evidence=ev(6, "拉伸性能", "T4", 4, 1),
                note="OCR 显示Ⅰ类数量为『3.4』，疑为『3个』，需页图确认。",
            ),
            GoldInspectionItem(
                item="布氏硬度",
                category="力学性能",
                quantities={"Ⅰ类": "3.4", "Ⅱ类": "每炉次1件"},
                requirement_clause="3.3",
                method_clause="4.3.3",
                status="ambiguous",
                evidence=ev(6, "布氏硬度", "T4", 5, 1),
                note="OCR 显示Ⅰ类数量为『3.4』，疑为『3个』，需页图确认。",
            ),
        ]
    )

    clauses = [
        GoldClause(
            clause_id="3.1",
            title="化学成分",
            page_no=3,
            kind="technical_requirement",
            fields={
                "chemical_requirement": textv(
                    "锻件的化学成分应符合GB/T3190的规定",
                    None,
                    ev(3, "锻件的化学成分应符合GB/T3190的规定。", clause="3.1"),
                )
            },
            evidence=ev(3, "锻件的化学成分应符合GB/T3190的规定。", clause="3.1"),
        ),
        GoldClause(
            clause_id="3.2",
            title="氢含量",
            page_no=3,
            kind="technical_requirement",
            fields={
                "requirement": textv(
                    "锻件的氢含量应符合表1的规定",
                    None,
                    ev(3, "锻件的氢含量应符合表1的规定。", clause="3.2"),
                )
            },
            evidence=ev(3, "锻件的氢含量应符合表1的规定。", clause="3.2"),
        ),
        GoldClause(
            clause_id="3.3",
            title="力学性能",
            page_no=3,
            kind="technical_requirement",
            fields={
                "mechanical_requirement": textv(
                    "室温拉伸力学性能及布氏硬度应符合表2的规定；H112、O状态交货锻件按T6状态性能要求",
                    None,
                    ev(3, "锻件的室温拉伸力学性能及布氏硬度应符合表2的规定。", clause="3.3"),
                )
            },
            evidence=ev(3, "锻件的室温拉伸力学性能及布氏硬度应符合表2的规定。", clause="3.3"),
        ),
        GoldClause(
            clause_id="3.4",
            title="超声检测",
            page_no=3,
            kind="technical_requirement",
            fields={
                "acceptance_level": textv(
                    "GB/T6519-2013中A级或AA级",
                    None,
                    ev(3, "锻件的超声检测结果应符合GB/T6519-2013中A级或AA级的要求", clause="3.4"),
                )
            },
            evidence=ev(3, "锻件的超声检测结果应符合GB/T6519-2013中A级或AA级的要求", clause="3.4"),
        ),
        GoldClause(
            clause_id="4.3.3",
            title="力学性能试验方法",
            page_no=7,
            kind="test_method",
            fields={
                "tensile_method": textv(
                    "GB/T16865",
                    None,
                    ev(7, "锻件的室温拉伸力学性能检验按GB/T16865的规定进行。", clause="4.3.3"),
                ),
                "hardness_method": textv(
                    "GB/T231.1",
                    None,
                    ev(7, "锻件的布氏硬度试验按GB/T231.1的规定进行。", clause="4.3.3"),
                ),
            },
            evidence=ev(7, "锻件的室温拉伸力学性能检验按GB/T16865的规定进行。", clause="4.3.3"),
            )
        ,
        GoldClause(
            clause_id="3.10.1",
            title="冷压缩变形",
            page_no=5,
            kind="technical_requirement",
            fields={
                "cold_compression_range": value(
                    "2%~4%",
                    ev(5, "冷压缩变形率按 2%～4% 进行控制", clause="3.10.1"),
                    "range",
                    lower=2.0,
                    upper=4.0,
                    unit="%",
                ),
                "cold_compression_difference_max": value(
                    "小于1%",
                    ev(5, "单件产品的冷压缩变形率差值应小于 1%", clause="3.10.1"),
                    "max",
                    number=1.0,
                    unit="%",
                ),
            },
            evidence=ev(5, "冷压缩变形率按 2%～4% 进行控制", clause="3.10.1"),
        ),
    ]

    return GoldDocument(
        doc_id="gjb2057a_2018",
        standard_no="GJB 2057A-2018",
        title="航天用2219铝合金锻件规范",
        doc_type="gjb",
        material="2219铝合金",
        product_form="锻件/锻环",
        source_type="scanned",
        annotation=AnnotationMeta(
            status="draft",
            annotator="agent-draft",
            updated_at="2026-10-25",
            notes=[
                "表2 只标注前 6 行（scope=partial），未标注行不计入 precision。",
                "表4 拉伸/布氏硬度Ⅰ类数量的 OCR 值存疑，标为 ambiguous 并跳过评分。",
            ],
        ),
        tables=[
            GoldTable(
                table_id="T1",
                page_no=3,
                caption="表1 氢含量",
                profile="chemical_composition",
                scope="full",
                records=[
                    GoldRecord(
                        record_id="gjb2057-T1-2219-hydrogen",
                        grade="2219",
                        condition="氢含量",
                        properties={
                            "H_liquid": value(
                                "0.15",
                                ev(3, "0.15", "T1", 2, 1),
                                "max",
                                number=0.15,
                                unit="mL/100gAl",
                            ),
                            "H_solid": value(
                                "0.14",
                                ev(3, "0.14", "T1", 2, 2),
                                "max",
                                number=0.14,
                                unit="μg/g",
                            ),
                        },
                    )
                ],
            ),
            GoldTable(
                table_id="T2",
                page_no=4,
                caption="表2 力学性能",
                profile="mechanical_properties",
                scope="partial",
                note="仅标注前 6 行；其余 19 行待补。",
                records=records,
            ),
            GoldTable(
                table_id="T4",
                page_no=6,
                caption="表4 检验项目及取样",
                profile="inspection",
                scope="full",
                inspection_items=inspection_items,
            ),
        ],
        clauses=clauses,
        notes=["T3/T5/T6/T7 未标注：低倍/断口、牌号对照、状态对照、附录公差。"],
    )


def write(gold: GoldDocument) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{gold.doc_id}.json"
    path.write_text(
        json.dumps(gold.model_dump(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {path}")


def main() -> int:
    for builder in (build_qdu302, build_gbt40303, build_gjb2057a):
        write(builder())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
