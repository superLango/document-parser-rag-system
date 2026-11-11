"""Item discovery from tables, bindings, clauses and references (M1.7)."""

from __future__ import annotations

import re

from ..contracts import (
    ClauseRecord,
    ColumnBindingResult,
    CrossStandardTask,
    InspectionItem,
    ItemInventory,
    ItemInventoryEntry,
    Page,
    TableGrid,
)
from ..tablegrid.normalize import (
    canonical_element,
    canonical_property,
    clean_text,
    is_footnote_row,
    is_numeric_like,
    resolve_element_label_from_notes,
)
from .taxonomy import (
    FAMILY_LABELS,
    IDENTITY_FACETS_BY_FAMILY,
    canonical_item,
    classify_item,
    is_umbrella,
    item_key,
    split_item_text,
)

CLAUSE_ITEM_RE = re.compile(
    r"(?:应|需|须|必须)?(?:进行|做)\s*(?P<item>[\u4e00-\u9fffA-Za-z0-9α-ω\-/]{2,20}?)"
    r"(?:检验|试验|检测|检查|探伤)"
)
INSPECTION_CATALOG_RE = re.compile(r"必检项目|定期检验项目|特殊要求检验项目")
ITEM_COLUMN_MARKERS = (
    "检验项目", "试验项目", "测试类别", "测试项目", "检查项目", "检验内容",
    "test item", "test category", "inspection item", "examination item",
)


def _is_item_column(header_path: list[str] | tuple[str, ...]) -> bool:
    text = " ".join(header_path)
    return any(marker in text for marker in ITEM_COLUMN_MARKERS)
CLAUSE_REF_RE = re.compile(
    r"(?P<item>[\u4e00-\u9fffA-Za-z0-9α-ω\-/]{2,20}?)\s*(?:应)?按\s*"
    r"(?P<std>(?:GB/T|GB|GJB|JB/T|YB/T|HB|ASTM|ISO|AMS|Q/[A-Za-z]+)\s*[0-9.\-]+)"
    r"\s*(?:的)?(?:规定|要求)?\s*(?:进行|执行|检验|试验|检测)"
)
CLAUSE_LIST_RE = re.compile(r"检验项目(?:包括|有|为)[:：]?(?P<items>[^。；\n]+)")
HEADING_RE = re.compile(r"^\s*#{0,6}\s*(\d{1,2}(?:\.\s*\d{1,3}){0,3})\s+(.+)$")
NOISE_PARTS = ("方法", "规定", "要求", "标准", "章", "条", "表", "附录", "文件")
STD_RE = re.compile(
    r"(?:GB/T|GB|GJB|JB/T|YB/T|HB|ASTM|ISO|AMS|Q/[A-Za-z]+)\s*[0-9.\-]+",
    re.IGNORECASE,
)
INSPECTION_ALIASES = {
    "室温力学性能": "力学性能",
    "高温力学性能": "力学性能",
    "布氏硬度": "硬度",
}
_PAREN_RE = re.compile(r"[（(][^）)]*[）)]")
_TRAILING_UNIT_RE = re.compile(r"(?:%|mm|MPa|GPa|J|℃|°C|HRC|HV|HBW)\s*$", re.IGNORECASE)
_FOOTNOTE_TAIL_RE = re.compile(r"^([\u4e00-\u9fff]{2,})([a-z])$")
_ITEM_STOP_PREFIX = (
    "对于",
    "应按",
    "且",
    "应在",
    "分别",
    "高纯",
    "其中",
    "如果",
    "当",
    "尾部",
    "头部",
    "一次",
    "全面",
    "每",
    "其他",
    "下列",
    "其中",
)
_ITEM_NOISE = {"重复", "试验", "检验", "检测", "检查", "项目", "要求", "规定"}
_SUBJECT_SUFFIXES = (
    "棒材",
    "板材",
    "带材",
    "管材",
    "丝材",
    "锻件",
    "铸件",
    "材料",
    "产品",
    "试样",
    "零件",
    "合金",
)
_TEXTCIRCLED_RE = re.compile(r"textcircled[a-z0-9]*", re.IGNORECASE)

