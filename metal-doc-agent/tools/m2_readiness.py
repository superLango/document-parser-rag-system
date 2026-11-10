"""Check M2.1 readiness against the plan's split and data rules.

Usage:
    python tools/m2_readiness.py
    python tools/m2_readiness.py --gold goldset/v0 --dataset data/m2/train-v1
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SPLIT_MAP = {"mini": "train", "dev": "dev", "heldout": "heldout"}
FAMILY_YEAR_RE = re.compile(r"[-—]?\s*\d{4}$")
HELDOUT_MIN_DOC_TYPES = 4
HELDOUT_MIN_PROFILES = 3


def build_readiness(gold_dir: Path, dataset_dir: Path) -> dict[str, Any]:
    manifest = json.loads((gold_dir / "manifest.json").read_text(encoding="utf-8"))
    report = json.loads((dataset_dir / "report.json").read_text(encoding="utf-8"))
    documents = manifest.get("documents") or []

    splits: dict[str, list[str]] = defaultdict(list)
    for doc in documents:
        splits[SPLIT_MAP.get(doc.get("split") or "dev", "dev")].append(doc["doc_id"])
    leakage = _find_duplicates(splits)

    family_conflicts = _family_conflicts(documents)
    heldout = [doc for doc in documents if doc.get("split") == "heldout"]
    doc_types = sorted({doc.get("doc_type") for doc in heldout if doc.get("doc_type")})
    profiles = sorted(_heldout_profiles(heldout, gold_dir))
    pure = _heldout_perturbations(dataset_dir)

    rows = _sample_rows(dataset_dir)
    trace = _traceability(rows)

    checks = [
        _check("leakage", "fail" if leakage else "pass", leakage or "无跨 split 文档"),
        _check(
            "family_split",
            "fail" if family_conflicts else "pass",
            family_conflicts or "同族标准均在同一侧",
        ),
        _check(
            "heldout_doc_types",
            "pass" if len(doc_types) >= HELDOUT_MIN_DOC_TYPES else "warn",
            f"{len(doc_types)} 种：{', '.join(doc_types)}（要求 ≥{HELDOUT_MIN_DOC_TYPES}）",
        ),
        _check(
            "heldout_profiles",
            "pass" if len(profiles) >= HELDOUT_MIN_PROFILES else "warn",
            f"{len(profiles)} 种：{', '.join(profiles)}（要求 ≥{HELDOUT_MIN_PROFILES}）",
        ),
        _check(
            "heldout_purity",
            "fail" if pure else "pass",
            f"heldout 扰动样本 {pure} 条（要求 0）",
        ),
        _check(
            "traceability",
            "warn" if trace["issues"] else "pass",
            f"缺证据/行号 {trace['issues']} 条（共 {trace['total']}）",
        ),
    ]

    return {
        "schema_version": "0.1.0",
        "goldset_version": manifest.get("goldset_version"),
        "dataset": _relative(dataset_dir),
        "documents": len(documents),
        "splits": {name: sorted(docs) for name, docs in splits.items()},
        "heldout": {"documents": len(heldout), "doc_types": doc_types, "profiles": profiles},
        "samples": report.get("samples") or {},
        "checks": checks,
        "status": "fail" if any(item["status"] == "fail" for item in checks) else "pass",
        "m2_2": _teacher_status(dataset_dir),
    }


def _teacher_status(dataset_dir: Path) -> dict[str, Any]:
    path = dataset_dir.parent / "teacher-v1" / "report.json"
    if not path.exists():
        return {
            "status": "pending",
            "requires": [
                "teacher.jsonl（教师输出与金标对齐）",
                "教师选型决策记录（成本/质量对比）",
                "L0/L1 过滤规则（无证据值不进训练）",
                "人工/蒸馏数据配比",
            ],
        }
    report = json.loads(path.read_text(encoding="utf-8"))
    return {
        "status": "complete",
        "teacher": report.get("teacher"),
        "accepted": report.get("accepted"),
        "field_accuracy": report.get("field_accuracy"),
        "exact_match_rate": report.get("exact_match_rate"),
        "mix": report.get("mix"),
    }


def _find_duplicates(splits: dict[str, list[str]]) -> str:
    seen: dict[str, str] = {}
    conflicts: list[str] = []
    for split, docs in splits.items():
        for doc_id in docs:
            if doc_id in seen:
                conflicts.append(f"{doc_id} 同时出现在 {seen[doc_id]} 与 {split}")
            seen[doc_id] = split
    return "；".join(conflicts)


def _family_conflicts(documents: list[dict[str, Any]]) -> str:
    families: dict[str, set[str]] = defaultdict(set)
    for doc in documents:
        standard_no = doc.get("standard_no") or doc["doc_id"]
        family = FAMILY_YEAR_RE.sub("", standard_no).strip()
        split = SPLIT_MAP.get(doc.get("split") or "dev", "dev")
        families[family].add(split)
    conflicts = [
        f"{family} 跨 {'/'.join(sorted(splits))}"
        for family, splits in families.items()
        if len(splits) > 1
    ]
    return "；".join(conflicts)


def _heldout_profiles(heldout: list[dict[str, Any]], gold_dir: Path) -> set[str]:
    profiles: set[str] = set()
    for doc in heldout:
        annotation = doc.get("annotation_file")
        if not annotation:
            continue
        path = gold_dir / annotation
        if not path.exists():
            continue
        gold = json.loads(path.read_text(encoding="utf-8"))
        for table in gold.get("tables") or []:
            profile = table.get("profile")
            if profile and profile != "unknown":
                profiles.add(profile)
    return profiles


def _heldout_perturbations(dataset_dir: Path) -> int:
    path = dataset_dir / "heldout.jsonl"
    if not path.exists():
        return 0
    return sum(
        1
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and json.loads(line).get("task") == "row_record_perturb"
    )


def _sample_rows(dataset_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for split in ("train", "dev", "heldout"):
        path = dataset_dir / f"{split}.jsonl"
        if not path.exists():
            continue
        rows.extend(
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        )
    return rows


def _traceability(rows: list[dict[str, Any]]) -> dict[str, Any]:
    issues = 0
    for row in rows:
        task = row.get("task")
        meta = row.get("meta") or {}
        if not row.get("doc_id"):
            issues += 1
            continue
        if task in {"row_record", "row_record_perturb"} and meta.get("row_index") is None:
            issues += 1
        elif task == "clause_extract" and not (row.get("input") or {}).get("quotes"):
            issues += 1
        elif task == "citation_constraint" and not (row.get("input") or {}).get("context"):
            issues += 1
        elif task == "header_mapping" and not (row.get("input") or {}).get("header_paths"):
            issues += 1
    return {"total": len(rows), "issues": issues}


def _check(check_id: str, status: str, detail: str) -> dict[str, str]:
    return {"id": check_id, "status": status, "detail": detail}


def _relative(path: Path) -> str:
    try:
        return path.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _render(readiness: dict[str, Any]) -> str:
    lines = [
        "# M2.1 数据就绪检查",
        "",
        f"- 数据集：`{readiness['dataset']}`（{readiness['documents']} 份文档）",
        f"- 结论：**{readiness['status']}**",
        "",
        "| 检查 | 状态 | 详情 |",
        "|---|---|---|",
    ]
    for item in readiness["checks"]:
        lines.append(f"| {item['id']} | {item['status']} | {item['detail']} |")
    heldout = readiness["heldout"]
    lines.extend(
        [
            "",
            "## heldout 覆盖",
            "",
            f"- 文档 {heldout['documents']} 份",
            f"- 文档类型：{', '.join(heldout['doc_types']) or '-'}",
            f"- 表型：{', '.join(heldout['profiles']) or '-'}",
            "",
            "## 训练样本",
            "",
            "| split | 任务 | 数量 |",
            "|---|---|---|",
        ]
    )
    for split, tasks in readiness["samples"].items():
        for task, count in tasks.items():
            lines.append(f"| {split} | {task} | {count} |")
    lines.extend(["", f"## M2.2（{readiness['m2_2']['status']}）", ""])
    if readiness["m2_2"]["status"] == "complete":
        m2_2 = readiness["m2_2"]
        lines.extend(
            [
                f"- 教师：{m2_2.get('teacher')}",
                f"- 接受样本：{m2_2.get('accepted')}，字段一致 {m2_2.get('field_accuracy')}，整条一致 {m2_2.get('exact_match_rate')}",
                f"- 配比：teacher {m2_2.get('mix', {}).get('teacher_share')}，{m2_2.get('mix', {}).get('policy')}",
            ]
        )
    else:
        lines.extend(f"- {item}" for item in readiness["m2_2"]["requires"])
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", default=str(ROOT / "goldset" / "v0"))
    parser.add_argument("--dataset", default=str(ROOT / "data" / "m2" / "train-v1"))
    parser.add_argument("--out", default=str(ROOT / "eval" / "m2"))
    args = parser.parse_args(argv)

    dataset_dir = Path(args.dataset)
    readiness = build_readiness(Path(args.gold), dataset_dir)
    (dataset_dir / "readiness.json").write_text(
        json.dumps(readiness, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "readiness.md").write_text(_render(readiness), encoding="utf-8")
    for item in readiness["checks"]:
        print(f"{item['status']:4} {item['id']:20} {item['detail']}")
    print(f"status={readiness['status']} out={out_dir / 'readiness.md'}")
    return 1 if readiness["status"] == "fail" else 0


if __name__ == "__main__":
    raise SystemExit(main())
