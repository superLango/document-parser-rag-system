"""Retrofit existing runs with deterministic inspection/classification items.

This is a measurement helper for WS2. New pipeline runs already include
non-record extraction; this tool updates an existing run copy in place and
rebuilds the artifact manifest.

Run from the repository root:
    python tools/augment_nonrecord.py --runs runs/m1_qwen_ws2
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.artifacts import write_artifact_manifest  # noqa: E402
from metal_doc_agent.contracts import DocumentResult, Evidence, Page, TableGrid  # noqa: E402
from metal_doc_agent.extraction.clauses import extract_clauses  # noqa: E402
from metal_doc_agent.extraction.nonrecord import extract_nonrecord  # noqa: E402
from metal_doc_agent.references import extract_references  # noqa: E402
from metal_doc_agent.relevance import plan_references  # noqa: E402
from metal_doc_agent.standards import load_registry, resolve_references  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", default="runs/m1_qwen_ws2")
    args = parser.parse_args(argv)
    runs_dir = ROOT / args.runs

    for run_dir in sorted(path for path in runs_dir.iterdir() if path.is_dir()):
        result_path = run_dir / "result.json"
        if not result_path.exists():
            continue
        result = DocumentResult.model_validate_json(result_path.read_text(encoding="utf-8"))
        tables = [
            TableGrid.model_validate_json(path.read_text(encoding="utf-8"))
            for path in sorted((run_dir / "tablegrid").glob("*.json"))
        ]
        inspection = []
        classification = []
        new_evidence = []
        for table in tables:
            output = extract_nonrecord(table, result.document)
            inspection.extend(output.inspection_items)
            classification.extend(output.classification_items)
            new_evidence.extend(output.evidence)

        pages_path = run_dir / "pages.json"
        version_report = None
        if pages_path.exists():
            pages = [
                Page.model_validate(item)
                for item in json.loads(pages_path.read_text(encoding="utf-8"))
            ]
            clause_output = extract_clauses(pages, result.document)
            result.clauses = clause_output.clauses
            new_evidence.extend(clause_output.evidence)
            result.references = extract_references(pages, result.document)
            registry = load_registry(ROOT / "configs" / "standards.json")
            version_report = resolve_references(result.references, registry)
            plan_references(result.references)
            result.artifacts["references"] = "references.json"
            result.artifacts["version_report"] = "version_report.md"
            (run_dir / "references.json").write_text(
                json.dumps(
                    result.references.model_dump(mode="json"),
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
            (run_dir / "version_report.md").write_text(
                version_report.to_markdown(result.references),
                encoding="utf-8",
            )

        evidence_path = run_dir / "evidence.jsonl"
        existing_ids: set[str] = set()
        lines: list[str] = []
        if evidence_path.exists():
            for line in evidence_path.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                item = Evidence.model_validate_json(line)
                existing_ids.add(item.evidence_id)
                lines.append(line)
        for item in new_evidence:
            if item.evidence_id in existing_ids:
                continue
            existing_ids.add(item.evidence_id)
            lines.append(json.dumps(item.model_dump(mode="json"), ensure_ascii=False))
        evidence_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")

        result.inspection_items = inspection
        result.classification_items = classification
        result_path.write_text(
            json.dumps(result.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        write_artifact_manifest(run_dir, job_id=run_dir.name, doc_id=result.document.doc_id)
        print(
            run_dir.name,
            "inspection", len(inspection),
            "classification", len(classification),
            "clauses", len(result.clauses),
            "references", len(result.references.references) if result.references else 0,
            "resolved", version_report.resolved if version_report else 0,
            "selected", result.references.budget.get("selected_documents", 0) if result.references else 0,
            "gaps", len(result.references.gaps) if result.references else 0,
            "evidence", len(new_evidence),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