_SOURCE_PRIORITY = {
    "inspection_table": 4,
    "property_table": 3,
    "clause": 2,
    "reference": 1,
    "manual": 5,
}
_PROPERTY_FAMILY = {
    "Rm": "tensile",
    "ReL": "tensile",
    "Rp0.2": "tensile",
    "A": "tensile",
    "A50mm": "tensile",
    "Z": "tensile",
    "E": "tensile",
    "KV2": "impact",
    "KU2": "impact",
    "KU5": "impact",
    "侧向膨胀值": "impact",
    "HB": "hardness",
    "HBW": "hardness",
    "HRC": "hardness",
    "HRB": "hardness",
    "HV": "hardness",
    "厚度": "dimension",
    "宽度": "dimension",
    "长度": "dimension",
    "内径": "dimension",
    "外径": "dimension",
    "尺寸偏差": "dimension",
    "CEV": "chemical_composition",
    "Pcm": "chemical_composition",
}
_STATUS_PRIORITY = {
    "confirmed": 4,
    "probable": 3,
    "ambiguous": 2,
    "new": 1,
    "not_applicable": 0,
}


def discover_items(
    pages: list[Page],
    tables: list[TableGrid],
    bindings: dict[str, ColumnBindingResult] | None = None,
    cross_tasks: list[CrossStandardTask] | None = None,
    *,
    doc_id: str = "",
    document_profile: str | None = None,
) -> ItemInventory:
    binding_map = bindings or {}
    entries: list[ItemInventoryEntry] = []
    unknown: list[dict] = []
    for table in tables:
        bound = binding_map.get(table.table_id)
        table_entries: list[ItemInventoryEntry] = []
        if table.profile == "inspection":
            table_entries.extend(_inspection_table_items(table, bound, unknown))
        if bound is not None:
            table_entries.extend(_property_group_items(table, bound, unknown))
        if not any(entry.source == "property_table" for entry in table_entries):
            table_entries.extend(_profile_fallback_items(table))
        entries.extend(table_entries)
    entries.extend(_clause_items(pages, unknown))
    entries.extend(_reference_items(cross_tasks or [], unknown))
    unknown = _dedupe_unknown(unknown)
    _complete_identity(entries)
    merged = _merge(entries)
    not_applicable: list[dict] = []
    if document_profile == "heat_treatment_plan":
        # 检查计划的核心是“检查组别 × 抽检比例”，现有产品字段 schema 无法承载；
        # 先明确标为不适用，避免把计划表拆成空壳检验项。
        not_applicable.append(
            {
                "reason": "热处理检查计划按检查组别×抽检比例组织，不适用产品字段投影",
                "profile": document_profile,
            }
        )
    elif not merged and document_profile in {"classification", "technical_agreement"}:
        not_applicable.append(
            {"reason": f"文档类型 {document_profile} 无检验项目", "profile": document_profile}
        )
    coverage = _coverage(tables, binding_map, merged, unknown)
    recipe_ids = sorted(
        {
            item.recipe_id
            for item in binding_map.values()
            if item.recipe_id
        }
    )
    return ItemInventory(
        doc_id=doc_id,
        items=merged,
        unknown_candidates=unknown,
        not_applicable=not_applicable,
        coverage=coverage,
        recipe_ids=recipe_ids,
    )


