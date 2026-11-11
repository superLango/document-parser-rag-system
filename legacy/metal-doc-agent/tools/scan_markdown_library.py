"""Scan the OCR markdown folder into a candidate standards-library catalog.

This does not modify the source folder. It extracts title, page count, document
code, reference-section presence and duplicate information so the registry can
be expanded deliberately instead of blindly adding every OCR file.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_LIB = ROOT.parent / "markdown"
DEFAULT_OUT = ROOT / "data" / "standards_library"

STANDARD_RE = re.compile(
    r"(?P<org>GB/T|GB|GJB/Z|GJB|JB/T|YB/T|HB/Z|HB|NB/T|EJ/T|ASTM|ISO|"
    r"AMS-STD|AMS|ASME|Q/(?:[A-Za-z]+|[A-Za-z0-9]*[A-Za-z])|QJ|JX|MAS|MFS)\s*"
    r"(?P<num>-?\d+(?:\.\d+)*(?:-\d+)?[A-Z]?|[A-Z]\s?-?\d+[A-Za-z]?)"
    r"(?:\s*[-—–:]\s*(?P<year>\d{4}))?"
)
TITLE_RE = re.compile(r"^\s*#\s+(.+)$", re.MULTILINE)
PAGES_RE = re.compile(r"页数\s*[:：]\s*(\d+)")
PAGE_MARK_RE = re.compile(r"<!--\s*page\s*:\s*\d+\s*-->", re.IGNORECASE)
REFERENCE_RE = re.compile(r"规范性引用文件|引用标准|引用文件")
CITATION_CUE_RE = re.compile(r"按照|依据|符合|引用|采用|遵守|参照|参见|代替|起草")

EXCLUDE_MARKERS = (
    "制造大纲",
    "质量保证",
    "质保",
    "质量计划",
    "程序",
    "管理规定",
    "采购合同",
    "会议纪要",
    "检验报告",
    "试验报告",
    "技术协议",
    "技术条件",
    "评定大纲",
    "采购规范",
    "订货技术",
)


def scan_file(path: Path) -> dict:
    raw = path.read_bytes()
    text = raw.decode("utf-8-sig", errors="replace")
    title_match = TITLE_RE.search(text)
    title = _clean(title_match.group(1)) if title_match else _first_line(text)
    pages_match = PAGES_RE.search(text)
    pages = int(pages_match.group(1)) if pages_match else len(PAGE_MARK_RE.findall(text))
    cover_standard = _is_standard_cover(text)
    excluded = any(marker in title for marker in EXCLUDE_MARKERS)
    standard = None
    if cover_standard and not excluded:
        standard = _standard_from_title(title) or _standard_from_head(text)
    reference_section = bool(REFERENCE_RE.search(text[:8000]))
    doc_type = _doc_type(title, standard, cover_standard)
    cited = _cited_standards(text)

    return {
        "file": path.name,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
        "pages": pages,
        "title": title,
        "standard_no": standard["standard_no"] if standard else None,
        "edition": standard["edition"] if standard else None,
        "raw_standard": standard["raw"] if standard else None,
        "doc_type": doc_type,
        "cover_standard": cover_standard,
        "has_reference_section": reference_section,
        "cited_standards": cited,
        "duplicate_of": None,
    }


def _is_standard_cover(text: str) -> bool:
    head = "\n".join(text.splitlines()[:60])
    if any(
        marker in head
        for marker in (
            "中华人民共和国国家标准",
            "国家军用标准",
            "行业标准",
            "企业标准",
            "等效标准号",
        )
    ):
        return True
    first = "\n".join(text.splitlines()[:20])
    return "发布" in head and "实施" in head and bool(STANDARD_RE.search(first))


def _cited_standards(text: str) -> list[str]:
    found: list[str] = []
    for match in STANDARD_RE.finditer(text):
        raw = _clean(match.group(0))
        if raw and raw not in found:
            found.append(raw)
    return found[:80]


def _clean(value: str | None) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", value).strip().strip("*")


def _first_line(text: str) -> str:
    for line in text.splitlines():
        cleaned = _clean(line.lstrip("# ").strip())
        if cleaned and not cleaned.startswith("<!--") and len(cleaned) > 2:
            return cleaned
    return ""


def _standard_from_title(title: str) -> dict | None:
    match = STANDARD_RE.search(title)
    if not match:
        return None
    return _edge(match)


def _standard_from_head(text: str) -> dict | None:
    marks = list(PAGE_MARK_RE.finditer(text))
    head = text[: marks[1].start()] if len(marks) > 1 else text
    matches: list[re.Match[str]] = []
    for line in head.splitlines()[:80]:
        if len(line) >= 180:
            continue
        stripped = line.strip()
        if CITATION_CUE_RE.search(stripped) and "标准号" not in stripped:
            continue
        for match in STANDARD_RE.finditer(stripped):
            leftover = re.sub(
                r"[\s:：#*]", "", stripped[: match.start()] + stripped[match.end() :]
            )
            if len(leftover) > 8 and "标准号" not in stripped:
                continue
            matches.append(match)
    if not matches:
        return None
    best = max(
        matches,
        key=lambda match: (bool(match.group("year")), len(match.group(0))),
    )
    return _edge(best)


def _edge(match: re.Match[str]) -> dict:
    org = _clean(match.group("org")).replace(" ", "")
    number = re.sub(r"\s+", "", _clean(match.group("num")))
    year = _clean(match.group("year"))
    if not year:
        suffix = re.search(r"-(\d{4})$", number)
        if (
            suffix
            and suffix.start() > 0
            and 1900 <= int(suffix.group(1)) <= 2099
        ):
            year = suffix.group(1)
            number = number[: suffix.start()]
    return {
        "raw": _clean(match.group(0)),
        "standard_no": f"{org} {number}",
        "edition": year or None,
    }


def _doc_type(title: str, standard: dict | None, cover_standard: bool) -> str:
    if any(marker in title for marker in EXCLUDE_MARKERS):
        if "制造大纲" in title:
            return "manufacturing_outline"
        if "质量保证" in title or "质保" in title:
            return "quality_assurance"
        if "技术协议" in title or "技术条件" in title:
            return "technical_condition"
        return "internal_document"
    if standard:
        org = standard["standard_no"].split()[0]
        if org in {"GB/T", "GB", "GJB", "GJB/Z", "JB/T", "YB/T", "HB", "HB/Z", "NB/T", "EJ/T"}:
            return "national_or_industry_standard"
        if org in {"ASTM", "ISO", "AMS", "AMS-STD", "ASME"}:
            return "international_standard"
        return "enterprise_standard"
    if cover_standard:
        return "standard_uncertain"
    return "uncatalogued"


def _norm_standard(value: str | None) -> str:
    return re.sub(r"\s+", "", (value or "")).upper()


def _build_index(records: list[dict]) -> dict[str, dict]:
    standards: dict[str, dict] = {}
    for record in records:
        if record.get("duplicate_of"):
            continue
        if record.get("standard_no"):
            entry = standards.setdefault(
                _norm_standard(record["standard_no"]), {"bodies": [], "mentions": []}
            )
            entry["bodies"].append(
                {
                    "file": record["file"],
                    "edition": record.get("edition"),
                    "title": record.get("title"),
                    "doc_type": record.get("doc_type"),
                }
            )
        for raw in record.get("cited_standards") or []:
            match = STANDARD_RE.search(raw)
            if not match:
                continue
            edge = _edge(match)
            entry = standards.setdefault(
                _norm_standard(edge["standard_no"]), {"bodies": [], "mentions": []}
            )
            entry["mentions"].append(
                {
                    "file": record["file"],
                    "edition": edge["edition"],
                    "doc_type": record.get("doc_type"),
                }
            )
    result: dict[str, dict] = {}
    for key, entry in standards.items():
        body_files = {doc["file"] for doc in entry["bodies"]}
        seen: set[tuple[str, str | None]] = set()
        mentions = []
        for doc in entry["mentions"]:
            if doc["file"] in body_files:
                continue
            marker = (doc["file"], doc["edition"])
            if marker in seen:
                continue
            seen.add(marker)
            mentions.append(doc)
        result[key] = {"bodies": entry["bodies"], "mentions": mentions}
    return dict(sorted(result.items()))


def _duplicate_keys(records: list[dict]) -> None:
    seen: dict[tuple[str, str | None, str | None], str] = {}
    for record in records:
        key = (
            re.sub(r"\s+", "", record["title"]).lower(),
            record["standard_no"],
            record["edition"],
        )
        if not record["title"]:
            continue
        if key in seen:
            record["duplicate_of"] = seen[key]
        else:
            seen[key] = record["file"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lib", default=str(DEFAULT_LIB))
    parser.add_argument("--out", default=str(DEFAULT_OUT))
    args = parser.parse_args(argv)
    lib = Path(args.lib)
    out_dir = Path(args.out)
    files = sorted(lib.glob("*.md"))
    if not files:
        print(f"no markdown files under {lib}")
        return 1

    records = [scan_file(path) for path in files]
    _duplicate_keys(records)
    index = _build_index(records)
    body_standards = [key for key, entry in index.items() if entry["bodies"]]

    counts = Counter(record["doc_type"] for record in records)
    with_standard = [record for record in records if record["standard_no"] and not record["duplicate_of"]]
    orgs = Counter(record["standard_no"].split()[0] for record in with_standard)
    duplicates = [record for record in records if record["duplicate_of"]]

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "catalog.json").write_text(
        json.dumps(
            {
                "source": str(lib),
                "files": len(records),
                "unique_with_standard_no": len(with_standard),
                "duplicates": len(duplicates),
                "by_type": dict(counts),
                "by_org": dict(orgs),
                "records": records,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (out_dir / "index.json").write_text(
        json.dumps(
            {
                "source": str(lib),
                "files": len(records),
                "standards": index,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    lines = [
        "# OCR Markdown 语料目录",
        "",
        f"- 源目录：`{lib}`",
        f"- Markdown 文件：{len(records)}",
        "- 说明：所有文件都是解析输入；本目录只标注文件在跨标准补全中的角色（正文 / 引用 / 未识别）。",
        f"- 去重后可识别标准号：{len(with_standard)}",
        f"- 重复文件：{len(duplicates)}",
        f"- 语料标准号索引：{len(index)} 个（其中 {len(body_standards)} 个有正文）",
        "",
        "## 文档类型",
        "",
        "| 类型 | 数量 |",
        "|---|---|",
    ]
    for name, count in counts.most_common():
        lines.append(f"| {name} | {count} |")
    lines.extend(["", "## 标准号前缀", "", "| 前缀 | 数量 |", "|---|---|"])
    for name, count in orgs.most_common():
        lines.append(f"| {name} | {count} |")
    lines.extend(
        [
            "",
            "## 语料标准号索引（有正文）",
            "",
            "| 标准号 | 正文文件 | 引用文件数 |",
            "|---|---|---|",
        ]
    )
    for key in sorted(body_standards):
        entry = index[key]
        files_text = "、".join(doc["file"] for doc in entry["bodies"])
        lines.append(f"| {key} | {files_text} | {len(entry['mentions'])} |")
    lines.extend(
        [
            "",
            "## 可作为要求正文的文档（去重、封面有标准号）",
            "",
            "| 文件 | 标准号 | 版本 | 页数 | 标题 |",
            "|---|---|---|---|---|",
        ]
    )
    for record in sorted(with_standard, key=lambda item: (item["standard_no"], item["edition"] or "")):
        lines.append(
            f"| {record['file']} | {record['standard_no']} | {record['edition'] or '-'} | "
            f"{record['pages']} | {record['title'][:60]} |"
        )
    lines.extend(
        [
            "",
            "## 封面未识别标准号（不影响解析）",
            "",
            "以下文件仍作为解析输入；仅表示其封面未识别出标准号，不能充当被引用标准的正文。",
            "",
            "| 文件 | 类型 | 页数 | 引用标准数 | 标题 |",
            "|---|---|---|---|---|",
        ]
    )
    for record in records:
        if record["standard_no"] or record["duplicate_of"]:
            continue
        lines.append(
            f"| {record['file']} | {record['doc_type']} | {record['pages']} | "
            f"{len(record['cited_standards'])} | {record['title'][:60]} |"
        )
    (out_dir / "catalog.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(
        f"files={len(records)} unique_standard={len(with_standard)} "
        f"duplicates={len(duplicates)} indexed_standards={len(index)} "
        f"with_body={len(body_standards)}"
    )
    print("by_type", dict(counts))
    print("by_org", dict(orgs))
    print(f"out={out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
