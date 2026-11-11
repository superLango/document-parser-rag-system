"""Find the correct value in the source document, so users only confirm.

A feedback like "standard number is wrong" or "Rm requirement is wrong" must
not bounce back as "please supply the expected value". This module derives the
proposal from artifacts the engine already produced:

* table cell behind an extracted value (evidence row/col -> tablegrid);
* cover-page standard number and title;
* clause/page text around the named property, item or field.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field as dc_field
from pathlib import Path
from typing import Any

from ..contracts import DocumentResult
from .contracts import FeedbackTarget
from .evidence import (
    GENERIC_TOKENS,
    keyword_tokens,
    load_clause_rows,
    load_evidence_rows,
    load_pages,
    load_table_grid,
)

STANDARD_NO_RE = re.compile(
    r"(?:GB|GJB|HB|YS|JB|QB|TB|YY|SN|CB|CJ|JT|SY|HG|SH|ASTM|ASME|ISO|JIS|EN|DIN|BS|NF|API|AWS|MIL)"
    r"[\s/]?[A-Z]*\s*\d+(?:\.\d+)*\s*[-—–]\s*\d{2,4}",
    re.IGNORECASE,
)
FIELD_WORDS = (
    "标准编号",
    "标准号",
    "文件编号",
    "标准代号",
    "标准名称",
    "标题",
    "版本",
)
MISSING_WORDS = (
    "没有解析",
    "没解析",
    "未解析",
    "未提取",
    "没提取",
    "没有提取",
    "漏了",
    "缺失",
    "没有",
    "缺少",
    "不正确",
    "不对",
    "错误",
)


@dataclass
class Correction:
    found: bool
    value: str | None = None
    field: str | None = None
    method: str = ""
    reason: str = ""
    evidence: list[dict[str, Any]] = dc_field(default_factory=list)
    checked: list[str] = dc_field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "found": self.found,
            "value": self.value,
            "field": self.field,
            "method": self.method,
            "reason": self.reason,
            "evidence": self.evidence,
            "checked": self.checked,
        }


def _quote(page_no: int | None, quote: str, **extra: Any) -> dict[str, Any]:
    payload = {"page_no": page_no, "quote": quote[:300]}
    payload.update({key: value for key, value in extra.items() if value is not None})
    return payload


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _page_text(job_dir: str | Path | None) -> tuple[str, int]:
    pages = load_pages(job_dir)
    if not pages:
        return "", 1
    first = pages[0]
    return str(first.get("markdown") or ""), int(first.get("page_no") or 1)


def resolve_correction(
    result: DocumentResult,
    job_dir: str | Path | None,
    *,
    description: str,
    target: FeedbackTarget,
    expected: str | None,
    category: str = "other",
) -> Correction:
    text = f"{description} {target.feature or ''}"
    checked: list[str] = []

    # 1. Explicit expected value: accept only if the source really contains it.
    if expected:
        location = _find_text(result, job_dir, expected)
        if location is not None:
            return Correction(
                found=True,
                value=expected,
                field=target.property,
                method="expected_verified",
                reason="用户给出的期望值已在原文中核对到",
                evidence=[location],
                checked=["原文检索"],
            )
        checked.append(f"期望值 {expected} 未在原文中检索到")

    # 2. Document metadata: standard number / title / version.
    if _mentions_metadata(text):
        correction = _resolve_document_meta(result, job_dir, text, checked)
        if correction is not None:
            return correction

    # 3. Field value: read the source cell the extracted value came from.
    if target.record_id and target.property:
        correction = _resolve_field_cell(result, job_dir, target, checked)
        if correction is not None:
            return correction

    # 4. Missing item / field / requirement: search the document text.
    correction = _resolve_from_document(result, job_dir, text, target, checked)
    if correction is not None:
        return correction

    return Correction(
        found=False,
        reason="未在原文、表网格、条款或证据中找到可确认的正解",
        checked=checked,
    )


def _mentions_metadata(text: str) -> bool:
    return any(word in text for word in FIELD_WORDS)


def _resolve_document_meta(
    result: DocumentResult,
    job_dir: str | Path | None,
    text: str,
    checked: list[str],
) -> Correction | None:
    page_text, page_no = _page_text(job_dir)
    checked.append(f"已读取第 {page_no} 页原文（{len(page_text)} 字）")
    if not page_text:
        return None

    if "标准名称" in text or "标题" in text:
        title = _cover_title(page_text)
        checked.append("已解析首页标题行")
        if title and _normalize(title) != _normalize(result.document.title):
            return Correction(
                found=True,
                value=title,
                field="title",
                method="cover_page",
                reason="首页标题行与当前标准名称不一致",
                evidence=[_quote(page_no, title)],
                checked=checked,
            )

    candidates = [item.strip() for item in STANDARD_NO_RE.findall(page_text)]
    from ..ingest import parse_standard_no

    parsed = parse_standard_no(page_text.replace("\n", " "))
    if parsed:
        candidates.insert(0, parsed)
    checked.append(f"首页命中标准编号候选 {len(candidates)} 个")
    current = _normalize(result.document.standard_no or "")
    for candidate in candidates:
        normalized = _normalize(candidate)
        if normalized and normalized != current:
            return Correction(
                found=True,
                value=candidate,
                field="standard_no",
                method="cover_page",
                reason="首页标准编号与当前解析结果不一致",
                evidence=[_quote(page_no, _around(page_text, candidate))],
                checked=checked,
            )
    return None


def _cover_title(text: str) -> str | None:
    for line in text.splitlines():
        cleaned = line.strip().strip("#").strip()
        if len(cleaned) < 5 or len(cleaned) > 80:
            continue
        if any(word in cleaned for word in ("标准", "规范", "技术条件")):
            return cleaned
    return None


def _resolve_field_cell(
    result: DocumentResult,
    job_dir: str | Path | None,
    target: FeedbackTarget,
    checked: list[str],
) -> Correction | None:
    record = next(
        (item for item in result.records if item.record_id == target.record_id),
        None,
    )
    if record is None:
        checked.append(f"记录 {target.record_id} 不在结果中")
        return None
    value = record.properties.get(target.property or "")
    if value is None:
        checked.append(f"字段 {target.property} 不在记录中（可能属于缺失项）")
        return None

    table_id = target.table_id or record.source_table_id or ""
    checked.append(f"已定位记录 {record.record_id} / 字段 {target.property}")
    evidence_rows = {
        str(row.get("evidence_id")): row for row in load_evidence_rows(job_dir)
    }
    ref = evidence_rows.get(value.evidence_id or "")
    grid = load_table_grid(job_dir, table_id)
    if grid is None:
        checked.append(f"表 {table_id} 的原始网格不可用")
        return None

    rows = grid.get("rows") or []
    candidates: list[tuple[int, int, str]] = []
    if ref and ref.get("row") is not None and ref.get("col") is not None:
        for row_index in {int(ref["row"]), int(ref["row"]) - 1}:
            for col_index in {int(ref["col"]), int(ref["col"]) - 1}:
                if not (0 <= row_index < len(rows)):
                    continue
                row = rows[row_index]
                if not isinstance(row, list) or not (0 <= col_index < len(row)):
                    continue
                cell = str(row[col_index] or "").strip()
                if cell:
                    candidates.append((row_index, col_index, cell))
    checked.append(f"已读取表 {table_id} 原始网格（证据坐标）")

    for row_index, col_index, cell in candidates:
        if _normalize(cell) and _normalize(cell) != _normalize(
            value.raw or value.text or ""
        ):
            return Correction(
                found=True,
                value=cell,
                field=target.property,
                method="source_cell",
                reason=(
                    f"抽取值与表 {table_id} 第 {row_index + 1} 行第 {col_index + 1} 列"
                    "原文不一致"
                ),
                evidence=[
                    _quote(
                        grid.get("page_no"),
                        cell,
                        table_id=table_id,
                        row=row_index,
                        col=col_index,
                    )
                ],
                checked=checked,
            )
    checked.append("原始单元格与当前值一致")
    return None


def _resolve_from_document(
    result: DocumentResult,
    job_dir: str | Path | None,
    text: str,
    target: FeedbackTarget,
    checked: list[str],
) -> Correction | None:
    tokens = [
        token
        for token in keyword_tokens(text)
        if token not in GENERIC_TOKENS and len(token) >= 2
    ]
    if not tokens:
        return None
    clause_best: tuple[int, dict[str, Any], str] | None = None
    for clause in load_clause_rows(job_dir):
        haystack = " ".join(
            [str(clause.get("title") or "")]
            + [
                str(value.get("raw") or value.get("text") or "")
                for value in (clause.get("fields") or {}).values()
                if isinstance(value, dict)
            ]
        )
        score = sum(len(token) for token in tokens if token in haystack)
        if score and re.search(r"(\d|≥|≤|不小于|不大于|不低于|不高于)", haystack):
            score += 4
        if score and (clause_best is None or score > clause_best[0]):
            clause_best = (score, clause, haystack)
    if clause_best is not None:
        _, clause, haystack = clause_best
        checked.append(
            f"已在条款 {clause.get('clause_id')} 中检索到相关要求"
        )
        return Correction(
            found=True,
            value=None,
            field=target.property,
            method="clause",
            reason=f"条款 {clause.get('clause_id')} 包含与反馈相关的原文要求",
            evidence=[
                _quote(
                    int(clause.get("page_no") or 0),
                    haystack,
                    clause_id=str(clause.get("clause_id") or ""),
                )
            ],
            checked=checked,
        )
    pages = load_pages(job_dir)
    best: tuple[int, int, str, str] | None = None
    for page in pages:
        markdown = str(page.get("markdown") or "")
        if not markdown:
            continue
        for token in tokens:
            position = markdown.find(token)
            if position < 0:
                continue
            sentence = _window(markdown, position)
            score = len(token) + (3 if re.search(r"\d", sentence) else 0)
            if best is None or score > best[0]:
                best = (
                    score,
                    int(page.get("page_no") or 0),
                    sentence,
                    token,
                )
    if best is not None:
        _, page_no, sentence, token = best
        checked.append(f"已在第 {page_no} 页检索到“{token}”")
        return Correction(
            found=True,
            value=None,
            field=target.property,
            method="document_search",
            reason=f"原文第 {page_no} 页包含“{token}”的相关描述",
            evidence=[_quote(page_no, sentence)],
            checked=checked,
        )

    headers = []
    for table in result.tables:
        for path in table.header_paths:
            joined = " ".join(part for part in path if part)
            if any(token in joined for token in tokens):
                headers.append((table.table_id, table.page_no, joined))
    if headers:
        table_id, page_no, header = headers[0]
        checked.append(f"已在表 {table_id} 表头检索到匹配字段")
        return Correction(
            found=True,
            value=None,
            field=target.property,
            method="table_header",
            reason=f"表 {table_id} 表头包含匹配字段",
            evidence=[
                _quote(page_no, header, table_id=table_id),
            ],
            checked=checked,
        )
    checked.append("原文与表头均未检索到匹配内容")
    return None


def _find_text(
    result: DocumentResult, job_dir: str | Path | None, needle: str
) -> dict[str, Any] | None:
    target = _normalize(needle)
    if not target:
        return None
    for page in load_pages(job_dir):
        markdown = str(page.get("markdown") or "")
        if target in _normalize(markdown):
            return _quote(
                int(page.get("page_no") or 0),
                _around(markdown, needle),
            )
    for table in result.tables:
        for row_index, row in enumerate(table.rows):
            for col_index, cell in enumerate(row):
                if target and target in _normalize(cell):
                    return _quote(
                        table.page_no,
                        str(cell),
                        table_id=table.table_id,
                        row=row_index,
                        col=col_index,
                    )
    return None


def _window(text: str, position: int, size: int = 160) -> str:
    start = max(0, position - size // 2)
    return re.sub(r"\s+", " ", text[start : start + size]).strip()


def _around(text: str, needle: str, size: int = 160) -> str:
    position = text.find(needle)
    if position < 0:
        return text[:size]
    return _window(text, position, size)


def table_cell(
    job_dir: str | Path | None, table_id: str, row: int, col: int
) -> str | None:
    """Read one cell from the source table grid (used by tests and diagnostics)."""

    grid = load_table_grid(job_dir, table_id)
    if grid is None:
        return None
    rows = grid.get("rows") or []
    if not (0 <= row < len(rows)):
        return None
    row_cells = rows[row]
    if not isinstance(row_cells, list) or not (0 <= col < len(row_cells)):
        return None
    return str(row_cells[col] or "")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))