def _inspection_table_items(
    table: TableGrid,
    bound: ColumnBindingResult | None,
    unknown: list[dict],
) -> list[ItemInventoryEntry]:
    header_blob = " ".join(part for path in table.header_paths for part in path)
    caption = clean_text(table.caption) or ""
    if INSPECTION_CATALOG_RE.search(header_blob) or (
        "膜层性能" in caption and "检验项目" in caption
    ):
        # 表10「表面处理型材的膜层性能检验项目」按出厂必检/定期检验/特殊
        # 要求列出项目名，并没有逐项要求；把它拆成检验项会把涂层指标
        # （耐冲击性、耐盐雾腐蚀性等）误挂到金属材料大类上。
        return []
    item_columns = []
    if bound is not None:
        item_columns = [
            item.column
            for item in bound.bindings
            if item.role == "row_key" and _is_item_column(item.header_path)
        ]
    if not item_columns:
        item_columns = [
            index
            for index, path in enumerate(table.header_paths)
            if _is_item_column(path)
        ]
    if not item_columns:
        return []
    item_col = item_columns[0]
    method_col = _column_by_exact(table, ("试验方法", "检验方法", "方法"))
    if method_col is None:
        method_col = _column_by_keyword(table, ("试验方法", "检验方法"))
    sampling_qty_col = _column_by_exact(
        table, ("取样数量", "试样数量", "数量", "sample qty", "sample size")
    )
    sampling_pos_col = _column_by_exact(
        table,
        (
            "取样部位", "取样部位及方法", "取样部位及取样方法", "部位",
            "位置", "取样位置", "sample position",
        ),
    )
    entries: list[ItemInventoryEntry] = []
    for row_index, row in enumerate(table.rows[table.header_rows :], start=table.header_rows):
        if item_col >= len(row):
            continue
        raw = clean_text(row[item_col])
        raw = _clean_item_name(raw)
        if not raw or raw in {"检验项目", "项目"} or is_numeric_like(raw) or is_footnote_row(row):
            continue
        method = row[method_col] if method_col is not None and method_col < len(row) else ""
        method = _clean_method(method)
        facets: dict[str, str] = {}
        if sampling_qty_col is not None and sampling_qty_col < len(row):
            quantity = _clean_aux_cell(row[sampling_qty_col])
            if quantity:
                facets["sampling_quantity"] = quantity
        if sampling_pos_col is not None and sampling_pos_col < len(row):
            position = _clean_aux_cell(row[sampling_pos_col])
            if position:
                facets["sampling_position"] = position
        for item_raw in split_item_text(raw):
            family, item_facets = classify_item(item_raw, facets)
            if family == "unknown" and is_umbrella(item_raw):
                unknown.append(
                    {
                        "raw": item_raw,
                        "source": "inspection_table",
                        "page_no": table.page_no,
                        "table_id": table.table_id,
                        "reason": "综合性项目，需拆分",
                    }
                )
                continue
            item_facets = {key: value for key, value in item_facets.items() if value}
            canonical = canonical_item(item_raw, family, item_facets)
            entry = ItemInventoryEntry(
                item_raw=item_raw,
                item_canonical=canonical,
                item_family=family,
                facets=item_facets,
                method_standard=method,
                source="inspection_table",
                page_no=table.page_no,
                table_id=table.table_id,
                evidence=[f"{table.table_id}:{row_index}:{item_raw}"],
                status="confirmed" if family != "unknown" else "ambiguous",
            )
            entries.append(entry)
            if family == "unknown":
                unknown.append(
                    {
                        "raw": item_raw,
                        "source": "inspection_table",
                        "page_no": table.page_no,
                        "table_id": table.table_id,
                        "reason": "项目词表未识别",
                    }
                )
    return entries


def _property_group_items(
    table: TableGrid,
    bound: ColumnBindingResult,
    unknown: list[dict],
) -> list[ItemInventoryEntry]:
    entries: list[ItemInventoryEntry] = []
    for group in bound.item_groups:
        if group.item_family in {"unknown", "inspection"}:
            continue
        properties = []
        method_standard = group.facets.get("method_standard")
        for column in group.columns:
            if column >= len(bound.bindings):
                continue
            item = bound.bindings[column]
            if item.role == "measure" and item.property and item.property not in properties:
                properties.append(item.property)
            if not method_standard and item.facets.get("method_standard"):
                method_standard = item.facets["method_standard"]
        if not properties:
            continue
        if table.profile == "unknown" and len(properties) < 2:
            # Footnote blocks and pseudo tables can route to a recipe by
            # accident; a single stray property is not a usable item group.
            continue
        raw = group.item_raw or FAMILY_LABELS.get(group.item_family, group.item_family)
        if group.item_family == "dimension":
            raw = "尺寸"
        if raw.strip().lower() == group.item_family:
            raw = FAMILY_LABELS.get(group.item_family, raw)
        raw = _clean_item_name(raw) or FAMILY_LABELS.get(
            group.item_family, group.item_family
        )
        facets = {
            key: value
            for key, value in group.facets.items()
            if key != "conditions" and value
        }
        classified_family, classified_facets = classify_item(raw, facets)
        if classified_family != "unknown":
            family = classified_family
        else:
            family = group.item_family
        if family == "chemical_composition":
            raw = "化学成分"
        facets.update(
            {
                key: value
                for key, value in classified_facets.items()
                if value and key not in facets
            }
        )
        canonical = canonical_item(raw, family, facets)
        status = "confirmed" if group.status == "bound" else "ambiguous"
        entries.append(
            ItemInventoryEntry(
                item_raw=raw,
                item_canonical=canonical,
                item_family=family,
                facets=facets,
                properties=properties,
                method_standard=method_standard,
                source="property_table",
                page_no=table.page_no,
                table_id=table.table_id,
                evidence=[f"{table.table_id}:{group.group_id}"],
                status=status,
            )
        )
        if group.status != "bound":
            unknown.append(
                {
                    "raw": raw,
                    "source": "property_table",
                    "page_no": table.page_no,
                    "table_id": table.table_id,
                    "reason": f"项目组状态 {group.status}",
                }
            )
    return entries


