"""Build the M2.1 error taxonomy from a goldset evaluation JSON."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--eval", required=True, help="eval.json from metal-doc eval")
    parser.add_argument("--gold", default=str(ROOT / "goldset" / "v0"))
    parser.add_argument("--runs", default=str(ROOT / "runs" / "m2_baseline"))
    parser.add_argument("--out", default=str(ROOT / "eval" / "m2"))
    parser.add_argument(
        "--dataset",
        default=str(ROOT / "data" / "m2" / "train-v1" / "report.json"),
        help="optional M2 dataset report",
    )
    args = parser.parse_args(argv)

    eval_path = Path(args.eval)
    payload = json.loads(eval_path.read_text(encoding="utf-8"))
    gold_dir = Path(args.gold)
    manifest = json.loads((gold_dir / "manifest.json").read_text(encoding="utf-8"))
    entries = {item["doc_id"]: item for item in manifest["documents"]}
    documents = payload["documents"]
    summary = payload["summary"]

    categories = Counter(summary.get("error_categories") or {})
    error_types: Counter = Counter()
    by_doc_type: dict[str, Counter] = {}
    by_source_type: dict[str, Counter] = {}
    top: list[dict] = []
    for doc in documents:
        doc_id = doc["doc_id"]
        entry = entries.get(doc_id, {})
        cats = Counter(doc.get("error_categories") or {})
        error_types.update(error.get("type") for error in doc.get("errors") or [])
        by_doc_type.setdefault(entry.get("doc_type", "unknown"), Counter()).update(cats)
        by_source_type.setdefault(
            entry.get("source_type", "unknown"), Counter()
        ).update(cats)
        if doc.get("errors"):
            top.append({"doc_id": doc_id, "errors": len(doc["errors"])})

    top.sort(key=lambda item: item["errors"], reverse=True)

    gold_tables = 0
    gold_records = 0
    gold_clauses = 0
    profiles: Counter = Counter()
    splits: Counter = Counter()
    for item in manifest["documents"]:
        annotation = item.get("annotation_file")
        if not annotation:
            continue
        gold = json.loads((gold_dir / annotation).read_text(encoding="utf-8"))
        gold_tables += len(gold.get("tables") or [])
        gold_records += sum(
            len(table.get("records") or []) for table in gold.get("tables") or []
        )
        gold_clauses += len(gold.get("clauses") or [])
        profiles.update(
            table.get("profile", "unknown") for table in gold.get("tables") or []
        )
        splits[item.get("split", "unknown")] += 1

    doc_ids = [item["doc_id"] for item in manifest["documents"]]
    leakage = (
        "none（按 doc_id 切分，未发现同一文档跨 split）"
        if len(doc_ids) == len(set(doc_ids))
        else "duplicate doc_id detected"
    )
    total_tables = sum(int(item.get("tables") or 0) for item in manifest["documents"])

    doc_counts_type = Counter(
        entry.get("doc_type", "unknown") for entry in entries.values()
    )
    doc_counts_source = Counter(
        entry.get("source_type", "unknown") for entry in entries.values()
    )

    taxonomy = {
        "schema_version": "0.1.0",
        "source": _relative(eval_path),
        "run_root": _relative(Path(args.runs)),
        "goldset_version": payload.get("goldset_version", manifest["goldset_version"]),
        "documents": len(documents),
        "baseline": {
            key: summary.get(key)
            for key in (
                "record_f1",
                "field_f1",
                "value_accuracy",
                "inspection_accuracy",
                "classification_accuracy",
                "clause_accuracy",
                "evidence_rate",
                "coverage_rate",
            )
        },
        "error_categories": dict(categories),
        "error_types": dict(error_types.most_common()),
        "by_doc_type": _grouped(by_doc_type, doc_counts_type),
        "by_source_type": _grouped(by_source_type, doc_counts_source),
        "top_documents": top[:8],
        "readiness": {
            "annotated_documents": len(documents),
            "annotated_tables": gold_tables,
            "annotated_records": gold_records,
            "annotated_clauses": gold_clauses,
            "splits": dict(splits),
            "table_profiles": dict(profiles.most_common()),
            "leakage": leakage,
            "gaps": [
                f"每份文档仅标注 3 张关键表（{gold_tables}/{total_tables}），不是全表标注",
                f"mini 仅 {splits.get('mini', 0)} 份文档，当前不足以支撑 LoRA 训练",
                "条款/定性项目只标注了必填字段，数值项以 3 张关键表为准",
            ],
        },
    }

    out_dir = Path(args.out)
    dataset_path = Path(args.dataset)
    if dataset_path.exists():
        dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
        taxonomy["samples"] = {
            "source": _relative(dataset_path),
            "splits": dataset.get("splits"),
            "counts": dataset.get("samples"),
            "skipped_tables": len(dataset.get("skipped") or []),
        }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "error-taxonomy.json").write_text(
        json.dumps(taxonomy, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_dir / "error-taxonomy.md").write_text(
        _render(taxonomy), encoding="utf-8"
    )
    print(
        f"docs={taxonomy['documents']} record_f1={taxonomy['baseline']['record_f1']} "
        f"field_f1={taxonomy['baseline']['field_f1']} "
        f"errors={sum(error_types.values())}"
    )
    print(f"out={out_dir}")
    return 0


def _grouped(groups: dict[str, Counter], document_counts: Counter) -> dict:
    result = {}
    for key, counter in groups.items():
        item = {"documents": document_counts.get(key, 0)}
        item.update(dict(counter))
        result[key] = item
    return result


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _group_lines(title: str, groups: dict) -> list[str]:
    if not groups:
        return []
    keys = [
        key
        for key in ("header", "reference", "semantic", "ocr", "normalization", "coverage")
        if any(key in item for item in groups.values())
    ]
    lines = [
        "",
        f"## {title}",
        "",
        "| 分组 | 文档 | " + " | ".join(keys) + " |",
        "|---" * (len(keys) + 2) + "|",
    ]
    for name, item in groups.items():
        cells = " | ".join(str(item.get(key, 0)) for key in keys)
        lines.append(f"| {name} | {item.get('documents', 0)} | {cells} |")
    return lines


def _render(taxonomy: dict) -> str:
    baseline = taxonomy["baseline"]
    lines = [
        "# M2.1 错误分类与数据就绪",
        "",
        f"- 基线：`{taxonomy['source']}`（{taxonomy['documents']} 份文档，金标 {taxonomy['goldset_version']}）",
        f"- 指标：记录 F1 {baseline['record_f1']}、字段 F1 {baseline['field_f1']}、"
        f"数值准确 {baseline['value_accuracy']}、检验项目 {baseline['inspection_accuracy']}、"
        f"条款 {baseline['clause_accuracy']}、覆盖 {baseline['coverage_rate']}",
        "",
        "## 错误类别",
        "",
        "| 类别 | 数量 |",
        "|---|---|",
    ]
    for key, value in taxonomy["error_categories"].items():
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "## 错误类型", "", "| 类型 | 数量 |", "|---|---|"])
    for key, value in taxonomy["error_types"].items():
        lines.append(f"| {key} | {value} |")
    lines.extend(["", "## 高错误文档", "", "| 文档 | 错误数 |", "|---|---|"])
    for item in taxonomy["top_documents"]:
        lines.append(f"| {item['doc_id']} | {item['errors']} |")
    lines.extend(_group_lines("按文档类型", taxonomy["by_doc_type"]))
    lines.extend(_group_lines("按来源", taxonomy["by_source_type"]))
    readiness = taxonomy["readiness"]
    lines.extend(
        [
            "",
            "## 数据就绪",
            "",
            f"- 标注文档 {readiness['annotated_documents']} / 表 {readiness['annotated_tables']} / "
            f"记录 {readiness['annotated_records']} / 条款 {readiness['annotated_clauses']}",
            f"- 切分：{readiness['splits']}",
            f"- 泄漏：{readiness['leakage']}",
            "",
            "## 缺口",
            "",
        ]
    )
    lines.extend(f"- {gap}" for gap in readiness["gaps"])
    samples = taxonomy.get("samples")
    if samples:
        lines.extend(
            [
                "",
                "## 训练样本",
                "",
                f"- 来源 `{samples['source']}`；跳过 {samples['skipped_tables']} 张表",
            ]
        )
        splits = samples.get("splits") or {}
        counts = samples.get("counts") or {}
        for split, documents in splits.items():
            task_counts = counts.get(split) or {}
            detail = "、".join(f"{name} {value}" for name, value in task_counts.items())
            total = sum(task_counts.values())
            lines.append(f"- {split}：{documents} 文档 / {total} 样本（{detail}）")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
