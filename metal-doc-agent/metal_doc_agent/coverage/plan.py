"""Coverage templates and coverage plan.

Coverage answers a different question from extraction accuracy: did we look
everywhere the schema says we should look? A field can be found, explicitly
missing, ambiguous, or not applicable to this document type.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..contracts import CoverageItem, CoveragePlan, DocumentMeta, Evidence, Record, TableGrid
from ..document_types import DocumentTypeResult
from ..settings import Settings
from ..tablegrid.normalize import ELEMENTS

MECHANICAL_PROPS = {"Rm", "Rp0.2", "A", "Z", "KV2", "HB", "HRC", "HRB", "HV", "E"}

DEFAULT_TEMPLATES: dict[str, list[dict[str, Any]]] = {
    "product_full": [
        {"field": "document.standard_no", "required": True, "match": "document", "keywords": ["范围", "规范性引用文件"]},
        {"field": "records.grade", "required": True, "match": "grade", "keywords": ["牌号", "技术要求"]},
        {"field": "records.chemical_composition", "required": True, "match": "chemical", "keywords": ["化学成分"]},
        {"field": "records.mechanical_properties", "required": True, "match": "mechanical", "keywords": ["力学性能", "试验方法"]},
        {"field": "records.heat_treatment", "required": False, "match": "condition", "keywords": ["热处理", "交货状态"]},
        {"field": "records.inspection", "required": False, "match": "inspection", "keywords": ["检验规则", "取样"]},
    ],
    "gjb": [
        {"field": "document.standard_no", "required": True, "match": "document", "keywords": ["范围"]},
        {"field": "records.grade", "required": True, "match": "grade", "keywords": ["牌号", "技术要求"]},
        {"field": "records.chemical_composition", "required": True, "match": "chemical", "keywords": ["化学成分"]},
        {"field": "records.mechanical_properties", "required": True, "match": "mechanical", "keywords": ["力学性能"]},
        {"field": "records.inspection", "required": True, "match": "inspection", "keywords": ["检验规则", "取样"]},
    ],
    "enterprise": [
        {"field": "document.standard_no", "required": True, "match": "document", "keywords": ["范围"]},
        {"field": "records.grade", "required": True, "match": "grade", "keywords": ["牌号", "技术要求"]},
        {"field": "records.chemical_composition", "required": False, "match": "chemical", "keywords": ["化学成分"]},
        {"field": "records.mechanical_properties", "required": False, "match": "mechanical", "keywords": ["力学性能"]},
        {"field": "records.heat_treatment", "required": False, "match": "condition", "keywords": ["热处理"]},
    ],
    "classification": [
        {"field": "document.standard_no", "required": True, "match": "document", "keywords": ["范围"]},
        {"field": "records.grade", "required": True, "match": "grade", "keywords": ["牌号", "分类"]},
    ],
    "technical_agreement": [
        {"field": "document.standard_no", "required": True, "match": "document", "keywords": ["范围"]},
        {"field": "records.grade", "required": True, "match": "grade", "keywords": ["牌号", "材料"]},
    ],
    "purchase": [
        {"field": "document.standard_no", "required": True, "match": "document", "keywords": ["范围"]},
        {"field": "records.grade", "required": True, "match": "grade", "keywords": ["牌号"]},
        {"field": "records.chemical_composition", "required": True, "match": "chemical", "keywords": ["化学成分"]},
        {"field": "records.mechanical_properties", "required": True, "match": "mechanical", "keywords": ["力学性能"]},
    ],
}


def load_templates(settings: Settings | None = None) -> dict[str, list[dict[str, Any]]]:
    templates = {key: list(value) for key, value in DEFAULT_TEMPLATES.items()}
    if settings is None:
        return templates
    path = settings.project_root / "configs" / "coverage_templates.json"
    if not path.exists():
        return templates
    try:
        overrides = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return templates
    if isinstance(overrides, dict):
        for key, value in overrides.items():
            if isinstance(value, list):
                templates[key] = value
    return templates


def build_coverage(
    document: DocumentMeta,
    records: list[Record],
    tables: list[TableGrid],
    evidence: list[Evidence],
    template: str = "product_full",
    settings: Settings | None = None,
    outline_titles: list[str] | None = None,
    document_type: DocumentTypeResult | None = None,
) -> CoveragePlan:
    if document_type is not None and document_type.not_applicable:
        # Heat-treatment check plans describe 检查组别 × 抽检比例, not product
        # properties. Reporting every product field as "not_applicable" is
        # honest; projecting them would create empty rows.
        return CoveragePlan(
            standard_no=document.standard_no,
            template=template,
            items=[
                CoverageItem(
                    field=str(config.get("field", "")),
                    required=bool(config.get("required", True)),
                    status="not_applicable",
                    reason=f"文档类型「{document_type.label}」不适用产品字段投影",
                )
                for config in load_templates(settings).get(
                    template, DEFAULT_TEMPLATES["product_full"]
                )
            ],
        )

    templates = load_templates(settings)
    items_config = templates.get(template, templates["product_full"])
    evidence_ids = {item.evidence_id for item in evidence}
    titles = outline_titles or []

    items: list[CoverageItem] = []
    for config in items_config:
        field = str(config.get("field", ""))
        required = bool(config.get("required", True))
        match = str(config.get("match", ""))
        keywords = [str(key) for key in config.get("keywords", [])]

        status, matched_evidence, reason = _match_status(
            match=match,
            document=document,
            records=records,
            tables=tables,
            evidence_ids=evidence_ids,
        )
        expected = [
            title for title in titles if any(keyword in title for keyword in keywords)
        ][:5]

        items.append(
            CoverageItem(
                field=field,
                required=required,
                status=status,
                expected_locations=expected,
                evidence=matched_evidence[:5],
                reason=reason,
            )
        )

    return CoveragePlan(standard_no=document.standard_no, template=template, items=items)


def _match_status(
    match: str,
    document: DocumentMeta,
    records: list[Record],
    tables: list[TableGrid],
    evidence_ids: set[str],
) -> tuple[str, list[str], str | None]:
    if match == "document":
        if document.standard_no:
            return "found", [], None
        return "missing", [], "standard_no not parsed"

    if match == "grade":
        grades = [record.grade for record in records if record.grade]
        if grades:
            return "found", [], None
        return "missing", [], "no grade records"

    if match == "chemical":
        values = [
            value
            for record in records
            for key, value in record.properties.items()
            if key in ELEMENTS
        ]
        if values:
            evidence = [v.evidence_id for v in values if v.evidence_id in evidence_ids]
            return "found", evidence, None
        has_table = any(table.profile == "chemical_composition" for table in tables)
        if has_table:
            return "ambiguous", [], "table detected but no chemical values extracted"
        # No chemical table at all: for documents whose tables are confidently
        # profiled, chemistry is not applicable rather than missing. Unknown
        # tables keep the conservative "missing" so detection gaps stay visible.
        if tables and not _has_unknown(tables):
            return "not_applicable", [], "document has no chemical composition table"
        return "missing", [], "no chemical table or values"

    if match == "mechanical":
        values = [
            value
            for record in records
            for key, value in record.properties.items()
            if key in MECHANICAL_PROPS
        ]
        if values:
            evidence = [v.evidence_id for v in values if v.evidence_id in evidence_ids]
            return "found", evidence, None
        has_table = any(table.profile == "mechanical_properties" for table in tables)
        if has_table:
            return "ambiguous", [], "table detected but no mechanical values extracted"
        if tables and not _has_unknown(tables):
            return "not_applicable", [], "document has no mechanical properties table"
        return "missing", [], "no mechanical table or values"

    if match == "condition":
        conditions = [record.condition or record.grade_level for record in records]
        if any(conditions):
            return "found", [], None
        return "missing", [], "no condition/heat-treatment values"

    if match == "inspection":
        inspection_tables = [table for table in tables if table.profile == "inspection"]
        if inspection_tables:
            return "ambiguous", [], "inspection table detected; clause extraction not implemented in mock mode"
        if tables and not _has_unknown(tables):
            return "not_applicable", [], "document has no inspection table"
        return "missing", [], "no inspection table"

    return "missing", [], "unknown coverage matcher"


def _has_unknown(tables: list[TableGrid]) -> bool:
    return any(table.profile == "unknown" for table in tables)