def iter_clause_mentions(pages: list[Page]):
    """Yield cleaned inspection-item mentions found in clause text."""

    for page in pages:
        clause_id = None
        for line in page.markdown.splitlines():
            heading = HEADING_RE.match(line.strip())
            if heading:
                clause_id = re.sub(r"\s+", "", heading.group(1))
            text = clean_text(line)
            if not text or len(text) > 300:
                continue
            candidates: list[tuple[str, str | None]] = []
            for match in CLAUSE_ITEM_RE.finditer(text):
                candidates.append((match.group("item"), None))
            for match in CLAUSE_REF_RE.finditer(text):
                candidates.append((match.group("item"), match.group("std")))
            for match in CLAUSE_LIST_RE.finditer(text):
                for item in split_item_text(match.group("items")):
                    candidates.append((item, None))
            seen: set[str] = set()
            for raw, method in candidates:
                raw = clean_text(raw)
                raw = re.sub(r"^(?:为|对|其|的|按)+", "", raw)
                raw = re.sub(r"(?:复验|的)$", "", raw)
                raw = _clean_item_name(raw)
                if not raw or raw in seen or any(part in raw for part in NOISE_PARTS):
                    continue
                seen.add(raw)
                yield {
                    "raw": raw,
                    "method_standard": method,
                    "clause_id": clause_id,
                    "page_no": page.page_no,
                    "text": text[:300],
                }


def attach_clause_methods(
    inventory: ItemInventory,
    inspections: list[InspectionItem],
    clauses: list[ClauseRecord],
) -> int:
    """Fill missing item methods from the method clause referenced by 表3."""

    clause_methods: dict[str, str] = {}
    for clause in clauses:
        value = clause.fields.get("method_standard")
        if value is None:
            continue
        method = clean_text(value.text) or clean_text(value.raw)
        if method:
            clause_methods[clause.clause_id] = method
    if not clause_methods:
        return 0
    by_name = {inspection.item: inspection for inspection in inspections}
    updated = 0
    for entry in inventory.items:
        if entry.method_standard:
            continue
        inspection = _match_inspection(entry, by_name)
        if inspection is None or not inspection.method_clause:
            continue
        method = clause_methods.get(_clause_ref(inspection.method_clause) or "")
        if method:
            entry.method_standard = method
            updated += 1
    return updated


def _clause_ref(value: str | None) -> str | None:
    """Normalize "见8.2" / "第8.2条" to the clause id "8.2"."""
    text = clean_text(value)
    if not text:
        return None
    text = re.sub(r"^(?:见|参见|依据|按)\s*", "", text)
    text = re.sub(r"^第\s*", "", text)
    text = re.sub(r"\s*(?:条|章|节)$", "", text)
    return text.strip() or None


