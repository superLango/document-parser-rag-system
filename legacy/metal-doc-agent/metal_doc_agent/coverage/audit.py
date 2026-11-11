"""Item-driven coverage audit (M1.7).

The audit answers whether every place that could hold an inspection item was
visited: measure columns, clause mentions, tables, and table rows. It consumes
ItemInventory and TableLinkResult rather than re-deriving them.
"""

from __future__ import annotations

from collections import defaultdict

from ..contracts import (
    ColumnBindingResult,
    CoverageAudit,
    CoverageItem,
    ItemInventory,
    Page,
    Record,
    TableGrid,
    TableLinkResult,
)
from ..items.discover import iter_clause_mentions
from ..items.taxonomy import (
    FAMILY_LABELS,
    canonical_item,
    classify_item,
    normalize_item,
)
from ..tablegrid.normalize import clean_text, is_footnote_row, is_numeric_like

PROPERTY_PROFILES = {"mechanical_properties", "chemical_composition", "hardness"}


def build_coverage_audit(
    doc_id: str,
    pages: list[Page],
    tables: list[TableGrid],
    inventory: ItemInventory,
    links: TableLinkResult,
    bindings: dict[str, ColumnBindingResult] | None = None,
    records: list[Record] | None = None,
) -> CoverageAudit:
    bindings = bindings or {}
    records = records or []
    stats = _stats(tables, inventory, links, bindings, records)
    mention_gaps, mention_total, mention_mapped = _audit_mentions(pages, inventory)
    stats["clause_mentions"] = mention_total
    stats["clause_mentions_mapped"] = mention_mapped
    stats["unmapped_mentions"] = mention_total - mention_mapped

    orphan_rows = _orphan_rows(tables, records)
    stats["orphan_rows"] = len(orphan_rows)
    uncovered = _uncovered_tables(tables, records)
    stats["uncovered_tables"] = len(uncovered)

    gaps: list[dict] = []
    for table_id, column in _unmapped_columns(bindings):
        gaps.append(
            {
                "type": "unmapped_column",
                "table_id": table_id,
                "column": column,
                "reason": "测量列未绑定到项目或属性",
            }
        )
    gaps.extend(
        {"type": "unlinked_table", **orphan} for orphan in links.orphans
    )
    gaps.extend({"type": "unmapped_mention", **gap} for gap in mention_gaps)
    gaps.extend({"type": "orphan_row", **row} for row in orphan_rows)
    gaps.extend({"type": "uncovered_table", **table} for table in uncovered)

    items = _coverage_items(inventory, links, stats, gaps)
    status = _status(stats, gaps)
    return CoverageAudit(
        doc_id=doc_id,
        status=status,
        items=items,
        gaps=gaps,
        stats=stats,
    )


def _stats(
    tables: list[TableGrid],
    inventory: ItemInventory,
    links: TableLinkResult,
    bindings: dict[str, ColumnBindingResult],
    records: list[Record],
) -> dict:
    measure_total = 0
    measure_mapped = 0
    for bound in bindings.values():
        for column in bound.bindings:
            if column.role != "measure":
                continue
            measure_total += 1
            if column.item_family not in {"unknown", "inspection"} and column.property:
                measure_mapped += 1
    coverage = inventory.coverage or {}
    return {
        "tables": len(tables),
        "records": len(records),
        "items": len(inventory.items),
        "confirmed": sum(1 for item in inventory.items if item.status == "confirmed"),
        "probable": sum(1 for item in inventory.items if item.status == "probable"),
        "ambiguous": sum(1 for item in inventory.items if item.status == "ambiguous"),
        "unknown_candidates": len(inventory.unknown_candidates),
        "not_applicable": len(inventory.not_applicable),
        "measure_columns_total": measure_total,
        "measure_columns_mapped": measure_mapped,
        "measure_column_coverage": round(
            measure_mapped / measure_total, 4
        ) if measure_total else 0.0,
        "unmapped_columns": sum(len(bound.unmapped_columns) for bound in bindings.values()),
        "tables_linked": links.coverage.get("linked", 0),
        "tables_explicit": links.coverage.get("explicit", 0),
        "tables_nearest": links.coverage.get("nearest", 0),
        "orphan_tables": len(links.orphans),
        "link_rate": links.coverage.get("link_rate", 0.0),
        "measure_columns_covered": coverage.get("measure_columns_total", 0),
    }


def _audit_mentions(
    pages: list[Page], inventory: ItemInventory
) -> tuple[list[dict], int, int]:
    canonical_index = {
        normalize_item(item.item_canonical or item.item_raw)
        for item in inventory.items
    }
    family_index: dict[str, set[str]] = defaultdict(set)
    for item in inventory.items:
        family_index[item.item_family].add(
            normalize_item(item.item_canonical or item.item_raw)
        )
    raw_index = {normalize_item(item.item_raw) for item in inventory.items}
    triaged = {
        normalize_item(str(candidate.get("raw", "")))
        for candidate in inventory.unknown_candidates
    }
    gaps: list[dict] = []
    total = 0
    mapped = 0
    for mention in iter_clause_mentions(pages):
        total += 1
        raw = mention["raw"]
        family, facets = classify_item(raw)
        if family == "unknown":
            is_mapped = normalize_item(raw) in triaged
        else:
            canonical = normalize_item(canonical_item(raw, family, facets))
            is_mapped = (
                canonical in canonical_index
                or normalize_item(raw) in raw_index
                or _generic_family_mention(canonical, family, family_index)
            )
        if is_mapped:
            mapped += 1
            continue
        gaps.append(
            {
                "raw": raw,
                "clause_id": mention["clause_id"],
                "page_no": mention["page_no"],
                "reason": "条款提及未进入项目清单",
            }
        )
    return gaps, total, mapped


