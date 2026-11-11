"""Expand G1.7 clause gold with source-derived schema-relevant clauses."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.coverage.linker import extract_heading_blocks  # noqa: E402
from metal_doc_agent.extraction.clauses import extract_clauses  # noqa: E402
from metal_doc_agent.tablegrid.normalize import clean_text  # noqa: E402
from run_loader import load_run  # noqa: E402

TABLE_RE = re.compile(r"<table\b.*?</table>", re.IGNORECASE | re.DOTALL)
HEADING_RE = re.compile(
    r"^\s*(?:#{1,6}\s*)?"
    r"(?P<id>[A-Z](?:\.\s*\d{1,3}){1,3}|\d{1,2}(?:\.\s*\d{1,3}){0,3})\.?"
    r"(?:\s+|(?=[\u4e00-\u9fff])|$)(?P<title>.*)$"
)
SENTENCE_RE = re.compile(r"[^。；;]+[。；;]?")
BODY_MARKERS = (
    "应进行",
    "应符合",
    "应按",
    "应不",
    "应供",
    "应打",
    "应作",
    "应注明",
    "应满足",
    "应采用",
    "应逐",
    "应检验",
    "应检测",
    "应测量",
    "不允许",
    "需记录",
    "取样数量",
    "取样部位",
    "试验方法",
    "试验温度",
    "判为不合格",
    "方向",
    "纵向",
    "横向",
    "按GB",
    "按GJB",
    "按ASTM",
    "按ISO",
    "按GB ",
    "按GJB ",
    "按ASTM ",
    "按ISO ",
    "按附录",
    "可采用",
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--gold", default=str(ROOT / "goldset" / "g1_7" / "v0"))
    parser.add_argument("--runs", default=str(ROOT / "runs" / "m1.5_qwen"))
    parser.add_argument("--docs", nargs="*", default=None)
    args = parser.parse_args(argv)
    gold_dir = Path(args.gold)
    manifest = json.loads((gold_dir / "manifest.json").read_text(encoding="utf-8"))
    for doc in manifest["docs"]:
        if args.docs and doc["doc_id"] not in args.docs:
            continue
        gold = json.loads((gold_dir / doc["file"]).read_text(encoding="utf-8"))
        run = load_run(Path(args.runs) / doc.get("run", doc["doc_id"]))
        generated = _clauses(run.pages)
        existing = {
            clause["clause_id"]: clause for clause in gold.get("clauses") or []
        }
        existing = {
            clause_id: clause
            for clause_id, clause in existing.items()
            if not (
                clause.get("kind")
                in {"scope", "normative_reference", "terms"}
                and not clause.get("fields")
            )
            and clause.get("quote")
            and (
                clause.get("fields")
                or any(
                    marker in clause.get("quote", "") for marker in BODY_MARKERS
                )
            )
        }
        for clause in generated:
            clause_id = clause["clause_id"]
            if clause_id in existing:
                continue
            existing[clause_id] = clause
        valid_ids = {
            clause.clause_id
            for clause in extract_clauses(run.pages, run.document).clauses
        } | {
            block.clause_id for block in extract_heading_blocks(run.pages)
        }
        existing = {
            clause_id: clause
            for clause_id, clause in existing.items()
            if clause_id in valid_ids
        }
        gold["clauses"] = sorted(
            existing.values(), key=lambda clause: _sort_key(clause["clause_id"])
        )
        (gold_dir / doc["file"]).write_text(
            json.dumps(gold, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        print(f"{doc['doc_id']}: clauses={len(gold['clauses'])} (+{len(generated)})")
    return 0


def _clauses(pages) -> list[dict]:
    blocks: list[dict] = []
    current: dict | None = None
    body: list[str] = []
    text = "\n".join(TABLE_RE.sub("\n", page.markdown) for page in pages)
    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = HEADING_RE.match(line)
        if match:
            if current is not None:
                current["body"] = clean_text(" ".join(body))
                blocks.append(current)
            current = {
                "clause_id": re.sub(r"\s+", "", match.group("id")).rstrip("."),
                "title": clean_text(match.group("title")),
                "body": "",
            }
            body = []
            continue
        if current is not None and line:
            body.append(line)
    if current is not None:
        current["body"] = clean_text(" ".join(body))
        blocks.append(current)

    clauses: list[dict] = []
    for block in blocks:
        title = block["title"]
        clause_body = block["body"]
        text = f"{title} {clause_body}"
        if not text.strip():
            continue
        if not any(marker in text for marker in BODY_MARKERS):
            continue
        kind = _kind(title, clause_body)
        if kind in {"scope", "normative_reference", "terms"}:
            continue
        clauses.append(
            {
                "clause_id": block["clause_id"],
                "kind": kind,
                "quote": _quote(clause_body) if clause_body else title[:160],
                "fields": {},
            }
        )
    return clauses


def _kind(title: str, body: str) -> str:
    text = f"{title} {body}"
    if "范围" in title:
        return "scope"
    if "规范性引用文件" in title:
        return "normative_reference"
    if "术语" in title:
        return "terms"
    if "取样" in title:
        return "sampling"
    if "检验" in title:
        return "inspection"
    if "试验方法" in title or "方法" in title:
        return "test_method"
    if "包装" in title:
        return "packaging"
    if "交货" in title:
        return "delivery"
    if any(marker in text for marker in ("应符合", "应按", "应不", "技术要求")):
        return "technical_requirement"
    return "other"


def _quote(body: str) -> str:
    for sentence in SENTENCE_RE.findall(body):
        if any(marker in sentence for marker in BODY_MARKERS):
            return sentence.strip()[:160]
    return body[:160]


def _sort_key(clause_id: str) -> tuple:
    return (
        tuple(int(part) for part in re.findall(r"\d+", clause_id)),
        clause_id,
    )


if __name__ == "__main__":
    raise SystemExit(main())
