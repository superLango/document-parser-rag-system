"""Build the evidence pack a feedback diagnosis is grounded on.

The pack is deliberately read-only: it collects what the job already produced
(result, pages, table grids, evidence rows, clauses, trace) so the model can
locate a defect and the reply can cite page/table/quotes instead of asking the
user to supply the answer.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from ..contracts import DocumentResult
from .contracts import FeedbackTarget

CJK_RE = re.compile(r"[\u4e00-\u9fff]{2,}")
ASCII_RE = re.compile(r"[A-Za-z][A-Za-z0-9.+-]{1,}")
STOP_TOKENS = {
    "没有",
    "正确",
    "解析",
    "问题",
    "错误",
    "标准",
    "要求",
    "这个",
    "那个",
    "应该",
    "错误",
    "不对",
    "内容",
}
GENERIC_TOKENS = {
    "项目",
    "内容",
    "标准",
    "要求",
    "数据",
    "结果",
    "表格",
    "规定",
    "方法",
    "性能",
    "试验",
    "检验",
    "分析",
}


def keyword_tokens(text: str) -> list[str]:
    """Split a free-text feedback into searchable CJK/ASCII tokens."""

    cleaned = re.sub(r"\s+", " ", str(text or ""))
    tokens: list[str] = []
    for match in CJK_RE.findall(cleaned):
        if match in STOP_TOKENS:
            continue
        tokens.append(match)
        if len(match) > 4:
            for size in (2, 3, 4):
                for index in range(0, len(match) - size + 1):
                    piece = match[index : index + size]
                    if piece not in STOP_TOKENS:
                        tokens.append(piece)
    for match in ASCII_RE.findall(cleaned):
        if match.lower() not in {"pdf", "docx", "md"}:
            tokens.append(match)
    seen: list[str] = []
    for token in tokens:
        if token and token not in seen:
            seen.append(token)
    return seen[:40]


def load_pages(job_dir: str | Path | None) -> list[dict[str, Any]]:
    if job_dir is None:
        return []
    path = Path(job_dir) / "pages.json"
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return []
    return [item for item in payload if isinstance(item, dict)]


def load_evidence_rows(job_dir: str | Path | None) -> list[dict[str, Any]]:
    if job_dir is None:
        return []
    path = Path(job_dir) / "evidence.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def load_clause_rows(job_dir: str | Path | None) -> list[dict[str, Any]]:
    if job_dir is None:
        return []
    path = Path(job_dir) / "clauses.jsonl"
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            rows.append(item)
    return rows


def load_table_grid(job_dir: str | Path | None, table_id: str) -> dict[str, Any] | None:
    if job_dir is None or not table_id:
        return None
    path = Path(job_dir) / "tablegrid" / f"{table_id}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return None
    return payload if isinstance(payload, dict) else None


def _score(text: str, tokens: list[str]) -> int:
    if not text:
        return 0
    lowered = text.lower()
    return sum(lowered.count(token.lower()) for token in tokens)


def _excerpt(text: str, tokens: list[str], size: int = 1200) -> str:
    if not text:
        return ""
    lowered = text.lower()
    position = -1
    for token in tokens:
        found = lowered.find(token.lower())
        if found >= 0:
            position = found
            break
    if position < 0:
        return text[:size]
    start = max(0, position - size // 3)
    return text[start : start + size]


def _record_payload(record, tokens: list[str]) -> dict[str, Any]:
    properties = {
        name: value.raw or value.text or ""
        for name, value in record.properties.items()
    }
    return {
        "record_id": record.record_id,
        "table_id": record.source_table_id,
        "grade": record.grade or record.grade_level,
        "condition": record.condition,
        "properties": properties,
        "_score": _score(
            " ".join(
                [str(record.grade or ""), str(record.condition or "")]
                + list(properties)
                + list(properties.values())
            ),
            tokens,
        ),
    }


def _clause_excerpt(clause: dict[str, Any], size: int = 400) -> str:
    parts = [str(clause.get("title") or "")]
    for value in (clause.get("fields") or {}).values():
        if isinstance(value, dict):
            parts.append(str(value.get("raw") or value.get("text") or ""))
    return " ".join(part for part in parts if part)[:size]


def build_evidence_pack(
    result: DocumentResult,
    job_dir: str | Path | None,
    *,
    description: str = "",
    source_quote: str = "",
    target: FeedbackTarget | None = None,
    expected: str | None = None,
    trace: dict[str, Any] | None = None,
    max_records: int = 40,
    max_tables: int = 60,
    max_pages: int = 3,
) -> dict[str, Any]:
    """Assemble a compact, citable view of everything the system already knows."""

    tokens = keyword_tokens(f"{description} {source_quote or ''}")
    pages = load_pages(job_dir)
    evidence_rows = load_evidence_rows(job_dir)
    clauses = load_clause_rows(job_dir)

    tables = []
    for table in result.tables[:max_tables]:
        haystack = " ".join(
            [table.caption or ""]
            + [" ".join(path) for path in table.header_paths]
            + [str(table.profile or "")]
        )
        tables.append(
            {
                "table_id": table.table_id,
                "page_no": table.page_no,
                "caption": table.caption,
                "profile": table.profile,
                "records": sum(
                    1
                    for record in result.records
                    if record.source_table_id == table.table_id
                ),
                "header": [
                    " ".join(part for part in path if part)
                    for path in table.header_paths[:8]
                ],
                "score": _score(haystack, tokens),
            }
        )
    tables.sort(key=lambda item: (-item["score"], item["table_id"]))

    records = [_record_payload(record, tokens) for record in result.records]
    pinned = {target.record_id} if target and target.record_id else set()
    records.sort(
        key=lambda item: (
            0 if item["record_id"] in pinned else 1,
            -item["_score"],
            item["record_id"],
        )
    )
    for item in records:
        item.pop("_score", None)

    items = [
        {
            "item": item.item,
            "category": item.category,
            "status": item.status,
            "requirement": item.requirement,
            "quantities": item.quantities,
            "method_standard": item.method_standard,
        }
        for item in result.inspection_items
    ]

    page_rows: list[dict[str, Any]] = []
    seen_pages: set[int] = set()
    if pages:
        first = pages[0]
        page_rows.append(
            {
                "page_no": first.get("page_no"),
                "excerpt": (first.get("markdown") or "")[:1500],
                "reason": "首页（标准编号/标题核对）",
            }
        )
        seen_pages.add(int(first.get("page_no") or 1))
    ranked_pages = sorted(
        pages,
        key=lambda item: -_score(str(item.get("markdown") or ""), tokens),
    )
    for page in ranked_pages:
        number = int(page.get("page_no") or 0)
        if number in seen_pages:
            continue
        if _score(str(page.get("markdown") or ""), tokens) <= 0:
            continue
        page_rows.append(
            {
                "page_no": number,
                "excerpt": _excerpt(str(page.get("markdown") or ""), tokens),
                "reason": "命中反馈关键词",
            }
        )
        seen_pages.add(number)
        if len(page_rows) >= max_pages:
            break

    quotes: list[dict[str, Any]] = []
    for row in evidence_rows:
        quote = str(row.get("quote") or "")
        score = _score(quote, tokens)
        if target and target.table_id and row.get("table_id") == target.table_id:
            score += 2
        if score <= 0:
            continue
        quotes.append(
            {
                "page_no": row.get("page_no"),
                "table_id": row.get("table_id"),
                "row": row.get("row"),
                "col": row.get("col"),
                "quote": quote[:300],
                "score": score,
            }
        )
    quotes.sort(key=lambda item: -item["score"])
    for item in quotes:
        item.pop("score", None)

    quality_issues = []
    if result.quality is not None:
        quality_issues = [
            {
                "code": issue.code,
                "level": issue.level,
                "severity": issue.severity,
                "message": issue.message,
                "record_id": issue.record_id,
                "field": issue.field,
            }
            for issue in result.quality.issues[:30]
        ]

    checks = [
        f"已核对 {len(result.tables)} 张表、{len(result.records)} 条记录、"
        f"{len(result.inspection_items)} 个检验项目、{len(result.clauses)} 个条款",
        f"已检索 {len(pages)} 页原文、{len(evidence_rows)} 条证据引文",
    ]
    if target and target.table_id:
        checks.append(f"目标表：{target.table_id}")
    if target and target.record_id:
        checks.append(f"目标记录：{target.record_id}")

    return {
        "document": {
            "doc_id": result.document.doc_id,
            "standard_no": result.document.standard_no,
            "title": result.document.title,
            "version": result.document.version,
            "page_count": result.document.page_count,
            "file_name": result.document.file_name,
        },
        "feedback": {
            "description": description,
            "source_quote": source_quote,
            "expected": expected,
            "category": getattr(target, "category", None),
            "target": target.model_dump(mode="json") if target else {},
        },
        "versions": (trace or {}).get("versions") or {},
        "quality": {
            "status": result.quality.status if result.quality else None,
            "issues": quality_issues,
        },
        "tables": tables,
        "records": records[:max_records],
        "inspection_items": items,
        "clauses": [
            {
                "clause_id": clause.get("clause_id"),
                "title": clause.get("title"),
                "page_no": clause.get("page_no"),
                "kind": clause.get("kind"),
                "excerpt": _clause_excerpt(clause),
            }
            for clause in clauses[:60]
        ],
        "page_excerpts": page_rows,
        "evidence_quotes": quotes[:8],
        "checks": checks,
        "keywords": tokens,
    }
