"""Command line interface for the local framework."""

from __future__ import annotations

import argparse
import dataclasses
import json
from pathlib import Path

from . import __version__
from .acceptance import run_acceptance, write_acceptance
from .artifacts import verify_artifacts
from .clients import build_glm_client, build_layout_client, build_qwen_client
from .contracts import CoveragePlan, DocumentResult, Evidence
from .eval import run_evaluation
from .extraction import build_extractor
from .goldset import (
    goldset_summary,
    load_gold_document,
    load_manifest,
    validate_manifest,
)
from .goldset_review import (
    render_review_markdown,
    review_annotations,
    write_review_report,
)
from .goldset_verify import verify_document_evidence
from .ingest import ingest
from .ocr import build_ocr_adapter
from .pipeline import run_pipeline
from .schema_export import export_schemas
from .settings import Settings
from .tablegrid import extract_tables
from .validation import validate


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="metal-doc",
        description="Metal standard document extraction agent (local framework)",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the end-to-end pipeline")
    run.add_argument("doc", help="OCR-produced markdown file (.md)")
    run.add_argument("--out", required=True, help="output directory")
    run.add_argument("--ocr", default=None, choices=["mock", "glm"], help="OCR backend")
    run.add_argument("--extractor", default=None, choices=["mock", "qwen"], help="extractor backend")
    run.add_argument("--template", default="product_full", help="coverage template")
    run.add_argument("--json", action="store_true", help="print machine-readable summary")

    inspect = sub.add_parser("inspect", help="inspect document pages and tables")
    inspect.add_argument("doc", help="OCR-produced markdown file (.md)")
    inspect.add_argument("--ocr", default=None, choices=["mock", "glm"], help="OCR backend")

    schema = sub.add_parser("schema", help="schema utilities")
    schema_sub = schema.add_subparsers(dest="schema_command", required=True)
    schema_export = schema_sub.add_parser("export", help="export JSON Schemas")
    schema_export.add_argument("--out", default="schemas/v0", help="output directory")
    schema_project = schema_sub.add_parser(
        "project", help="project job artifacts onto a schema template"
    )
    schema_project.add_argument(
        "--job", required=True, help="job/run directory containing result.json"
    )
    schema_project.add_argument(
        "--template",
        default="configs/schema_templates/product_standard.json",
        help="schema template JSON",
    )
    schema_project.add_argument("--out", default=None, help="write projection JSON")
    schema_project.add_argument(
        "--json", action="store_true", help="print projection JSON"
    )

    gold = sub.add_parser("gold", help="golden set utilities")
    gold_sub = gold.add_subparsers(dest="gold_command", required=True)
    gold_validate = gold_sub.add_parser("validate", help="validate a golden set")
    gold_validate.add_argument(
        "--manifest", default="goldset/v0/manifest.json", help="manifest path"
    )
    gold_validate.add_argument(
        "--strict", action="store_true", help="treat requirement gaps as errors"
    )
    gold_status = gold_sub.add_parser("status", help="summarize annotation progress")
    gold_status.add_argument(
        "--manifest", default="goldset/v0/manifest.json", help="manifest path"
    )
    gold_status.add_argument("--json", action="store_true", help="machine-readable output")
    gold_diff = gold_sub.add_parser("diff", help="compare A/B annotations")
    gold_diff.add_argument("--a", required=True, help="annotator A file")
    gold_diff.add_argument("--b", required=True, help="annotator B file")
    gold_diff.add_argument("--out", default=None, help="write markdown report")
    gold_diff.add_argument("--json", action="store_true", help="machine-readable output")
    gold_diff.add_argument(
        "--strict", action="store_true", help="exit 1 when the consistency gate fails"
    )
    gold_verify = gold_sub.add_parser(
        "verify", help="verify annotation evidence against source runs"
    )
    gold_verify.add_argument(
        "--manifest", default="goldset/v0/manifest.json", help="manifest path"
    )
    gold_verify.add_argument("--runs", required=True, help="run root with <doc_id>/")
    gold_verify.add_argument("--json", action="store_true", help="machine-readable output")
    gold_verify.add_argument(
        "--strict", action="store_true", help="exit 1 when any evidence is invalid"
    )

    models = sub.add_parser("models", help="model service utilities")
    models_sub = models.add_subparsers(dest="models_command", required=True)
    models_check = models_sub.add_parser("check", help="health-check model services")
    models_check.add_argument("--json", action="store_true", help="machine-readable output")

    validate_run = sub.add_parser("validate", help="re-run L0-L2 on an existing run")
    validate_run.add_argument("--run", required=True, help="run directory with result.json")
    validate_run.add_argument("--json", action="store_true", help="machine-readable output")

    artifacts = sub.add_parser("artifacts", help="artifact manifest utilities")
    artifacts_sub = artifacts.add_subparsers(dest="artifacts_command", required=True)
    artifacts_verify = artifacts_sub.add_parser("verify", help="verify artifact sizes and hashes")
    artifacts_verify.add_argument("--run", required=True, help="run directory")
    artifacts_verify.add_argument("--json", action="store_true", help="machine-readable output")

    evaluate = sub.add_parser("eval", help="score predictions against the golden set")
    evaluate.add_argument("--gold", default="goldset/v0", help="golden set directory")
    evaluate.add_argument("--runs", required=True, help="run root with <doc_id>/result.json")
    evaluate.add_argument("--out", default="runs/eval", help="output directory")
    evaluate.add_argument(
        "--baseline", default=None, help="regression baseline JSON to compare against"
    )
    evaluate.add_argument(
        "--save-baseline", default=None, help="write this run as a regression baseline"
    )
    evaluate.add_argument(
        "--baseline-label", default="m1", help="label for a saved baseline"
    )
    evaluate.add_argument(
        "--fail-on-regression",
        action="store_true",
        help="exit 1 when a core metric drops beyond tolerance",
    )
    evaluate.add_argument("--json", action="store_true", help="print machine-readable summary")

    accept = sub.add_parser("accept", help="M1-S8 full-corpus acceptance report")
    accept.add_argument("--gold", default="goldset/v0", help="golden set directory")
    accept.add_argument("--runs", required=True, help="run root with <doc_id>/result.json")
    accept.add_argument("--out", default="eval/acceptance", help="output directory")
    accept.add_argument("--json", action="store_true", help="machine-readable output")
    accept.add_argument(
        "--strict", action="store_true", help="exit 1 when the decision is NO-GO"
    )

    return parser


