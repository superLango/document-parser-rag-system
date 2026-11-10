"""Deterministic extraction for inspection and classification tables.

These tables do not need model calls: their headers and row structure are
stable enough to assemble items directly. The extractor is intentionally
shared by every backend (mock and Qwen) so non-record coverage does not depend
on the model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..contracts import (
    ClassificationItem,
    ClauseRecord,
    DocumentMeta,
    Evidence,
    InspectionItem,
    TableGrid,
    TableIR,
)
from ..tablegrid.frame import (
    TableFrame,
    detect_multi_axis_inspection,
    frame_rows,
)
from ..tablegrid.ir import table_grid_from_ir
from ..tablegrid.normalize import clean_text, is_footnote_row


@dataclass
class NonRecordOutput:
    inspection_items: list[InspectionItem] = field(default_factory=list)
    classification_items: list[ClassificationItem] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)


def _looks_like_inspection(headers: list[str]) -> bool:
    has_item = any(
        marker in text
        for text in headers
        for marker in ("检验项目", "试验项目")
    )
    return has_item and any(
        marker in text
        for text in headers
        for marker in (
            "取样数量",
            "取样规定",
            "取样部位",
            "试验方法",
            "检验方法",
            "抽样",
            "复验数量",
            "检测频次",
            "检验频次",
        )
    )


def _looks_like_classification(headers: list[str]) -> bool:
    return (
        any("牌号" in text for text in headers)
        and any("状态" in text for text in headers)
        and any(("含义" in text or "代号" in text) for text in headers)
    )


def extract_nonrecord(table: TableGrid, document: DocumentMeta) -> NonRecordOutput:
    frame = detect_multi_axis_inspection(table)
    if frame is not None:
        return _extract_frame(table, document, frame)
    headers = _headers(table)
    if table.profile == "inspection" or _looks_like_inspection(headers):
        return _extract_inspection(table, document)
    if table.profile == "classification" or _looks_like_classification(headers):
        return _extract_classification(table, document)
    return NonRecordOutput()


def extract_nonrecord_ir(
    ir: TableIR, document: DocumentMeta
) -> NonRecordOutput:
    """Read inspection/classification tables through the unified IR.

    The IR adapter is lossless for every field these readers use, so the
    shared row assembly can consume the IR-reconstructed grid today. The
    dual-run diff proves real documents still agree; cell-level migration of
    the individual readers follows incrementally.
    """

    return extract_nonrecord(table_grid_from_ir(ir), document)


def compare_nonrecord_outputs(
    legacy: NonRecordOutput, current: NonRecordOutput
) -> dict:
    """Diff the grid and IR non-record outputs for one table."""

    inspection_equal = _dumps(legacy.inspection_items) == _dumps(
        current.inspection_items
    )
    classification_equal = _dumps(legacy.classification_items) == _dumps(
        current.classification_items
    )
    evidence_equal = _dumps(legacy.evidence) == _dumps(current.evidence)
    identical = inspection_equal and classification_equal and evidence_equal
    return {
        "status": "identical" if identical else "mismatch",
        "inspection_items": len(legacy.inspection_items),
        "classification_items": len(legacy.classification_items),
        "inspection_equal": inspection_equal,
        "classification_equal": classification_equal,
        "evidence_equal": evidence_equal,
    }


def _dumps(items: list) -> list[dict]:
    return [item.model_dump(mode="json") for item in items]


def _extract_frame(
    table: TableGrid, document: DocumentMeta, frame: TableFrame
) -> NonRecordOutput:
    output = NonRecordOutput()
    for row in frame_rows(table, frame):
        evidence, evidence_id = _evidence(
            document, table, row.row_index, row.item_column, row.item
        )
        output.evidence.append(evidence)
        output.inspection_items.append(
            InspectionItem(
                item=row.item,
                quantities=row.quantities,
                evidence_id=evidence_id,
            )
        )
    output.inspection_items = _merge_duplicate_items(output.inspection_items)
    return output


def _header(text: str) -> str:
    return clean_text(text).lower()


def _headers(table: TableGrid) -> list[str]:
    return [_header(" ".join(path)) for path in table.header_paths]


def _evidence(
    document: DocumentMeta, table: TableGrid, row: int, col: int, quote: str
) -> tuple[Evidence, str]:
    evidence_id = f"ev:{document.doc_id}:{table.table_id}:r{row}:c{col}"
    return (
        Evidence(
            evidence_id=evidence_id,
            page_no=table.page_no,
            table_id=table.table_id,
            row=row,
            col=col,
            quote=quote,
            artifact_uri=f"tablegrid/{table.table_id}.json",
        ),
        evidence_id,
    )


def _footnote(row: list[str]) -> bool:
    first = clean_text(row[0]) if row else ""
    return first.startswith("*") or is_footnote_row(row) or _colspan_note(row)


def _colspan_note(row: list[str]) -> bool:
    """Detect a colspan footnote row (same long prose repeated across cells)."""
    cells = [clean_text(cell) for cell in row if clean_text(cell)]
    if len(cells) < 2:
        return False
    longest = max(cells, key=len)
    return len(longest) >= 20 and cells.count(longest) >= len(cells) - 1


def _strip_footnote(text: str) -> str:
    """Drop OCR footnote suffixes such as 室温拉伸b / 尾部a."""
    return re.sub(r"(?<=[\u4e00-\u9fff\)）])\s*[a-z]$", "", text).strip()


INSPECTION_ITEM_PARTS = (
    "拉伸",
    "冲击",
    "硬度",
    "弯曲",
    "低倍",
    "高倍",
    "晶粒度",
    "化学成分",
    "持久",
    "蠕变",
    "超声",
    "渗透",
    "尺寸",
    "外观",
)


def _split_inspection_item(item: str) -> list[str]:
    """把“拉伸、冲击、硬度”这类组合检验项拆成独立项。"""

    if not any(sep in item for sep in ("、", "，", ",")):
        return [item]
    parts = [part.strip() for part in re.split(r"[、，,]", item) if part.strip()]
    known = [part for part in parts if any(key in part for key in INSPECTION_ITEM_PARTS)]
    if len(known) >= 2:
        return known
    return [item]


def _text_or_none(value: str | None) -> str | None:
    text = clean_text(value)
    return None if text in {"", "-", "—", "－"} else text


TABLE_REF_RE = re.compile(
    r"表\s*(?P<table>[A-Za-z]?\.?\s*\d+(?:\.\d+)?)\s*[，,]\s*"
    r"(?P<column>[A-Za-z])(?P<group>\s*\(\s*组\s*\))?"
    r"(?:\s*[，,]\s*每组\s*(?P<per_group>\d+)\s*个试样)?"
)
TABLE_CAPTION_NO_RE = re.compile(r"表\s*([A-Za-z]?\.?\s*\d+(?:\.\d+)?)")


def resolve_table_references(
    items: list[InspectionItem], tables: list[TableGrid]
) -> list[InspectionItem]:
    """Resolve ``表3，C`` quantity references against the referenced table.

    A reference such as ``表3，C`` usually points to a batch-size lookup, so a
    single integer is not always available. When every lookup row has the same
    value we replace the reference with that value; otherwise the lookup is
    written to ``note`` and the original reference is preserved.
    """

    by_number = {
        number: table
        for table in tables
        if (number := _table_number(table.caption)) is not None
    }
    for item in items:
        notes: list[str] = []
        for key, raw in list(item.quantities.items()):
            match = TABLE_REF_RE.search(raw)
            if match is None:
                continue
            number = re.sub(r"\s+", "", match.group("table")).lower()
            table = by_number.get(number)
            if table is None:
                notes.append(f"{raw}（未找到表{number}）")
                continue
            column = _reference_column(table, match.group("column"))
            if column is None:
                notes.append(f"{raw}（未找到列{match.group('column').upper()}）")
                continue
            lookup = _reference_lookup(table, column)
            if not lookup:
                notes.append(f"{raw}（表{number}无数据）")
                continue
            per_group = (
                int(match.group("per_group"))
                if match.group("per_group")
                else None
            )
            values = {value for _, value in lookup}
            if len(values) == 1 and not per_group:
                item.quantities[key] = next(iter(values))
                notes.append(f"{raw}→{next(iter(values))}")
                continue
            if len(values) == 1 and per_group and values.copy().pop().isdigit():
                base = int(next(iter(values)))
                item.quantities[key] = str(base * per_group)
                notes.append(f"{raw}→{base}组×{per_group}个={base * per_group}")
                continue
            rule = "；".join(f"{span}→{value}" for span, value in lookup)
            suffix = f"；每组{per_group}个试样" if per_group else ""
            notes.append(f"{raw}（{rule}{suffix}）")
        if notes:
            message = "；".join(notes)
            item.note = f"{item.note}；{message}" if item.note else message
    return items


def _table_number(caption: str | None) -> str | None:
    match = TABLE_CAPTION_NO_RE.search(clean_text(caption))
    return re.sub(r"\s+", "", match.group(1)).lower() if match else None


def _reference_column(table: TableGrid, letter: str) -> int | None:
    target = clean_text(letter).upper()
    for index, path in enumerate(table.header_paths):
        if any(clean_text(part).upper() == target for part in path):
            return index
    return None


def _reference_lookup(table: TableGrid, column: int) -> list[tuple[str, str]]:
    lookup: list[tuple[str, str]] = []
    for row in table.rows[table.header_rows :]:
        if column >= len(row) or not row:
            continue
        span = clean_text(row[0])
        value = clean_text(row[column])
        if not span or not value or value in {"-", "—", "－"}:
            continue
        if is_footnote_row(row):
            continue
        lookup.append((span, value))
    return lookup


def _merge_duplicate_items(items: list[InspectionItem]) -> list[InspectionItem]:
    """Merge repeated inspection rows from the same table.

    GJB 5301 lists hardness twice (test ring vs. product), with the same
    requirement/method but different class-level quantities. Keeping only the
    first row drops the product rule; merging preserves both. Rows using only
    a ``default`` quantity key are kept separate because they usually belong to
    different levels/conditions in multi-level sampling tables.
    """

    merged: list[InspectionItem] = []
    for item in items:
        target = next(
            (existing for existing in merged if _can_merge_items(existing, item)),
            None,
        )
        if target is None:
            merged.append(item)
            continue
        target.quantities = _merge_quantities(
            target.quantities, item.quantities
        )
        target.sample_location = _merge_locations(
            target.sample_location, item.sample_location
        )
        target.condition = target.condition or item.condition
        target.requirement = target.requirement or item.requirement
        target.note = target.note or item.note
    return merged


POSITION_RE = re.compile(r"^\d{1,3}$")


def _positions(text: str | None) -> list[str] | None:
    value = _text_or_none(text)
    if not value:
        return None
    parts = [part.strip() for part in re.split(r"[/、,，]", value) if part.strip()]
    if parts and all(POSITION_RE.match(part) for part in parts):
        return parts
    return None


def _merge_locations(left: str | None, right: str | None) -> str | None:
    """Join sample positions (1/2/3) instead of dropping all but the first."""

    left_text = _text_or_none(left)
    right_text = _text_or_none(right)
    if not left_text:
        return right_text
    if not right_text or left_text == right_text:
        return left_text
    left_positions = _positions(left_text)
    right_positions = _positions(right_text)
    if left_positions and right_positions:
        merged = sorted(
            set(left_positions) | set(right_positions), key=lambda value: int(value)
        )
        return "/".join(merged)
    return left_text


def _can_merge_items(left: InspectionItem, right: InspectionItem) -> bool:
    if re.sub(r"\s+", "", left.item) != re.sub(r"\s+", "", right.item):
        return False
    keys = set(left.quantities) | set(right.quantities)
    if not keys or keys == {"default"}:
        return False
    for name in (
        "requirement",
        "requirement_clause",
        "condition",
        "method_clause",
        "method_standard",
    ):
        if (getattr(left, name) or "") != (getattr(right, name) or ""):
            return False
    left_location = _text_or_none(left.sample_location)
    right_location = _text_or_none(right.sample_location)
    if left_location and right_location and left_location != right_location:
        # 批准试验按取样位置 1/2/3 重复列同一项目；位置不是区分条件，
        # 合并后保留全部位置，否则投影只看到“位置=1”。
        if not (_positions(left_location) and _positions(right_location)):
            return False
    return True


def _merge_quantities(
    left: dict[str, str], right: dict[str, str]
) -> dict[str, str]:
    merged = dict(left)
    for key, value in right.items():
        current = merged.get(key)
        if not current or current in {"-", "—", "－"}:
            merged[key] = value
        elif value and value not in {"-", "—", "－"} and value not in current:
            merged[key] = f"{current}；{value}"
    return merged


def _quantity_key(path: list[str]) -> str:
    parts = [clean_text(part) for part in path if clean_text(part)]
    roman = {"I": "Ⅰ", "II": "Ⅱ", "III": "Ⅲ", "IV": "Ⅳ", "Ⅰ": "Ⅰ", "Ⅱ": "Ⅱ", "Ⅲ": "Ⅲ", "Ⅳ": "Ⅳ"}
    # 先找“I类/II类...”等类别列：它们在合并表头下位于父列之后，
    # 不能先返回“取样部位和数量”这种父列名。
    for part in parts:
        cleaned = re.sub(r"textcircle[a-z]*", "", part)
        cleaned = re.sub(r"[，,]\s*(不少于|不小于)$", "", cleaned).strip()
        match = re.fullmatch(r"(I{1,3}|IV|[ⅠⅡⅢⅣ])类(?:件|别)?", cleaned)
        if match:
            return f"{roman[match.group(1)]}类"
    generic = {
        "取样数量",
        "检验项目及数量",
        "取样部位和数量",
        "取样部位及数量",
        "抽样规定",
    }
    for part in parts:
        cleaned = re.sub(r"textcircle[a-z]*", "", part).strip()
        cleaned = re.sub(r"[，,]\s*(不少于|不小于)$", "", cleaned).strip()
        if cleaned in generic:
            continue
        if any(marker in cleaned for marker in ("数量", "张数", "根数", "百分比", "个数")):
            return cleaned
    for part in reversed(parts):
        cleaned = re.sub(r"textcircle[a-z]*", "", part).strip()
        cleaned = re.sub(r"[，,]\s*(不少于|不小于)$", "", cleaned).strip()
        if cleaned and cleaned not in generic:
            return cleaned
    return "default"


def _extract_inspection(table: TableGrid, document: DocumentMeta) -> NonRecordOutput:
    headers = _headers(table)
    item_col = next(
        (
            index
            for index, text in enumerate(headers)
            if (
                "检验项目" in text
                or "试验项目" in text
                or "检验类型" in text
                or "测试类别" in text
                or "测试项目" in text
                or "检查项目" in text
                or "检验内容" in text
            )
            and "数量" not in text
        ),
        None,
    )
    if item_col is None:
        item_col = next(
            (index for index, text in enumerate(headers) if "检验项目" in text),
            None,
        )
    item_col2 = next(
        (
            index
            for index, text in enumerate(headers)
            if index != item_col and "检验项目" in text and "数量" not in text
        ),
        None,
    )
    quantity_cols: list[tuple[int, str]] = []
    sample_location_col = None
    requirement_col = None
    requirement_text_col = None
    condition_col = None
    method_col = None
    method_clause_col = None
    acceptance_col = None

    for index, text in enumerate(headers):
        if index == item_col:
            continue
        if (
            "检验项目及数量" in text
            or "数量" in text
            or "取样规定" in text
            or "张数" in text
            or "根数" in text
            or "个数" in text
            or "抽样" in text
            or "检测频次" in text
            or "检验频次" in text
            or "频次" in text
        ):
            path = table.header_paths[index] if index < len(table.header_paths) else []
            quantity_cols.append((index, _quantity_key(path)))
        if "取样部位" in text and not any(
            marker in text for marker in ("数量", "张数", "根数", "个数")
        ):
            sample_location_col = index
        if (
            sample_location_col is None
            and "位置" in text
            and not any(
                marker in text for marker in ("数量", "张数", "根数", "个数", "尺寸")
            )
        ):
            sample_location_col = index
        if "要求" in text and ("章节" in text or "条款" in text or "章条" in text):
            requirement_col = index
        if (
            requirement_text_col is None
            and any(
                marker in text
                for marker in (
                    "验收指标", "验收要求", "接受准则", "合格标准",
                    "判定标准", "结果要求", "技术要求",
                )
            )
            and not any(
                marker in text for marker in ("章节", "条款", "章条", "方法")
            )
        ):
            requirement_text_col = index
        if condition_col is None and any(
            marker in text for marker in ("测试条件", "试验条件", "测试温度", "试验温度")
        ):
            condition_col = index
        if "试验方法" in text or "检验方法" in text:
            if "章节" in text or "章条" in text or "条款" in text:
                method_clause_col = index
            else:
                method_col = index
        if "认可方式" in text or "验收方式" in text:
            acceptance_col = index

    if item_col is None and not quantity_cols:
        return NonRecordOutput()
    # “试验项目 + 试验数据范围/圆整值”这类附录表不是检验表。
    if (
        not quantity_cols
        and sample_location_col is None
        and requirement_col is None
        and requirement_text_col is None
        and condition_col is None
        and method_col is None
        and method_clause_col is None
    ):
        return NonRecordOutput()

    caption = clean_text(table.caption or "")
    base_item = _sampling_item(caption)
    output = NonRecordOutput()
    for row_index in range(table.header_rows, len(table.rows)):
        row = table.rows[row_index]
        if _footnote(row):
            continue
        item = clean_text(row[item_col]) if item_col is not None and item_col < len(row) else ""
        item_source_col = item_col
        if item_col is not None:
            item = _strip_footnote(item)
            if (
                item in {"力学性能", "物理性能", "性能"}
                and item_col2 is not None
                and item_col2 < len(row)
                and clean_text(row[item_col2])
            ):
                item = _strip_footnote(clean_text(row[item_col2]))
                item_source_col = item_col2
            if not item or item in {"检验项目", "序号"} or item.isdigit():
                continue
        else:
            item = base_item
            if not item:
                continue
        if item in {"一", "—", "－", "-"}:
            continue
        quantities: dict[str, str] = {}
        for col, key in quantity_cols:
            if col >= len(row):
                continue
            raw = clean_text(row[col])
            if not raw:
                continue
            quantities[key] = _quantity_with_unit(raw, key)
        sample_location = (
            _strip_footnote(clean_text(row[sample_location_col]))
            if sample_location_col is not None and sample_location_col < len(row)
            else None
        ) 
        method_from_location = None
        if sample_location:
            match = re.search(r"[，,、;；]?\s*(见\s*\d+(?:\.\d+)*)", sample_location)
            if match:
                method_from_location = match.group(1).replace(" ", "")
                sample_location = sample_location[: match.start()].strip("，,、;； ")
        requirement_clause = (
            _strip_footnote(clean_text(row[requirement_col]))
            if requirement_col is not None and requirement_col < len(row)
            else None
        )
        requirement_text = (
            _strip_footnote(clean_text(row[requirement_text_col]))
            if requirement_text_col is not None and requirement_text_col < len(row)
            else None
        )
        condition = (
            _strip_footnote(clean_text(row[condition_col]))
            if condition_col is not None and condition_col < len(row)
            else None
        )
        method_clause = method_from_location
        method_standard = None
        if method_clause_col is not None and method_clause_col < len(row):
            method_clause = _strip_footnote(clean_text(row[method_clause_col])) or method_clause
        if method_col is not None and method_col < len(row):
            raw_method = _strip_footnote(clean_text(row[method_col]))
            if raw_method.startswith("见") or re.fullmatch(r"\d+(?:\.\d+)*", raw_method):
                method_clause = raw_method
            elif raw_method:
                method_standard = raw_method
        if method_standard is None and acceptance_col is not None and acceptance_col < len(row):
            acceptance = _strip_footnote(clean_text(row[acceptance_col]))
            if any(
                marker in acceptance
                for marker in ("检查", "检测", "测量", "试验", "检验")
            ):
                method_standard = acceptance

        evidence, evidence_id = _evidence(
            document,
            table,
            row_index,
            item_source_col if item_source_col is not None else 0,
            item,
        )
        output.evidence.append(evidence)
        for part in _split_inspection_item(item):
            output.inspection_items.append(
                InspectionItem(
                    item=part,
                    quantities=quantities,
                    sample_location=_text_or_none(sample_location),
                    condition=_text_or_none(condition),
                    requirement=_text_or_none(requirement_text),
                    requirement_clause=_text_or_none(requirement_clause),
                    method_clause=_text_or_none(method_clause),
                    method_standard=_text_or_none(method_standard),
                    evidence_id=evidence_id,
                )
            )
    output.inspection_items = _merge_duplicate_items(output.inspection_items)
    return output


def _quantity_with_unit(raw: str, header: str) -> str:
    if header.endswith("/%") and re.fullmatch(r"\d+(?:\.\d+)?", raw):
        return f"{raw}%"
    if header.endswith("/个") and re.fullmatch(r"\d+(?:\.\d+)?", raw):
        return f"{raw}个"
    return raw


def _sampling_item(caption: str) -> str:
    text = re.sub(r"^表\s*[A-Za-z]?\.?\s*\d+(?:\.\d+)?\s*", "", caption)
    text = re.sub(r"的?取样数量$", "", text).strip()
    return text


NH_RULE_RE = re.compile(r"N\s*表示抽检数量.*?(?:。|$)")


def extract_nh_rule(tables: list[TableGrid]) -> str | None:
    """Extract the N/H sampling rule from checklist footnotes.

    ``N`` is the inspection sample size and ``H`` is the submitted lot size;
    the rule is usually a multi-clause footnote in a separate row/table.
    """

    for table in tables:
        texts = [cell for row in table.rows for cell in row]
        texts.extend(table.footnotes or [])
        for raw in texts:
            text = clean_text(raw)
            if "N" not in text or "H" not in text:
                continue
            match = NH_RULE_RE.search(text)
            if match:
                return match.group(0).strip().rstrip("。")
    return None


def attach_nh_rule(
    items: list[InspectionItem], rule: str | None
) -> list[InspectionItem]:
    """Append the N/H rule to items sampled by ``抽检``.

    The rule cannot be reduced to a single number without the submitted lot
    size ``H``; keeping it in ``note`` preserves the exact business formula.
    """

    if not rule:
        return items
    message = f"抽检数量N/H分档：{rule}"
    for item in items:
        signals = " ".join(str(value) for value in item.quantities.values())
        signals = f"{signals} {item.note or ''}"
        if "抽检" not in signals and "检测频次" not in signals and "检验频次" not in signals:
            continue
        if message in (item.note or ""):
            continue
        item.note = f"{item.note}；{message}" if item.note else message
    return items


CLAUSE_INSPECTION_KEYWORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("化学成分", ("化学成分", "熔炼分析", "成品分析", "化学分析")),
    ("高温拉伸", ("高温拉伸", "高温力学性能")),
    ("室温拉伸", ("室温拉伸", "拉伸试验", "拉伸性能")),
    ("冲击", ("冲击试验", "冲击性能", "夏比")),
    ("硬度", ("硬度试验", "布氏硬度", "洛氏硬度", "维氏硬度")),
    ("晶粒度", ("晶粒度",)),
    ("非金属夹杂物", ("非金属夹杂物", "夹杂物")),
    ("弯曲", ("弯曲试验",)),
    ("晶间腐蚀", ("晶间腐蚀",)),
    ("无损检测", ("无损检测", "超声检测", "射线检测", "渗透检测", "磁粉检测")),
    ("尺寸", ("尺寸检查", "外形尺寸")),
    ("外观质量", ("外观质量", "表面质量")),
)


def inspections_from_clauses(
    clauses: list[ClauseRecord], existing: list[InspectionItem]
) -> list[InspectionItem]:
    """Use sampling clauses when a document has no inspection table.

    Standards often state ``每批取1个试样`` in clause 6.2 instead of a table.
    The table extractor never sees those rules, so schema rows lose both the
    quantity and the explanation. Only clauses that already carry a parsed
    quantity/location are used, and items covered by a table are left alone.
    """

    covered = [clean_text(item.item) for item in existing if clean_text(item.item)]
    specific: list[tuple[ClauseRecord, list[str], str | None, str | None, str | None, str | None]] = []
    generic: list[tuple[ClauseRecord, str | None, str | None, str | None, str | None]] = []
    for clause in clauses:
        fields = clause.fields or {}
        quantity = _text_or_none(_field_text(fields.get("sample_quantity")))
        location = _text_or_none(_field_text(fields.get("sample_location")))
        if location in {"取样规定", "取样", "试样"}:
            location = None
        if not quantity and not location:
            continue
        count_value, note_value = _split_clause_quantity(quantity)
        method = _text_or_none(_field_text(fields.get("method_standard")))
        text = _clause_text(clause)
        labels = _clause_inspection_labels(text)
        if labels:
            specific.append(
                (clause, labels, count_value, note_value, location, method)
            )
        elif _is_generic_mechanical_sampling(text):
            generic.append((clause, count_value, note_value, location, method))

    output: list[InspectionItem] = []
    for clause, labels, count, note, location, method in specific:
        for label in labels:
            if _inspection_covers(label, covered):
                continue
            output.append(
                _clause_item(clause, label, count, note, location, method)
            )
            covered.append(label)

    # A generic “small bars: one sample per 10 pieces” clause has no test name.
    # Attach it to mechanical items that already exist but still lack a count.
    for clause, count, note, location, method in generic:
        for label in ("室温拉伸", "冲击", "硬度"):
            target = _existing_inspection(label, [*existing, *output])
            if target is not None:
                _merge_clause_sampling(target, count, note, location)
                continue
            if _inspection_covers(label, covered):
                continue
            output.append(
                _clause_item(clause, label, count, note, location, method)
            )
            covered.append(label)
    return output


def _clause_item(
    clause: ClauseRecord,
    label: str,
    count: str | None,
    note: str | None,
    location: str | None,
    method: str | None,
) -> InspectionItem:
    return InspectionItem(
        item=label,
        quantities={"取样数量": count} if count else {},
        sample_location=location,
        requirement_clause=clause.clause_id,
        method_standard=method,
        note=note,
        evidence_id=(clause.evidence[0] if clause.evidence else None),
    )


def _merge_clause_sampling(
    item: InspectionItem,
    count: str | None,
    note: str | None,
    location: str | None,
) -> None:
    if count and not item.quantities:
        item.quantities = {"取样数量": count}
    if note and not item.note:
        item.note = note
    if location and not item.sample_location:
        item.sample_location = location


def _is_generic_mechanical_sampling(text: str) -> bool:
    return "试样" in text and any(
        marker in text
        for marker in ("纵向", "横向", "试样数量", "取样数量")
    )


def _existing_inspection(
    label: str, items: list[InspectionItem]
) -> InspectionItem | None:
    for item in items:
        name = clean_text(item.item)
        if name and _matches_label(label, name):
            return item
    return None


def _split_clause_quantity(text: str | None) -> tuple[str | None, str | None]:
    """Keep single counts as quantities; multi-condition rules go to the note."""

    value = _text_or_none(text)
    if not value:
        return None, None
    numbers = re.findall(r"\d+(?:\.\d+)?", value)
    if len(numbers) > 1 and not any(
        marker in value for marker in ("~", "～", "不少于", "不大于", "不多于")
    ):
        # “每10件抽1件”仍可交给 _sample_count 解析，同时保留原文说明。
        if "每" in value:
            return value, value
        return None, value
    return value, None


def _field_text(value) -> str:
    return clean_text(getattr(value, "raw", None) or getattr(value, "text", None))


def _clause_text(clause: ClauseRecord) -> str:
    parts = [clean_text(clause.title)]
    for value in (clause.fields or {}).values():
        parts.append(_field_text(value))
    return " ".join(part for part in parts if part)


def _clause_inspection_labels(text: str) -> list[str]:
    labels: list[str] = []
    for label, keywords in CLAUSE_INSPECTION_KEYWORDS:
        if any(keyword in text for keyword in keywords):
            labels.append(label)
    return labels


def _inspection_covers(label: str, covered: list[str]) -> bool:
    return any(_matches_label(label, item) for item in covered)


def _matches_label(label: str, name: str) -> bool:
    if label == "室温拉伸":
        return "拉伸" in name and "高温" not in name and "低温" not in name
    if label == "高温拉伸":
        return "高温" in name and "拉伸" in name
    if label == "低温拉伸":
        return "低温" in name and "拉伸" in name
    return any(word in name for word in _inspection_synonyms(label))


def _inspection_synonyms(label: str) -> tuple[str, ...]:
    return {
        "化学成分": ("化学",),
        "室温拉伸": ("拉伸",),
        "高温拉伸": ("高温拉伸", "高温"),
        "冲击": ("冲击",),
        "硬度": ("硬度",),
        "晶粒度": ("晶粒",),
        "非金属夹杂物": ("夹杂",),
        "弯曲": ("弯曲",),
        "晶间腐蚀": ("腐蚀",),
        "无损检测": ("无损", "超声", "射线", "渗透", "磁粉"),
        "尺寸": ("尺寸",),
        "外观质量": ("外观", "表面"),
    }.get(label, (label,))


def _extract_classification(
    table: TableGrid, document: DocumentMeta
) -> NonRecordOutput:
    headers = _headers(table)

    grade_cols = [
        index
        for index, text in enumerate(headers)
        if "牌号" in text and "旧" not in text and "原" not in text
    ]
    grade_old = next(
        (
            index
            for index, text in enumerate(headers)
            if "牌号" in text and ("旧" in text or "原" in text)
        ),
        None,
    )
    state_new = next(
        (
            index
            for index, text in enumerate(headers)
            if "状态" in text and ("新" in text or "代号" in text)
        ),
        None,
    )
    if state_new is None:
        state_new = next(
            (
                index
                for index, text in enumerate(headers)
                if "状态" in text and "旧" not in text and "原" not in text
            ),
            None,
        )
    state_old = next(
        (
            index
            for index, text in enumerate(headers)
            if "状态" in text and ("旧" in text or "原" in text)
        ),
        None,
    )
    if state_new is not None and state_old is None:
        state_old = next(
            (
                index
                for index, text in enumerate(headers)
                if index != state_new
                and "状态" in text
                and "试样" in text
            ),
            None,
        )
    meaning = next(
        (index for index, text in enumerate(headers) if "含义" in text), None
    )

    if not grade_cols:
        return NonRecordOutput()

    output = NonRecordOutput()
    for row_index in range(table.header_rows, len(table.rows)):
        row = table.rows[row_index]
        if _footnote(row):
            continue
        grade = ""
        grade_col = grade_cols[0]
        for col in grade_cols:
            if col < len(row) and clean_text(row[col]):
                grade = clean_text(row[col])
                grade_col = col
                break
        if not grade or grade in {"新牌号", "牌号"}:
            continue
        state = (
            clean_text(row[state_new])
            if state_new is not None and state_new < len(row)
            else None
        )
        evidence, evidence_id = _evidence(document, table, row_index, grade_col, grade)
        output.evidence.append(evidence)
        output.classification_items.append(
            ClassificationItem(
                grade=grade,
                old_grade=_text_or_none(row[grade_old]) if grade_old is not None and grade_old < len(row) else None,
                state=state or None,
                old_state=_text_or_none(row[state_old]) if state_old is not None and state_old < len(row) else None,
                meaning=_text_or_none(row[meaning]) if meaning is not None and meaning < len(row) else None,
                evidence_id=evidence_id,
            )
        )
    return output
