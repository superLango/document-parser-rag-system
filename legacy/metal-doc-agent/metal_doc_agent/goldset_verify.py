"""Verify golden-set evidence locators against source pages and TableGrids.

Annotation values must point at a real cell or clause quote. This check catches
hand-editing mistakes and fabricated quotes, not semantic truth.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .contracts import Page, TableGrid
from .eval.metrics import norm_text
from .goldset import GoldDocument, GoldEvidence

MAX_ISSUES = 500


@dataclass
class GoldVerification:
    ok: bool
    checked: int
    issues: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "checked": self.checked, "issues": self.issues}


def verify_document_evidence(
    gold: GoldDocument, run_dir: str | Path
) -> GoldVerification:
    base = Path(run_dir)
    result_path = base / "result.json"
    pages_path = base / "pages.json"
    if not result_path.exists() or not pages_path.exists():
        return GoldVerification(
            ok=False,
            checked=0,
            issues=[{"code": "RUN_MISSING", "doc_id": gold.doc_id, "path": str(base)}],
        )

    pages = {
        page.page_no: page
        for page in (
            Page.model_validate(item)
            for item in json.loads(pages_path.read_text(encoding="utf-8"))
        )
    }
    result = json.loads(result_path.read_text(encoding="utf-8"))
    tables = {
        table["table_id"]: TableGrid.model_validate(table)
        for table in result.get("tables", [])
    }

    issues: list[dict[str, Any]] = []
    checked = 0
    for evidence, prefix in _iter_evidence(gold):
        checked += 1
        _check_one(gold.doc_id, prefix, evidence, pages, tables, issues)
        if len(issues) >= MAX_ISSUES:
            break
    return GoldVerification(ok=not issues, checked=checked, issues=issues)


def _iter_evidence(gold: GoldDocument) -> Iterable[tuple[GoldEvidence, str]]:
    for table in gold.tables:
        for record in table.records:
            for name, value in record.properties.items():
                yield value.evidence, f"{table.table_id}/{record.record_id}/{name}"
        for index, item in enumerate(table.inspection_items):
            yield item.evidence, f"{table.table_id}/inspection[{index}]/{item.item}"
        for index, item in enumerate(table.classification_items):
            yield item.evidence, f"{table.table_id}/classification[{index}]/{item.grade}"
    for clause in gold.clauses:
        for name, value in clause.fields.items():
            yield value.evidence, f"clause {clause.clause_id}/{name}"
        if clause.evidence:
            yield clause.evidence, f"clause {clause.clause_id}"


def _check_one(
    doc_id: str,
    prefix: str,
    evidence: GoldEvidence,
    pages: dict[int, Page],
    tables: dict[str, TableGrid],
    issues: list[dict[str, Any]],
) -> None:
    page = pages.get(evidence.page_no)
    if page is None:
        issues.append(
            {
                "code": "PAGE_MISSING",
                "doc_id": doc_id,
                "location": prefix,
                "page_no": evidence.page_no,
            }
        )
        return
    quote = norm_text(evidence.quote)
    if not quote:
        issues.append(
            {"code": "QUOTE_EMPTY", "doc_id": doc_id, "location": prefix}
        )
        return

    if evidence.table_id:
        table = tables.get(evidence.table_id)
        if table is None:
            issues.append(
                {
                    "code": "TABLE_MISSING",
                    "doc_id": doc_id,
                    "location": prefix,
                    "table_id": evidence.table_id,
                }
            )
            return
        if evidence.row is None or evidence.col is None:
            issues.append(
                {
                    "code": "LOCATOR_MISSING",
                    "doc_id": doc_id,
                    "location": prefix,
                    "table_id": evidence.table_id,
                }
            )
            return
        if evidence.row < 0 or evidence.row >= len(table.rows):
            issues.append(
                {
                    "code": "ROW_OUT_OF_RANGE",
                    "doc_id": doc_id,
                    "location": prefix,
                    "row": evidence.row,
                }
            )
            return
        row = table.rows[evidence.row]
        if evidence.col < 0 or evidence.col >= len(row):
            issues.append(
                {
                    "code": "COL_OUT_OF_RANGE",
                    "doc_id": doc_id,
                    "location": prefix,
                    "col": evidence.col,
                }
            )
            return
        cell = norm_text(row[evidence.col])
        if quote not in cell and cell not in quote:
            issues.append(
                {
                    "code": "QUOTE_MISMATCH",
                    "doc_id": doc_id,
                    "location": prefix,
                    "table_id": evidence.table_id,
                    "row": evidence.row,
                    "col": evidence.col,
                    "cell": row[evidence.col],
                    "quote": evidence.quote,
                }
            )
        return

    if evidence.clause_id:
        page_text = norm_text(page.markdown)
        if quote not in page_text:
            issues.append(
                {
                    "code": "CLAUSE_QUOTE_MISMATCH",
                    "doc_id": doc_id,
                    "location": prefix,
                    "clause_id": evidence.clause_id,
                    "quote": evidence.quote,
                }
            )
        return

    issues.append(
        {
            "code": "LOCATOR_MISSING",
            "doc_id": doc_id,
            "location": prefix,
        }
    )
