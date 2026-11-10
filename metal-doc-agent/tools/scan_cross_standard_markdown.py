"""Scan the OCR markdown library for reference-only cross-standard tasks."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.contracts import DocumentMeta, Page  # noqa: E402
from metal_doc_agent.cross_standard import detect_tasks, render_report  # noqa: E402
from metal_doc_agent.standards import load_registry  # noqa: E402

PAGE_RE = re.compile(r"<!--\s*page\s*:\s*(\d+)\s*-->", re.IGNORECASE)


def pages_of(text: str) -> list[Page]:
    matches = list(PAGE_RE.finditer(text))
    if not matches:
        return [Page(page_no=1, markdown=text.strip())]
    pages: list[Page] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        pages.append(Page(page_no=int(match.group(1)), markdown=text[start:end].strip()))
    return pages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lib", default=str(ROOT.parent / "markdown"))
    parser.add_argument("--catalog", default="data/standards_library/catalog.json")
    parser.add_argument("--registry", default="configs/standards.json")
    parser.add_argument("--out", default="data/standards_library/cross_standard_scan")
    args = parser.parse_args(argv)

    lib = Path(args.lib)
    catalog_path = ROOT / args.catalog
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    records = {record["file"]: record for record in catalog["records"]}
    registry = load_registry(ROOT / args.registry)

    tasks = []
    for path in sorted(lib.glob("*.md")):
        record = records.get(path.name, {})
        if record.get("duplicate_of"):
            continue
        text = path.read_text(encoding="utf-8-sig", errors="replace")
        document = DocumentMeta(
            doc_id=record.get("sha256", path.stem)[:12],
            source_path=str(path),
            file_name=path.name,
            standard_no=record.get("standard_no"),
            title=record.get("title"),
        )
        for task in detect_tasks(
            pages_of(text), document, registry=registry, catalog_path=catalog_path
        ):
            task_dict = task.model_dump(mode="json")
            task_dict["file"] = path.name
            task_dict["doc_type"] = record.get("doc_type", "unknown")
            task_dict["doc_title"] = record.get("title", "")
            tasks.append(task_dict)

    by_type = Counter(task["doc_type"] for task in tasks)
    by_status = Counter(task["status"] for task in tasks)
    by_std = Counter(task["requirement_standard"] for task in tasks)

    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "tasks.json").write_text(
        json.dumps(tasks, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    lines = [
        "# Markdown 语料跨标准补全扫描",
        "",
        f"- 扫描文件：{len([name for name in records if not records[name].get('duplicate_of')])}",
        "- 说明：覆盖全部文档类型（国标/行标/企标/美标、制造大纲、技术协议、质保文件等），不按类型过滤。",
        f"- 任务数：{len(tasks)}",
        f"- 按类型：{dict(by_type)}",
        f"- 按状态：{dict(by_status)}",
        "",
        "## 高频要求来源",
        "",
        "| 标准号 | 任务数 |",
        "|---|---|",
    ]
    for standard, count in by_std.most_common(30):
        lines.append(f"| {standard} | {count} |")
    lines.extend(
        [
            "",
            "## 任务明细（前 100 条）",
            "",
            "| 文件 | 类型 | 检测项目 | 缺失字段 | 要求来源 | 页码 | 可选 | 状态 |",
            "|---|---|---|---|---|---|---|---|",
        ]
    )
    for task in tasks[:100]:
        lines.append(
            f"| {task['file']} | {task['doc_type']} | {task.get('inspection_item') or ''} | "
            f"{'、'.join(task.get('missing_fields', []))} | {task['requirement_standard']} | "
            f"{task.get('page_no') or ''} | {'是' if task.get('optional') else '否'} | {task['status']} |"
        )
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"tasks={len(tasks)}")
    print("by_type", dict(by_type))
    print("by_status", dict(by_status))
    print("top standards", by_std.most_common(15))
    print(f"out={out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