def _settings_with_overrides(args: argparse.Namespace) -> Settings:
    settings = Settings.from_env()
    updates = {}
    if getattr(args, "ocr", None):
        updates["ocr_backend"] = args.ocr
    if getattr(args, "extractor", None):
        updates["extractor_backend"] = args.extractor
    return dataclasses.replace(settings, **updates) if updates else settings


def cmd_run(args: argparse.Namespace) -> int:
    settings = _settings_with_overrides(args)
    result = run_pipeline(
        doc_path=args.doc,
        out_dir=args.out,
        settings=settings,
        coverage_template=args.template,
    )
    summary = {
        "doc": result.result.document.standard_no or result.result.document.file_name,
        "title": result.result.document.title,
        "pages": result.result.document.page_count,
        "tables": len(result.result.tables),
        "records": len(result.result.records),
        "evidence": len(result.evidence),
        "status": result.result.quality.status if result.result.quality else "unknown",
        "out": str(Path(args.out).resolve()),
        "artifacts": result.result.artifacts,
    }
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"document : {summary['doc']}")
        print(f"title    : {summary['title']}")
        print(f"pages    : {summary['pages']}")
        print(f"tables   : {summary['tables']}")
        print(f"records  : {summary['records']}")
        print(f"evidence : {summary['evidence']}")
        print(f"status   : {summary['status']}")
        print(f"out      : {summary['out']}")
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    settings = _settings_with_overrides(args)
    document, pages = ingest(args.doc)
    ocr = build_ocr_adapter(settings)
    pages = ocr.recognize(Path(args.doc))
    tables = extract_tables(pages)
    print(f"document : {document.standard_no or document.file_name}")
    print(f"title    : {document.title}")
    print(f"pages    : {len(pages)}")
    print(f"tables   : {len(tables)}")
    for table in tables:
        print(
            f"- {table.table_id} p{table.page_no} {table.profile:24s} "
            f"{table.orientation:12s} {table.n_rows}x{table.n_cols} "
            f"blocks={len(table.blocks)} caption={table.caption or ''}"
        )
    return 0


