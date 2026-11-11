"""M1-S8 repeatable demo: document -> tables -> records -> evidence -> audit.

Run from the repository root:
    python tools/demo_m1.py
    python tools/demo_m1.py --doc "..\\标准文件\\Q-Du 302-2015.md" --out runs\\demo_m1
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.artifacts import verify_artifacts  # noqa: E402
from metal_doc_agent.pipeline import run_pipeline  # noqa: E402
from metal_doc_agent.settings import Settings  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="M1 repeatable demo")
    parser.add_argument(
        "--doc",
        default=str(ROOT.parent / "标准文件" / "Q-Du 302-2015.md"),
        help="OCR-produced markdown or PDF",
    )
    parser.add_argument("--out", default=str(ROOT / "runs" / "demo_m1"), help="output directory")
    parser.add_argument("--ocr", default="mock", choices=["mock", "glm"])
    parser.add_argument("--extractor", default="mock", choices=["mock", "qwen"])
    parser.add_argument("--template", default="enterprise")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = dataclasses.replace(
        Settings.from_env(),
        ocr_backend=args.ocr,
        extractor_backend=args.extractor,
    )
    result = run_pipeline(
        args.doc,
        args.out,
        settings=settings,
        coverage_template=args.template,
    )
    verification = verify_artifacts(Path(args.out))

    print("== document ==")
    print(f"standard : {result.result.document.standard_no or result.result.document.file_name}")
    print(f"title    : {result.result.document.title}")
    print(f"pages    : {result.result.document.page_count}")
    print(f"tables   : {len(result.result.tables)}")
    print(f"records  : {len(result.result.records)}")
    print(f"evidence : {len(result.evidence)}")
    print(f"audit    : {result.result.quality.status if result.result.quality else 'unknown'}")
    print(f"out      : {Path(args.out).resolve()}")

    print("\n== first records ==")
    for record in result.result.records[:3]:
        values = ", ".join(
            f"{name}={value.raw}/{value.value}/{value.unit}/{value.comparator}"
            for name, value in list(record.properties.items())[:5]
        )
        print(f"- {record.grade or record.grade_level} | {record.condition or ''} | {values}")

    print("\n== evidence sample ==")
    for evidence in result.evidence[:5]:
        print(
            f"- {evidence.evidence_id} p{evidence.page_no} "
            f"{evidence.table_id} r{evidence.row} c{evidence.col}: {evidence.quote}"
        )

    print("\n== artifacts ==")
    print(f"checked : {verification.checked}")
    print(f"ok      : {verification.ok}")
    for issue in verification.issues:
        print(f"- {issue}")
    print(f"report  : {Path(args.out).resolve() / 'audit.md'}")

    summary = {
        "doc": result.result.document.standard_no or result.result.document.file_name,
        "pages": result.result.document.page_count,
        "tables": len(result.result.tables),
        "records": len(result.result.records),
        "evidence": len(result.evidence),
        "status": result.result.quality.status if result.result.quality else "unknown",
        "artifacts_ok": verification.ok,
    }
    (Path(args.out) / "demo_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0 if verification.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
