"""Demand-driven cross-standard expansion (P2/P3).

A task is only expanded when the current document defers a named parameter to
another standard. The referenced standard must already exist as OCR markdown in
the local corpus. Expansion is deterministic: locate clause/table, read the
value, keep provenance. No value is invented.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .contracts import (
    ClauseRecord,
    CrossStandardTask,
    DocumentMeta,
    Evidence,
    Page,
    TableGrid,
)
from .extraction.clauses import extract_clauses
from .tablegrid import extract_tables
from .tablegrid.normalize import clean_text

PAGE_MARK_RE = re.compile(r"<!--\s*page:\s*(\d+)\s*-->")
NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
UNIT_RE = re.compile(r"(mm|cm|MPa|GPa|%|℃|°C|K|h|min|s|J|HRC|HBW?)")
VALUE_RE = re.compile(
    r"(?:为|取|按|不小于|不大于|≤|≥|=|:|：)?\s*"
    r"(?P<value>[-+]?\d+(?:\.\d+)?)\s*(?P<unit>mm|cm|MPa|GPa|%|℃|°C|K|h|min|s|J)?"
)
TEXT_VALUE_RE = re.compile(
    r"(?:为|取|按|采用)\s*(?P<value>[A-Za-z0-9ⅠⅡⅢⅣⅤ一二三四五六七八九十]{1,8}(?:级|类)?)"
)
TABLE_REF_RE = re.compile(r"表\s*(?P<num>[A-Za-z]?\.?\s*\d+(?:\.\d+)?)")


def load_reference_pages(path: Path) -> list[Page]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    parts = PAGE_MARK_RE.split(text)
    if len(parts) <= 1:
        return [Page(page_no=1, markdown=text)]
    pages: list[Page] = []
    for index in range(1, len(parts), 2):
        try:
            page_no = int(parts[index])
        except ValueError:
            page_no = len(pages) + 1
        pages.append(Page(page_no=page_no, markdown=parts[index + 1]))
    return pages


def _reference_path(project_root: Path, source_file: str | None) -> Path | None:
    if not source_file:
        return None
    name = Path(source_file).name
    candidates = (
        project_root.parent / "markdown" / name,
        project_root / "markdown" / name,
        Path(source_file),
    )
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _clause_text(clause: ClauseRecord, evidence: dict[str, Evidence]) -> str:
    quotes = [
        evidence[evidence_id].quote
        for evidence_id in clause.evidence
        if evidence_id in evidence and evidence[evidence_id].quote
    ]
    return clean_text(" ".join(quotes))


def _extract_from_text(text: str, field: str) -> dict[str, Any] | None:
    if not text or not field:
        return None
    index = text.find(field)
    if index < 0:
        return None
    window = text[index : index + 120]
    tail = window[len(field) :]
    for match in VALUE_RE.finditer(tail):
        # "表 4" / "第 5 章" are references, not requirement values.
        if tail[: match.start()].rstrip().endswith(("表", "图", "第", "附录")):
            continue
        value = match.group("value")
        unit = match.group("unit") or ""
        return {
            "field": field,
            "value": value,
            "unit": unit,
            "requirement": f"{value}{unit}",
            "source_text": window[:120],
            "confidence": 1.0,
        }
    text_match = TEXT_VALUE_RE.search(tail)
    if text_match:
        value = text_match.group("value")
        return {
            "field": field,
            "value": value,
            "unit": "",
            "requirement": value,
            "source_text": window[:120],
            "confidence": 0.9,
        }
    return None


def _extract_field(
    text: str, field: str, task: CrossStandardTask
) -> dict[str, Any] | None:
    """Clause-level references defer the whole requirement, not one value."""

    if field == "标准要求":
        needle = clean_text(task.inspection_item or "")
        if not needle or needle not in text:
            return None
        if not re.search(r"应|不得|不允许|≤|≥|不大于|不小于|按表|应符合", text):
            return None
        return {
            "field": "标准要求",
            "value": "",
            "unit": "",
            "requirement": text[:200],
            "source_text": text[:160],
            "confidence": 0.85,
        }
    return _extract_from_text(text, field)


def _locate_in_clauses(
    clauses: list[ClauseRecord],
    evidence: dict[str, Evidence],
    task: CrossStandardTask,
) -> tuple[ClauseRecord | None, dict[str, Any] | None]:
    if task.clause_id:
        for clause in clauses:
            if clause.clause_id == task.clause_id:
                for field in task.missing_fields:
                    result = _extract_field(
                        _clause_text(clause, evidence), field, task
                    )
                    if result:
                        return clause, result
    keywords = [field for field in task.missing_fields if field]
    if task.inspection_item:
        keywords.append(task.inspection_item)
    for clause in clauses:
        text = f"{clause.title or ''} {_clause_text(clause, evidence)}"
        if not any(keyword in text for keyword in keywords):
            continue
        for field in task.missing_fields:
            result = _extract_field(text, field, task)
            if result:
                return clause, result
    return None, None


def _locate_in_tables(
    tables: list[TableGrid],
    task: CrossStandardTask,
    quote: str | None,
) -> tuple[TableGrid | None, dict[str, Any] | None]:
    numbers = {match.group("num").replace(" ", "") for match in TABLE_REF_RE.finditer(quote or "")}
    candidates: list[TableGrid] = []
    for table in tables:
        caption = clean_text(table.caption)
        caption_match = TABLE_REF_RE.search(caption)
        if caption_match and caption_match.group("num").replace(" ", "") in numbers:
            candidates.append(table)
    if not candidates and numbers:
        # Caption-less tables: fall back to document order.
        for number in numbers:
            if number.isdigit() and int(number) <= len(tables):
                candidates.append(tables[int(number) - 1])
    candidates.extend(table for table in tables if table not in candidates)
    for table in candidates:
        headers = [
            clean_text(" ".join(path)) for path in table.header_paths
        ]
        for field in task.missing_fields:
            for col, header in enumerate(headers):
                if field not in header:
                    continue
                for row in table.rows[table.header_rows :]:
                    if col >= len(row):
                        continue
                    value = clean_text(row[col])
                    if not value:
                        continue
                    match = NUMBER_RE.search(value)
                    if not match:
                        continue
                    unit_match = UNIT_RE.search(value)
                    return table, {
                        "field": field,
                        "value": match.group(0),
                        "unit": unit_match.group(0) if unit_match else "",
                        "requirement": value,
                        "source_text": " | ".join(
                            clean_text(cell) for cell in row if clean_text(cell)
                        )[:160],
                        "confidence": 0.9,
                        "table_id": table.table_id,
                        "page_no": table.page_no,
                    }
    return None, None


def _expand_one(
    task: CrossStandardTask,
    reference_pages: list[Page],
    reference_doc: DocumentMeta,
) -> None:
    clause_output = extract_clauses(reference_pages, reference_doc)
    evidence = {item.evidence_id: item for item in clause_output.evidence}
    tables = extract_tables(reference_pages)
    clause, result = _locate_in_clauses(
        clause_output.clauses, evidence, task
    )
    table: TableGrid | None = None
    if result is None:
        table, result = _locate_in_tables(tables, task, task.quote)
    if result is None:
        task.error = "未在来源标准中定位到缺失字段"
        return
    task.expansion = {
        "clause_id": clause.clause_id if clause is not None else task.clause_id,
        "table_id": (result.get("table_id") or (table.table_id if table else None)),
        "page_no": (result.get("page_no") or (clause.page_no if clause else task.page_no)),
        "extracted": [result],
        "confidence": result.get("confidence", 0.9),
    }
    task.provenance = [
        {
            "source_file": task.resolved_source_file,
            "standard_no": task.requirement_standard,
            "edition": task.requirement_edition,
            "clause_id": task.expansion["clause_id"],
            "table_id": task.expansion["table_id"],
            "page_no": task.expansion["page_no"],
            "quote": result.get("source_text", ""),
        }
    ]
    task.merge = {
        "target_field": "标准要求",
        "requirement": result.get("requirement"),
        "applied": False,
        "conflict": False,
    }


def expand_tasks(
    job_dir: Path,
    project_root: Path,
    tasks: list[CrossStandardTask],
    *,
    max_documents: int = 8,
    max_pages: int = 30,
) -> dict[str, Any]:
    """Expand resolved tasks against the local markdown corpus."""

    cache: dict[str, tuple[list[Page], DocumentMeta]] = {}
    expanded = 0
    budget_skipped = 0
    for task in tasks:
        if task.status != "resolved":
            continue
        path = _reference_path(project_root, task.resolved_source_file)
        if path is None:
            task.status = "needs_source"
            task.gap = f"{task.requirement_standard}（本地正文未找到）"
            continue
        key = str(path)
        if key not in cache:
            if len(cache) >= max_documents:
                budget_skipped += 1
                task.gap = f"{task.requirement_standard}（展开预算超限：{max_documents} 份）"
                continue
            pages = load_reference_pages(path)
            if len(pages) > max_pages:
                pages = pages[:max_pages]
                task.gap = (
                    f"{task.requirement_standard}（仅展开前 {max_pages} 页）"
                )
            cache[key] = (
                pages,
                DocumentMeta(
                    doc_id=f"ref-{path.stem[:12]}",
                    source_path=str(path),
                    file_name=path.name,
                ),
            )
        pages, reference_doc = cache[key]
        before = task.error
        _expand_one(task, pages, reference_doc)
        if task.expansion is not None:
            expanded += 1
        elif task.error and task.error != before:
            task.status = "candidate"

    merge_entries = []
    for task in tasks:
        if task.status not in {"resolved", "needed"} or not task.expansion:
            continue
        extracted = (task.expansion.get("extracted") or [{}])[0]
        merge_entries.append(
            {
                "task_id": task.task_id,
                "inspection_item": task.inspection_item,
                "field": extracted.get("field"),
                "requirement": extracted.get("requirement"),
                "confidence": task.expansion.get("confidence", 0.9),
                "provenance": task.provenance,
            }
        )
        task.merge = {
            "target_field": "标准要求",
            "requirement": extracted.get("requirement"),
            "applied": task.expansion.get("confidence", 0.9) >= 0.9,
            "conflict": False,
        }
    summary = {
        "tasks": len(tasks),
        "expanded": expanded,
        "merge_entries": len(merge_entries),
        "budget_skipped": budget_skipped,
        "documents": len(cache),
    }
    target = Path(job_dir)
    (target / "cross_standard_expansion.json").write_text(
        json.dumps(
            [task.model_dump(mode="json") for task in tasks],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (target / "cross_standard_merge.json").write_text(
        json.dumps(merge_entries, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def load_merge_entries(job_dir: Path) -> list[dict[str, Any]]:
    """Load auto-merge entries and confirmed overrides for projection."""

    entries: list[dict[str, Any]] = []
    for name in ("cross_standard_merge.json", "cross_standard_overrides.json"):
        path = Path(job_dir) / name
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, list):
            entries.extend(item for item in data if isinstance(item, dict))
    return entries
