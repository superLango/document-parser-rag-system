"""Deterministic mock extractor.

This is not the final model extractor. It proves the pipeline contracts and
provides a useful baseline: table headers are mapped by rules, values are
normalized by code, and every value gets an evidence pointer.
"""

from __future__ import annotations

import hashlib
import re

from ..contracts import DocumentMeta, Evidence, ExtractedValue, Record, TableBlock, TableGrid
from ..tablegrid.normalize import (
    apply_default_comparator,
    canonical_element,
    canonical_property,
    clean_text,
    is_footnote_row,
    looks_like_grade,
    normalize_value,
    parse_unit,
)
from .base import ExtractionOutput

CONDITION_MARKERS = ("热处理", "状态", "方向", "温度", "取样", "交货")
CHEMICAL_CONDITION_MARKERS = ("类型", "类别", "组织", "状态")
UNSUPPORTED_MARKERS = ("蠕变", "疲劳", "无损检测")
MAX_RULE_COLS = 12
DEFAULT_UNITS = {
    "Rm": "MPa",
    "Rp0.2": "MPa",
    "ReH": "MPa",
    "A": "%",
    "A50mm": "%",
    "Z": "%",
    "KV2": "J",
    "KU2": "J",
    "HB": "HBW",
    "HBW": "HBW",
    "HRC": "HRC",
    "HRB": "HRB",
    "HV": "HV",
}


def _document_grade(document: DocumentMeta) -> str | None:
    for index, text in enumerate((document.title or "", document.file_name or "")):
        patterns = (
            r"GH\d{3,4}[A-Za-z]*",
            r"TA\d{1,2}",
        )
        if index == 0:
            patterns = (*patterns, r"(?<!\d)\d{4}(?!\d)", r"[A-Z]{1,2}\d{2,4}[A-Za-z]?")
        for pattern in patterns:
            match = re.search(pattern, text)
            if not match:
                continue
            value = match.group(0)
            if value in {"GB", "GJB", "HB", "JB", "MAS", "Q"}:
                continue
            if value.isdigit() and 1900 <= int(value) <= 2099:
                continue
            return value
    return None


def _element_condition(table: TableGrid) -> str | None:
    hints = clean_text((table.caption or "") + " " + (table.context or ""))
    if "化学成分" in hints:
        if "wt%" in hints.lower():
            return "wt% / 化学成分"
        return "化学成分"
    return clean_text(table.caption) or None