def _generic_family_mention(
    canonical: str, family: str, family_index: dict[str, set[str]]
) -> bool:
    members = family_index.get(family) or set()
    if not members:
        return False
    if canonical == normalize_item(FAMILY_LABELS.get(family, family)):
        return True
    return len(members) == 1


def _unmapped_columns(
    bindings: dict[str, ColumnBindingResult],
) -> list[tuple[str, int]]:
    result: list[tuple[str, int]] = []
    for table_id, bound in bindings.items():
        for column in bound.unmapped_columns:
            result.append((table_id, column))
        for column in bound.bindings:
            if column.status == "ambiguous":
                result.append((table_id, column.column))
    return result


def _orphan_rows(tables: list[TableGrid], records: list[Record]) -> list[dict]:
    by_table: dict[str, list[Record]] = defaultdict(list)
    for record in records:
        if record.source_table_id:
            by_table[record.source_table_id].append(record)
    orphans: list[dict] = []
    for table in tables:
        if table.orientation != "grade_rows":
            continue
        if table.profile not in {"mechanical_properties", "hardness"}:
            continue
        table_records = by_table.get(table.table_id)
        if not table_records:
            continue
        keys = {
            normalize_item(record.grade or record.grade_level or "")
            for record in table_records
        }
        for row_index, row in enumerate(
            table.rows[table.header_rows :], start=table.header_rows
        ):
            key = clean_text(row[0]) if row else ""
            if not key or is_numeric_like(key) or is_footnote_row(row):
                continue
            if normalize_item(key) not in keys:
                orphans.append(
                    {
                        "table_id": table.table_id,
                        "row": row_index,
                        "key": key,
                        "reason": "行未生成记录",
                    }
                )
    return orphans


def _uncovered_tables(tables: list[TableGrid], records: list[Record]) -> list[dict]:
    covered = {record.source_table_id for record in records}
    return [
        {
            "table_id": table.table_id,
            "profile": table.profile,
            "page_no": table.page_no,
            "reason": "属性表未产出记录",
        }
        for table in tables
        if table.profile in PROPERTY_PROFILES and table.table_id not in covered
    ]


def _coverage_items(
    inventory: ItemInventory,
    links: TableLinkResult,
    stats: dict,
    gaps: list[dict],
) -> list[CoverageItem]:
    items: list[CoverageItem] = []
    measure_total = stats["measure_columns_total"]
    measure_coverage = stats["measure_column_coverage"]
    items.append(
        CoverageItem(
            field="items.measure_columns",
            required=measure_total > 0,
            status=(
                "not_applicable"
                if measure_total == 0
                else _rate_status(measure_coverage)
            ),
            expected_locations=[],
            evidence=[],
            reason=(
                "无测量列"
                if measure_total == 0
                else f"{stats['measure_columns_mapped']}/{measure_total} 已映射"
            ),
        )
    )
    item_evidence = all(item.evidence for item in inventory.items)
    items.append(
        CoverageItem(
            field="items.evidence",
            required=True,
            status="found" if item_evidence else "ambiguous",
            reason=None if item_evidence else "存在无证据项目",
        )
    )
    items.append(
        CoverageItem(
            field="links.tables",
            required=True,
            status=_rate_status(stats["link_rate"]),
            reason=f"显式 {stats['tables_explicit']}；"
            f"回退 {stats['tables_nearest']}；"
            f"未链接 {stats['orphan_tables']}",
        )
    )
    mention_total = stats["clause_mentions"]
    unmapped = stats["unmapped_mentions"]
    items.append(
        CoverageItem(
            field="clauses.item_mentions",
            required=mention_total > 0,
            status=(
                "not_applicable"
                if mention_total == 0
                else ("found" if unmapped == 0 else "ambiguous")
            ),
            reason=(
                "无条款项目提及"
                if mention_total == 0
                else f"{stats['clause_mentions_mapped']}/{mention_total} 已映射"
            ),
        )
    )
    items.append(
        CoverageItem(
            field="items.not_applicable",
            required=False,
            status=(
                "not_applicable"
                if inventory.not_applicable
                else "found"
            ),
            reason=(
                f"{len(inventory.not_applicable)} 条不适用说明"
                if inventory.not_applicable
                else None
            ),
        )
    )
    if gaps:
        items.append(
            CoverageItem(
                field="coverage.gaps",
                required=False,
                status="ambiguous",
                reason=f"{len(gaps)} 个覆盖缺口",
            )
        )
    return items


def _rate_status(rate: float) -> str:
    if rate >= 0.95:
        return "found"
    if rate >= 0.8:
        return "ambiguous"
    return "missing"


def _status(stats: dict, gaps: list[dict]) -> str:
    measure_total = stats["measure_columns_total"]
    measure_coverage = stats["measure_column_coverage"]
    if (measure_total and measure_coverage < 0.8) or stats["link_rate"] < 0.8:
        return "fail"
    clean = (
        not gaps
        and (not measure_total or measure_coverage >= 0.95)
        and stats["link_rate"] >= 0.95
        and stats["unmapped_mentions"] == 0
    )
    return "pass" if clean else "review"
