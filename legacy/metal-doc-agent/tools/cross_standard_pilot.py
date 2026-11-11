"""Pilot the demand-driven cross-standard route on one run."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.contracts import DocumentResult, Page  # noqa: E402
from metal_doc_agent.cross_standard import detect_tasks, render_report  # noqa: E402
from metal_doc_agent.standards import load_registry  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", default="runs/m1.5_qwen/gbt3880_1_2012")
    parser.add_argument("--registry", default="configs/standards.json")
    parser.add_argument("--catalog", default="data/standards_library/catalog.json")
    args = parser.parse_args(argv)
    run_dir = ROOT / args.run
    result = DocumentResult.model_validate_json(
        (run_dir / "result.json").read_text(encoding="utf-8")
    )
    pages = [
        Page.model_validate(item)
        for item in json.loads((run_dir / "pages.json").read_text(encoding="utf-8"))
    ]
    registry = load_registry(ROOT / args.registry)
    tasks = detect_tasks(
        pages,
        result.document,
        registry=registry,
        catalog_path=ROOT / args.catalog,
    )
    (run_dir / "cross_standard_tasks.json").write_text(
        json.dumps(
            [task.model_dump(mode="json") for task in tasks],
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (run_dir / "cross_standard_report.md").write_text(
        render_report(result.document.doc_id, tasks), encoding="utf-8"
    )
    print(f"tasks={len(tasks)}")
    for task in tasks:
        print(
            task.task_id,
            "|",
            task.inspection_item,
            "|",
            "、".join(task.missing_fields),
            "|",
            task.requirement_standard,
            "|",
            task.status,
            "|",
            task.gap or task.resolution_basis or "",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