class MockExtractor:
    name = "mock"

    def extract(self, table: TableGrid, document: DocumentMeta) -> ExtractionOutput:
        output = ExtractionOutput()
        blocks = table.blocks or [self._table_as_block(table)]

        for block in blocks:
            if table.profile == "chemical_composition":
                if table.orientation == "element_rows":
                    records, evidence = self._extract_element_rows(table, block, document)
                else:
                    records, evidence = self._extract_chemical(table, block, document)
            elif table.profile == "mechanical_properties":
                records, evidence = self._extract_mechanical(table, block, document)
            else:
                continue
            output.records.extend(records)
            output.evidence.extend(evidence)

        output.records = self._merge_records(output.records)
        return output

    @staticmethod
    def _table_as_block(table: TableGrid) -> TableBlock:
        return TableBlock(
            block_id=f"{table.table_id}-B1",
            start_row=0,
            header_rows=table.header_rows,
            header_paths=table.header_paths,
            rows=table.rows,
        )

    def _extract_chemical(
        self, table: TableGrid, block: TableBlock, document: DocumentMeta
    ) -> tuple[list[Record], list[Evidence]]:
        paths = block.header_paths
        grade_col = self._find_grade_col(paths)
        condition_cols = [
            col
            for col, path in enumerate(paths)
            if col != grade_col
            and (
                " ".join(path).strip() == "元素"
                or any(
                    marker in " ".join(path) for marker in CHEMICAL_CONDITION_MARKERS
                )
            )
        ]
        element_cols: dict[int, str] = {}
        for col, path in enumerate(paths):
            if col == grade_col or col in condition_cols:
                continue
            element = canonical_element(" ".join(path))
            if element:
                element_cols[col] = element
        if not element_cols:
            return [], []

        records: list[Record] = []
        evidence: list[Evidence] = []
        data_rows = block.rows[block.header_rows :]
        for index, row in enumerate(data_rows):
            if is_footnote_row(row):
                continue
            grade = (
                clean_text(row[grade_col])
                if grade_col is not None and grade_col < len(row)
                else ""
            )
            if grade_col is not None and not self._is_plausible_key(grade):
                continue
            if grade_col is None:
                cells = [
                    clean_text(row[col])
                    for col in element_cols
                    if col < len(row) and clean_text(row[col])
                ]
                if not cells:
                    continue
                if sum(1 for cell in cells if canonical_element(cell)) >= max(
                    1, len(cells) // 2
                ):
                    continue
            condition_parts = [
                clean_text(row[col])
                for col in condition_cols
                if col < len(row) and clean_text(row[col])
            ]
            condition = " / ".join(dict.fromkeys(condition_parts)) or None
            props: dict[str, ExtractedValue] = {}
            for col, element in element_cols.items():
                raw = clean_text(row[col]) if col < len(row) else ""
                if not raw:
                    continue
                parsed = normalize_value(raw)
                if parsed["comparator"] == "na":
                    continue
                evidence_id, item = self._make_value(
                    table=table,
                    block=block,
                    document=document,
                    row_index=index,
                    col=col,
                    raw=raw,
                    parsed=parsed,
                    property_key=element,
                )
                props[element] = item
                evidence.append(self._evidence(table, block, index, col, raw, evidence_id))
            if props:
                grade_level = grade if grade in {"普通级", "优质级", "高纯级"} else None
                record = Record(
                    record_id=self._record_id(
                        document.doc_id, table.table_id, grade or None, condition
                    ),
                    source_table_id=table.table_id,
                    grade=grade or None,
                    grade_level=grade_level,
                    condition=condition,
                    properties=props,
                )
                records.append(record)

        return records, evidence

    def _extract_mechanical(
        self, table: TableGrid, block: TableBlock, document: DocumentMeta
    ) -> tuple[list[Record], list[Evidence]]:
        paths = block.header_paths
        header_text = " ".join(" ".join(path) for path in paths)
        if table.n_cols > MAX_RULE_COLS or any(marker in header_text for marker in UNSUPPORTED_MARKERS):
            return [], []
        grade_col = self._find_grade_col(paths)
        condition_cols = [
            col
            for col, path in enumerate(paths)
            if col != grade_col and any(marker in " ".join(path) for marker in CONDITION_MARKERS)
        ]
        property_cols: dict[int, str] = {}
        for col, path in enumerate(paths):
            if col == grade_col or col in condition_cols:
                continue
            prop = canonical_property(" ".join(path))
            if prop:
                property_cols[col] = prop
        if grade_col is None and len(property_cols) < 2:
            return [], []

        records: list[Record] = []
        evidence: list[Evidence] = []
        data_rows = block.rows[block.header_rows :]
        for index, row in enumerate(data_rows):
            if is_footnote_row(row):
                continue
            grade = (
                clean_text(row[grade_col])
                if grade_col is not None and grade_col < len(row)
                else ""
            )
            if grade_col is None:
                grade = _document_grade(document) or ""
            if grade_col is not None and not self._is_plausible_key(grade):
                continue
            condition_parts = [
                clean_text(row[col]) for col in condition_cols if col < len(row) and clean_text(row[col])
            ]
            condition = " / ".join(dict.fromkeys(condition_parts)) or None
            props: dict[str, ExtractedValue] = {}
            for col, prop in property_cols.items():
                raw = clean_text(row[col]) if col < len(row) else ""
                if not raw:
                    continue
                parsed = normalize_value(raw)
                if parsed["comparator"] == "na":
                    continue
                evidence_id, item = self._make_value(
                    table=table,
                    block=block,
                    document=document,
                    row_index=index,
                    col=col,
                    raw=raw,
                    parsed=parsed,
                    property_key=prop,
                )
                item.condition = condition
                props[prop] = item
                evidence.append(self._evidence(table, block, index, col, raw, evidence_id))
            if props:
                records.append(
                    Record(
                        record_id=self._record_id(
                            document.doc_id, table.table_id, grade or None, condition
                        ),
                        source_table_id=table.table_id,
                        grade=grade or None,
                        condition=condition,
                        properties=props,
                    )
                )

        return records, evidence

    def _extract_element_rows(
        self, table: TableGrid, block: TableBlock, document: DocumentMeta
    ) -> tuple[list[Record], list[Evidence]]:
        paths = block.header_paths
        grade_cols = [
            col
            for col, path in enumerate(paths)
            if looks_like_grade(" ".join(path)) or "牌号" in " ".join(path) or "级别" in " ".join(path)
        ]
        # Elements as columns with a single data row: a one-material spec such
        # as "主要元素，% | Ti | Al | Mo". Build one record instead of keying
        # records by the group header (which produced garbage rows).
        header_elements = [
            canonical_element(clean_text(path[-1])) if path else None for path in paths
        ]
        if (
            not grade_cols
            and sum(1 for element in header_elements if element)
            >= max(2, len(paths) // 2)
        ):
            grade = _document_grade(document)
            condition = _element_condition(table)
            props: dict[str, ExtractedValue] = {}
            evidence: list[Evidence] = []
            for index, row in enumerate(block.rows[block.header_rows :]):
                if is_footnote_row(row):
                    continue
                for col, element in enumerate(header_elements):
                    if not element or col >= len(row):
                        continue
                    raw = clean_text(row[col])
                    if not raw:
                        continue
                    parsed = normalize_value(raw)
                    if parsed["comparator"] == "na":
                        continue
                    evidence_id, item = self._make_value(
                        table=table,
                        block=block,
                        document=document,
                        row_index=index,
                        col=col,
                        raw=raw,
                        parsed=parsed,
                        property_key=element,
                    )
                    props[element] = item
                    evidence.append(
                        self._evidence(table, block, index, col, raw, evidence_id)
                    )
            if not props:
                return [], []
            return [
                Record(
                    record_id=self._record_id(
                        document.doc_id, table.table_id, grade, condition
                    ),
                    source_table_id=table.table_id,
                    grade=grade,
                    condition=condition,
                    properties=props,
                )
            ], evidence
        if not grade_cols:
            grade_cols = list(range(1, len(paths)))

        records: list[Record] = []
        evidence: list[Evidence] = []
        data_rows = block.rows[block.header_rows :]
        by_grade: dict[str, Record] = {}
        for index, row in enumerate(data_rows):
            element = canonical_element(row[0]) if row else None
            if not element:
                continue
            for col in grade_cols:
                if col >= len(row):
                    continue
                raw = clean_text(row[col])
                if not raw:
                    continue
                parsed = normalize_value(raw)
                if parsed["comparator"] == "na":
                    continue
                grade = clean_text(" ".join(paths[col])) or f"col{col}"
                evidence_id, item = self._make_value(
                    table=table,
                    block=block,
                    document=document,
                    row_index=index,
                    col=col,
                    raw=raw,
                    parsed=parsed,
                    property_key=element,
                )
                record = by_grade.setdefault(
                    grade,
                    Record(
                        record_id=self._record_id(document.doc_id, table.table_id, grade, None),
                        source_table_id=table.table_id,
                        grade=grade,
                    ),
                )
                record.properties[element] = item
                evidence.append(self._evidence(table, block, index, col, raw, evidence_id))
        records.extend(by_grade.values())
        return records, evidence

    @staticmethod
    def _is_plausible_key(text: str) -> bool:
        if not text or text in {
            "级别",
            "牌号",
            "合金牌号",
            "Grade",
            "序号",
            "名称",
            "材质",
            "材料",
            "元素",
            "含量/%",
        }:
            return False
        if len(text) > 30:
            return False
        if any(marker in text for marker in ("注", "试样结果", "仅实测", "根据需方", "不大于", "小于", "。", "；")):
            return False
        return True

    @staticmethod
    def _find_grade_col(paths: list[list[str]]) -> int | None:
        for col, path in enumerate(paths):
            text = " ".join(path)
            if any(
                key in text
                for key in ("牌号", "级别", "Grade", "grade", "材质", "钢号", "材料", "钢类")
            ):
                return col
        return None

    @staticmethod
    def _make_value(
        table: TableGrid,
        block: TableBlock,
        document: DocumentMeta,
        row_index: int,
        col: int,
        raw: str,
        parsed: dict,
        property_key: str,
    ) -> tuple[str, ExtractedValue]:
        absolute_row = block.start_row + block.header_rows + row_index
        evidence_id = f"ev:{document.doc_id}:{table.table_id}:r{absolute_row}:c{col}"
        if parsed.get("unit") is None and col < len(block.header_paths):
            parsed["unit"] = parse_unit(" ".join(block.header_paths[col]))
        if parsed.get("unit") is None and parsed.get("value") is not None:
            # Standard properties carry an implied unit even when the header
            # omits it, e.g. "冲击吸收功Aku2d" = J.
            parsed["unit"] = DEFAULT_UNITS.get(property_key)
        parsed = apply_default_comparator(
            parsed,
            property_key=property_key,
            header_path=block.header_paths[col],
            chemical=table.profile == "chemical_composition",
        )
        item = ExtractedValue(
            raw=parsed.get("raw", raw),
            value=parsed.get("value"),
            text=parsed.get("text"),
            unit=parsed.get("unit"),
            comparator=parsed.get("comparator", "eq"),
            lower=parsed.get("lower"),
            upper=parsed.get("upper"),
            evidence_id=evidence_id,
        )
        return evidence_id, item

    @staticmethod
    def _evidence(
        table: TableGrid,
        block: TableBlock,
        row_index: int,
        col: int,
        raw: str,
        evidence_id: str,
    ) -> Evidence:
        absolute_row = block.start_row + block.header_rows + row_index
        return Evidence(
            evidence_id=evidence_id,
            page_no=table.page_no,
            table_id=table.table_id,
            row=absolute_row,
            col=col,
            quote=raw,
            artifact_uri=f"tablegrid/{table.table_id}.json",
        )

    @staticmethod
    def _record_id(doc_id: str, table_id: str, grade: str | None, condition: str | None) -> str:
        key = f"{doc_id}|{table_id}|{grade or ''}|{condition or ''}"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]
        return f"rec-{digest}"

    @staticmethod
    def _merge_records(records: list[Record]) -> list[Record]:
        merged: dict[str, Record] = {}
        for record in records:
            existing = merged.get(record.record_id)
            if existing:
                existing.properties.update(record.properties)
            else:
                merged[record.record_id] = record
        return list(merged.values())