def _match_inspection(
    entry: ItemInventoryEntry, by_name: dict[str, InspectionItem]
) -> InspectionItem | None:
    names = [name for name in (entry.item_raw, entry.item_canonical) if name]
    for name in names:
        if name in by_name:
            return by_name[name]
    for name in names:
        alias = INSPECTION_ALIASES.get(name)
        if alias and alias in by_name:
            return by_name[alias]
    for name in names:
        if len(name) < 3:
            continue
        for key, inspection in by_name.items():
            if name in key or key in name:
                return inspection
    return None


def _clause_items(pages: list[Page], unknown: list[dict]) -> list[ItemInventoryEntry]:
    entries: list[ItemInventoryEntry] = []
    for mention in iter_clause_mentions(pages):
        raw = mention["raw"]
        family, facets = classify_item(raw)
        if family == "unknown":
            unknown.append(
                {
                    "raw": raw,
                    "source": "clause",
                    "page_no": mention["page_no"],
                    "clause_id": mention["clause_id"],
                    "reason": (
                        "综合性项目，需拆分"
                        if is_umbrella(raw)
                        else "条款项目词表未识别"
                    ),
                }
            )
            continue
        entries.append(
            ItemInventoryEntry(
                item_raw=raw,
                item_canonical=canonical_item(raw, family, facets),
                item_family=family,
                facets=facets,
                method_standard=mention["method_standard"],
                source="clause",
                clause_id=mention["clause_id"],
                page_no=mention["page_no"],
                evidence=[mention["text"]],
                status="probable",
            )
        )
    return entries


def _reference_items(
    tasks: list[CrossStandardTask], unknown: list[dict]
) -> list[ItemInventoryEntry]:
    entries: list[ItemInventoryEntry] = []
    for task in tasks:
        raw = _clean_item_name(task.inspection_item)
        if not raw:
            continue
        family, facets = classify_item(raw)
        if family == "unknown":
            unknown.append(
                {
                    "raw": raw,
                    "source": "reference",
                    "page_no": task.page_no,
                    "reason": "跨标准任务项目未识别",
                }
            )
            continue
        entries.append(
            ItemInventoryEntry(
                item_raw=raw,
                item_canonical=canonical_item(raw, family, facets),
                item_family=family,
                facets=facets,
                method_standard=task.method_standard,
                source="reference",
                clause_id=task.clause_id,
                page_no=task.page_no,
                evidence=[task.quote or raw],
                status="probable",
            )
        )
    return entries


def _complete_identity(entries: list[ItemInventoryEntry]) -> None:
    """Fill identity facets that are unambiguous within the document.

    A standard normally uses one impact type or one hardness scale per
    document; when that is the case, items that omit the dimension can inherit
    it. Tensile items without a temperature inherit room temperature, which is
    the default when a standard writes only ``拉伸``/``力学性能``.
    """

    for family, dims in IDENTITY_FACETS_BY_FAMILY.items():
        family_entries = [entry for entry in entries if entry.item_family == family]
        if not family_entries:
            continue
        for dim in dims:
            explicit = {
                entry.facets[dim]
                for entry in family_entries
                if entry.facets.get(dim)
            }
            if len(explicit) != 1:
                continue
            value = next(iter(explicit))
            for entry in family_entries:
                if not entry.facets.get(dim):
                    entry.facets[dim] = value
                    entry.facets[f"{dim}_basis"] = "document"

    explicit_impact_types = {
        entry.facets["impact_type"]
        for entry in entries
        if entry.item_family == "impact" and entry.facets.get("impact_type")
    }
    for entry in entries:
        if entry.item_family == "tensile" and not entry.facets.get("temperature"):
            entry.facets["temperature"] = "室温"
            entry.facets["temperature_basis"] = "default"
        if (
            entry.item_family == "impact"
            and not entry.facets.get("impact_type")
            and explicit_impact_types <= {"夏比"}
        ):
            entry.facets["impact_type"] = "夏比"
            entry.facets["impact_type_basis"] = "default"

    for entry in entries:
        entry.item_canonical = canonical_item(
            entry.item_raw, entry.item_family, entry.facets
        )


def _property_family(prop: str) -> str | None:
    if canonical_element(prop):
        return "chemical_composition"
    return _PROPERTY_FAMILY.get(prop)