def cmd_schema_export(args: argparse.Namespace) -> int:
    written = export_schemas(args.out)
    print(f"exported {len(written)} schemas to {Path(args.out).resolve()}")
    for name, file_name in written.items():
        print(f"- {name:22s} {file_name}")
    return 0


def cmd_schema_project(args: argparse.Namespace) -> int:
    from .schema_projection import load_template, project_job

    template = load_template(args.template)
    payload = project_job(args.job, template)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    coverage = payload["coverage"]
    print(f"schema  : {payload['template']}")
    print(f"doc     : {payload['doc_id']}")
    print(
        "coverage: fields {}/{} ({:.1%}), required {}/{} ({:.1%})".format(
            coverage["fields_filled"],
            coverage["fields_total"],
            coverage["field_rate"],
            coverage["required_filled"],
            coverage["required_total"],
            coverage["required_rate"],
        )
    )
    for key, stats in coverage["by_category"].items():
        print(
            f"- {key:14s} rows={stats['rows']} "
            f"required={stats['required_filled']}/{stats['required_total']}"
        )
    print(f"errors  : {len(payload['errors'])}")
    if payload.get("notes"):
        print("notes   : " + "; ".join(payload["notes"]))
    return 0


def cmd_gold_validate(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)
    issues = validate_manifest(
        manifest, manifest_path.parent, strict_requirements=args.strict
    )
    summary = goldset_summary(manifest)
    print(f"goldset : {manifest.goldset_version}")
    print(f"documents: {summary['documents']} annotated={summary['annotated']}")
    print(f"by type : {summary['by_doc_type']}")
    print(f"by source: {summary['by_source_type']}")
    print(f"by split: {summary['by_split']}")
    print(f"profiles: {summary['by_profile']}")
    if issues:
        print("issues:")
        for issue in issues:
            print(f"- {issue}")
        structural = [issue for issue in issues if not issue.startswith("requirement")]
        return 1 if structural else 0
    print("issues  : none")
    return 0


def cmd_models_check(args: argparse.Namespace) -> int:
    settings = Settings.from_env()
    checks: list[dict[str, object]] = []

    def check(name: str, url: str | None, builder) -> None:
        if not url:
            checks.append({"service": name, "status": "not_configured"})
            return
        try:
            with builder(settings) as client:
                detail = client.health()
                active = (
                    getattr(client, "base_url", None)
                    or getattr(client, "active_url", None)
                    or url
                )
            checks.append(
                {
                    "service": name,
                    "status": "ok",
                    "url": active,
                    "configured_url": url,
                    "detail": detail,
                }
            )
        except Exception as exc:  # noqa: BLE001 - report every service failure
            checks.append(
                {
                    "service": name,
                    "status": "failed",
                    "url": url,
                    "error": str(exc)[:300],
                }
            )

    check("glm-ocr", settings.glm_ocr_base_url, build_glm_client)
    check("qwen", settings.qwen_base_url, build_qwen_client)
    check("layout", settings.layout_service_url, build_layout_client)

    if args.json:
        print(json.dumps(checks, ensure_ascii=False, indent=2))
    else:
        for item in checks:
            line = f"{item['service']:10s} {item['status']}"
            if item.get("url"):
                line += f"  {item['url']}"
            if item.get("configured_url") and item.get("url") != item.get(
                "configured_url"
            ):
                line += f"  (fallback from {item['configured_url']})"
            if item.get("detail"):
                line += f"  {item['detail']}"
            if item.get("error"):
                line += f"  {item['error']}"
            print(line)
    return 0 if all(item["status"] == "ok" for item in checks) else 1