def _profile_fallback_items(table: TableGrid) -> list[ItemInventoryEntry]:
    """Create an item when a chemistry/mechanical table has no bound recipe.

    Imported specifications (especially English ones) often have a clean table
    but no matching recipe; without this fallback the extracted records would
    have no inventory item to project onto.
    """

    if table.profile == "chemical_composition":
        properties = _table_elements(table)
        if not properties:
            return []
        return [
            ItemInventoryEntry(
                item_raw="化学成分",
                item_canonical="化学成分",
                item_family="chemical_composition",
                properties=properties,
                source="property_table",
                page_no=table.page_no,
                table_id=table.table_id,
                evidence=[f"{table.table_id}:elements"],
                status="probable",
            )
        ]
    if table.profile == "mechanical_properties":
        properties = _table_properties(table)
        if not properties:
            return []
        family = _fallback_family(properties[0])
        if family is None:
            return []
        raw = FAMILY_LABELS.get(family, family)
        return [
            ItemInventoryEntry(
                item_raw=raw,
                item_canonical=canonical_item(raw, family, {}),
                item_family=family,
                properties=properties,
                source="property_table",
                page_no=table.page_no,
                table_id=table.table_id,
                evidence=[f"{table.table_id}:properties"],
                status="probable",
            )
        ]
    return []


def _table_elements(table: TableGrid) -> list[str]:
    notes = [*(table.footnotes or [])]
    if table.caption:
        notes.append(table.caption)
    for row in table.rows[table.header_rows :]:
        if is_footnote_row(row):
            notes.extend(cell for cell in row if cell)
    notes_text = clean_text(" ".join(notes))
    values: list[str] = []
    for path in table.header_paths:
        for cell in path:
            text = clean_text(cell)
            if len(text) <= 24:
                element = resolve_element_label_from_notes(text, notes_text)
                if element and element not in values:
                    values.append(element)
    for row in (table.rows or [])[:50]:
        if not row:
            continue
        text = clean_text(row[0])
        if len(text) > 24:
            continue
        element = resolve_element_label_from_notes(text, notes_text)
        if element and element not in values:
            values.append(element)
    return values


def _table_properties(table: TableGrid) -> list[str]:
    values: list[str] = []
    candidates: list[str] = []
    for path in table.header_paths:
        candidates.extend(path)
    for row in (table.rows or [])[:40]:
        if row:
            candidates.append(row[0])
    for cell in candidates:
        text = clean_text(cell)
        if not text or len(text) > 40:
            continue
        prop = canonical_property(text)
        if prop is None and "hardness" in text.lower():
            prop = "HB"
        if prop and prop not in values:
            values.append(prop)
    return values


def _fallback_family(prop: str) -> str | None:
    if prop in {"Rm", "Rp0.2", "ReH", "A", "A50mm", "Z"}:
        return "tensile"
    if prop in {"HB", "HRB", "HRC", "HV"}:
        return "hardness"
    if prop in {"KV2", "KU2", "KU1", "KU5"}:
        return "impact"
    if prop.startswith("σ"):
        return "stress_rupture"
    return None


def _merge(entries: list[ItemInventoryEntry]) -> list[ItemInventoryEntry]:
    merged: dict[tuple, ItemInventoryEntry] = {}
    for entry in entries:
        key = item_key(entry.item_canonical or entry.item_raw, entry.item_family, entry.facets)
        existing = merged.get(key)
        if existing is None:
            merged[key] = entry.model_copy(deep=True)
            continue
        for prop in entry.properties:
            prop_family = _property_family(prop)
            if prop_family and existing.item_family not in {prop_family, "unknown"}:
                continue
            if prop not in existing.properties:
                existing.properties.append(prop)
        for facet_key, value in entry.facets.items():
            existing.facets.setdefault(facet_key, value)
        for evidence in entry.evidence:
            if evidence not in existing.evidence:
                existing.evidence.append(evidence)
        if not existing.method_standard and entry.method_standard:
            existing.method_standard = entry.method_standard
        if _SOURCE_PRIORITY.get(entry.source, 0) > _SOURCE_PRIORITY.get(existing.source, 0):
            existing.source = entry.source
            existing.item_raw = entry.item_raw
            existing.table_id = entry.table_id or existing.table_id
        if _STATUS_PRIORITY.get(entry.status, 0) > _STATUS_PRIORITY.get(existing.status, 0):
            existing.status = entry.status
    for entry in merged.values():
        entry.properties = [
            prop
            for prop in entry.properties
            if _property_family(prop) in {None, entry.item_family}
            or entry.item_family == "unknown"
        ]
    return sorted(
        merged.values(),
        key=lambda item: (item.item_family, item.item_canonical or item.item_raw),
    )