def cmd_artifacts_verify(args: argparse.Namespace) -> int:
    result = verify_artifacts(Path(args.run))
    if args.json:
        print(
            json.dumps(
                {"ok": result.ok, "checked": result.checked, "issues": result.issues},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"run      : {Path(args.run).resolve()}")
        print(f"checked  : {result.checked}")
        print(f"ok       : {result.ok}")
        for issue in result.issues:
            print(f"- {issue['code']} {issue['path']}: {issue.get('detail', '')}")
    return 0 if result.ok else 1


def cmd_validate(args: argparse.Namespace) -> int:
    run_dir = Path(args.run)
    result = DocumentResult.model_validate(
        json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    )
    evidence: list[Evidence] = []
    evidence_path = run_dir / "evidence.jsonl"
    if evidence_path.exists():
        for line in evidence_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                evidence.append(Evidence.model_validate(json.loads(line)))
    audit = validate(
        result.document,
        result.records,
        evidence,
        result.coverage or CoveragePlan(),
        tables=result.tables,
    )
    if args.json:
        print(
            json.dumps(
                {
                    "status": audit.status,
                    "stats": audit.stats,
                    "issues": [issue.model_dump() for issue in audit.issues],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"document : {result.document.standard_no or result.document.file_name}")
        print(f"status   : {audit.status}")
        print(f"records  : {audit.stats.get('record_count', 0)}")
        print(f"values   : {audit.stats.get('value_count', 0)}")
        print(f"errors   : {audit.stats.get('issue_errors', 0)}")
        print(f"warnings : {audit.stats.get('issue_warnings', 0)}")
        for issue in audit.issues:
            print(
                f"- {issue.level} {issue.severity} {issue.code} "
                f"{issue.field or ''}: {issue.message}"
            )
    return 1 if audit.status == "fail" else 0


def cmd_gold_status(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)
    base = manifest_path.parent
    statuses: dict[str, int] = {}
    counts = {
        "tables": 0,
        "records": 0,
        "inspection_items": 0,
        "classification_items": 0,
        "clauses": 0,
    }
    missing: list[str] = []
    for entry in manifest.documents:
        if not entry.annotation_file:
            missing.append(entry.doc_id)
            continue
        gold = load_gold_document(base / entry.annotation_file)
        statuses[gold.annotation.status] = statuses.get(gold.annotation.status, 0) + 1
        counts["tables"] += len(gold.tables)
        counts["records"] += sum(len(table.records) for table in gold.tables)
        counts["inspection_items"] += sum(
            len(table.inspection_items) for table in gold.tables
        )
        counts["classification_items"] += sum(
            len(table.classification_items) for table in gold.tables
        )
        counts["clauses"] += len(gold.clauses)

    payload = {
        "goldset_version": manifest.goldset_version,
        "documents": len(manifest.documents),
        "annotated": len(manifest.documents) - len(missing),
        "by_status": statuses,
        "counts": counts,
        "missing": missing,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"goldset    : {manifest.goldset_version}")
        print(f"documents  : {len(manifest.documents)}")
        print(f"annotated  : {payload['annotated']}")
        print(f"status     : {statuses}")
        print(f"tables     : {counts['tables']}")
        print(f"records    : {counts['records']}")
        print(f"inspection : {counts['inspection_items']}")
        print(f"clauses    : {counts['clauses']}")
        print(f"missing    : {', '.join(missing) if missing else '无'}")
    return 0


def cmd_gold_diff(args: argparse.Namespace) -> int:
    review = review_annotations(args.a, args.b)
    if args.out:
        write_review_report(review, args.out)
    if args.json:
        print(json.dumps(review.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(render_review_markdown(review))
    return 0 if review.passed or not args.strict else 1


def cmd_gold_verify(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    manifest = load_manifest(manifest_path)
    base = manifest_path.parent
    run_root = Path(args.runs)
    reports = []
    for entry in manifest.documents:
        if not entry.annotation_file:
            continue
        gold = load_gold_document(base / entry.annotation_file)
        verification = verify_document_evidence(gold, run_root / entry.doc_id)
        reports.append({"doc_id": entry.doc_id, **verification.to_dict()})
    checked = sum(item["checked"] for item in reports)
    issues = [issue for item in reports for issue in item["issues"]]
    ok = not issues
    if args.json:
        print(json.dumps({"ok": ok, "checked": checked, "documents": reports}, ensure_ascii=False, indent=2))
    else:
        print(f"documents : {len(reports)}")
        print(f"checked   : {checked}")
        print(f"ok        : {ok}")
        for item in reports:
            if item["issues"]:
                print(f"- {item['doc_id']}: {len(item['issues'])} issue(s)")
                for issue in item["issues"][:10]:
                    print(
                        f"  {issue.get('code')} {issue.get('location', '')} "
                        f"{issue.get('quote', issue.get('cell', ''))}"
                    )
    return 0 if ok or not args.strict else 1


def cmd_eval(args: argparse.Namespace) -> int:
    payload = run_evaluation(
        args.gold,
        args.runs,
        args.out,
        baseline_path=args.baseline,
        save_baseline=args.save_baseline,
        baseline_label=args.baseline_label,
    )
    summary = payload["summary"]
    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        print(f"documents : {summary['documents']}")
        print(f"record F1 : {summary['record_f1']}")
        print(f"field F1  : {summary['field_f1']}")
        print(f"value acc : {summary['value_accuracy']}")
        print(f"evidence  : {summary['evidence_rate']}")
        print(f"coverage  : {summary['coverage_rate']}")
        print(f"out       : {Path(args.out).resolve()}")
        regression = payload.get("regression")
        if regression:
            print(f"regression: {'pass' if regression['passed'] else 'FAIL'}")
            for item in regression["regressions"]:
                print(
                    f"- {item['metric']}: {item['baseline']} -> "
                    f"{item['current']} ({item['delta']})"
                )
    if args.save_baseline:
        print(f"baseline  : {Path(args.save_baseline).resolve()}")
    if args.fail_on_regression and payload.get("regression"):
        return 0 if payload["regression"]["passed"] else 1
    return 0


def cmd_accept(args: argparse.Namespace) -> int:
    report = run_acceptance(args.gold, args.runs)
    paths = write_acceptance(report, args.out)
    payload = report.to_dict()
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"decision  : {report.go_no_go}")
        print(f"documents : {len(report.documents)}")
        for check in report.checks:
            print(
                f"- {'PASS' if check.passed else 'FAIL'} {check.name}: "
                f"{check.actual} (target {check.target})"
            )
        print(f"json      : {paths['json']}")
        print(f"report    : {paths['markdown']}")
    if args.strict and report.go_no_go != "GO":
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return cmd_run(args)
    if args.command == "inspect":
        return cmd_inspect(args)
    if args.command == "schema":
        if args.schema_command == "project":
            return cmd_schema_project(args)
        return cmd_schema_export(args)
    if args.command == "gold":
        if args.gold_command == "status":
            return cmd_gold_status(args)
        if args.gold_command == "diff":
            return cmd_gold_diff(args)
        if args.gold_command == "verify":
            return cmd_gold_verify(args)
        return cmd_gold_validate(args)
    if args.command == "validate":
        return cmd_validate(args)
    if args.command == "artifacts":
        return cmd_artifacts_verify(args)
    if args.command == "eval":
        return cmd_eval(args)
    if args.command == "accept":
        return cmd_accept(args)
    if args.command == "models":
        return cmd_models_check(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