def _coverage(
    tables: list[TableGrid],
    bindings: dict[str, ColumnBindingResult],
    items: list[ItemInventoryEntry],
    unknown: list[dict],
) -> dict:
    measure_total = 0
    measure_mapped = 0
    unmapped_columns = 0
    for bound in bindings.values():
        for item in bound.bindings:
            if item.role != "measure":
                continue
            measure_total += 1
            if item.item_family not in {"unknown", "inspection"} and item.property:
                measure_mapped += 1
        unmapped_columns += len(bound.unmapped_columns)
    return {
        "tables": len(tables),
        "items": len(items),
        "confirmed": sum(1 for item in items if item.status == "confirmed"),
        "probable": sum(1 for item in items if item.status == "probable"),
        "ambiguous": sum(1 for item in items if item.status == "ambiguous"),
        "unknown_candidates": len(unknown),
        "measure_columns_total": measure_total,
        "measure_columns_mapped": measure_mapped,
        "measure_column_coverage": round(
            measure_mapped / measure_total if measure_total else 0.0, 4
        ),
        "unmapped_columns": unmapped_columns,
    }


def _column_by_keyword(table: TableGrid, keywords: tuple[str, ...]) -> int | None:
    for index, path in enumerate(table.header_paths):
        text = " ".join(path)
        if any(keyword in text for keyword in keywords):
            return index
    return None


def _column_by_exact(table: TableGrid, labels: tuple[str, ...]) -> int | None:
    for index, path in enumerate(table.header_paths):
        if path and path[-1].strip() in labels:
            return index
    return None


def _clean_item_name(value: str | None) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    text = text.splitlines()[0]
    text = re.split(r"[。；;]", text)[0]
    text = text.split("*")[0]
    text = text.replace("'", "").replace("’", "")
    text = re.sub(r"^[a-z](?=[\u4e00-\u9fff])", "", text)
    text = _TEXTCIRCLED_RE.sub("", text)
    text = _PAREN_RE.sub("", text)
    text = _TRAILING_UNIT_RE.sub("", text).strip()
    text = text.rstrip("/ ").strip()
    footnote = _FOOTNOTE_TAIL_RE.match(text)
    if footnote:
        text = footnote.group(1)
    text = text.strip(" ：:，,、-—")
    if len(text) < 2 or len(text) > 30:
        return None
    if is_numeric_like(text):
        return None
    if text in _ITEM_NOISE:
        return None
    if "类型" in text:
        return None
    if "除" in text and "外" in text:
        return None
    if any(text.endswith(suffix) for suffix in _SUBJECT_SUFFIXES):
        return None
    if any(text.startswith(prefix) for prefix in _ITEM_STOP_PREFIX):
        return None
    if re.search(r"[。，；：]", text):
        return None
    return text


def _clean_method(value: str | None) -> str | None:
    text = clean_text(value)
    if not text or len(text) > 20 or text in {"-", "—", "–", "/"}:
        return None
    # Clause references ("见8.2") are resolved later from clause text.
    if re.match(r"^(?:见|参见|按)\s*\d", text):
        return None
    if not STD_RE.search(text) and not re.search(r"[\u4e00-\u9fff]", text):
        return None
    return text


def _clean_aux_cell(value: str | None) -> str | None:
    text = clean_text(value)
    if not text:
        return None
    text = text.splitlines()[0]
    if len(text) > 40 or re.search(r"[。；;]", text):
        return None
    return text


def _dedupe_unknown(items: list[dict]) -> list[dict]:
    seen: set[tuple] = set()
    result: list[dict] = []
    for item in items:
        key = (item.get("raw"), item.get("source"))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result
