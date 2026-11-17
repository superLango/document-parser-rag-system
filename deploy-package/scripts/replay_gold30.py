#!/usr/bin/env python3
"""30 份人工金标离线回放与字段覆盖对比。

输入：gold_standard_30/source_tables/<doc_id>.json 的 header_rows/data_rows
输出：按文档、按 FEATURE 的金标数量 vs 回放数量，以及缺失项清单。

不依赖 OCR/模型；用于 P1/P2/P3 算法改动的回归基准。
"""

from __future__ import annotations

import argparse
import html
import json
import os
import sys
from collections import Counter
from pathlib import Path

RECIPE_DIR = Path(
    os.environ.get("REPLAY_RECIPE_DIR", "/app/services/recipe_registry/data/recipes")
)
RUNTIME_DIR = Path(os.environ.get("REPLAY_RUNTIME_DIR", "/app/services/sandbox/runtime"))
sys.path.insert(0, str(RUNTIME_DIR))

import builtin
import projection as projection_module

from services.ocr.algorithms.table_grid import parse_table as parse_html_table
from services.recipe_registry.matcher import match_table
from services.recipe_registry.package import RecipeManifest


def load_recipes(channel: str = "stable") -> dict[str, tuple[dict, RecipeManifest]]:
    registry = json.loads((RECIPE_DIR / "registry.json").read_text(encoding="utf-8"))
    pointers = registry["channels"][channel]
    out: dict[str, tuple[dict, RecipeManifest]] = {}
    for recipe_id, version in pointers.items():
        manifest = json.loads(
            (RECIPE_DIR / recipe_id / version / "manifest.json").read_text(encoding="utf-8")
        )
        out[recipe_id] = (manifest, RecipeManifest.model_validate(manifest))
    return out


def table_html(table: dict) -> str:
    parts = ["<table><thead>"]
    for row in table.get("header_rows") or []:
        parts.append(
            "<tr>" + "".join(f"<th>{html.escape(str(cell))}</th>" for cell in row) + "</tr>"
        )
    parts.append("</thead><tbody>")
    for row in table.get("data_rows") or []:
        parts.append(
            "<tr>" + "".join(f"<td>{html.escape(str(cell))}</td>" for cell in row) + "</tr>"
        )
    parts.append("</tbody></table>")
    return "".join(parts)


def replay_doc(
    source: dict,
    recipes: dict[str, tuple[dict, RecipeManifest]],
) -> dict:
    doc_id = str(source.get("doc_id") or "")
    title = str(source.get("title") or "")
    builtin._table_fingerprints.clear()
    builtin._DOCUMENT_TEXT_CACHE = title
    recipe_list = [item[1] for item in recipes.values()]
    records: list[dict] = []
    evidence: list[dict] = []
    diagnostics: list[dict] = []
    table_dumps: list[dict] = []
    details: list[dict] = []
    for index, table in enumerate(source.get("tables") or [], start=1):
        table_id = str(table.get("table_id") or f"T{index}")
        grid = parse_html_table(
            table_html(table),
            table_id,
            page_no=int(table.get("page_no") or 0),
            caption=str(table.get("caption") or ""),
            context=title,
        )
        if not grid.rows:
            continue
        match = match_table(grid, recipe_list)
        entry = {
            "table_id": table_id,
            "rows": grid.n_rows,
            "cols": grid.n_cols,
            "profile": grid.profile,
            "recipe": match.recipe_id,
            "status": match.status,
            "score": round(match.score, 3),
            "records": 0,
            "props": 0,
        }
        if match.recipe_id:
            manifest = recipes[match.recipe_id][0]
            assignment = {
                "table_id": table_id,
                "recipe_id": match.recipe_id,
                "version": match.version,
            }
            parsed, parsed_evidence, summary = builtin.parse_table(
                grid.model_dump(mode="json"), manifest, assignment, diagnostics
            )
            entry["records"] = summary.get("records", len(parsed))
            entry["props"] = sum(len(rec.get("properties") or {}) for rec in parsed)
            records.extend(parsed)
            evidence.extend(parsed_evidence)
            table_dumps.append(grid.model_dump(mode="json"))
        details.append(entry)

    records = builtin._merge_fragments(records)
    records, _ = builtin._disambiguate_duplicate_keys(records, diagnostics)
    ocr_payload = {
        "schema_version": "gold-replay/1",
        "markdown": title,
        "tables": table_dumps,
        "pages": [],
        "layout": [],
        "backend": "gold-replay",
    }
    projection_module.apply_document_intelligence(records, evidence, ocr_payload, diagnostics)

    feature_counts: Counter = Counter()
    grades: set[str] = set()
    for record in records:
        grade = str(record.get("grade") or "").strip()
        if grade and grade != "~":
            grades.add(grade)
        for measure, prop in (record.get("properties") or {}).items():
            if not isinstance(prop, dict):
                continue
            feature = str(prop.get("feature") or "")
            if not feature:
                feature = builtin._feature_for_measure(record, str(measure))
            feature_counts[feature] += 1
    return {
        "doc_id": doc_id,
        "title": title,
        "tables": len(source.get("tables") or []),
        "recipes": len(table_dumps),
        "records": len(records),
        "props": sum(feature_counts.values()),
        "features": dict(feature_counts),
        "grades": sorted(grades),
        "table_details": details,
    }


def gold_summary(document: dict) -> dict:
    features: Counter = Counter()
    grades: set[str] = set()
    for category in document.get("categories") or []:
        feature = str(category.get("feature") or "")
        for record in category.get("records") or []:
            features[feature] += 1
            grade = str(record.get("材料牌号") or "").strip()
            if grade and grade != "全部牌号":
                grades.add(grade)
    return {"features": dict(features), "grades": sorted(grades)}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default="/data/gold_standard_30")
    parser.add_argument("--channel", default="stable")
    parser.add_argument("--only", default="")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    root = Path(args.root)
    index = json.loads((root / "index.json").read_text(encoding="utf-8"))
    wanted = {name for name in args.only.split(",") if name}
    recipes = load_recipes(args.channel)
    results = []
    for item in index["documents"]:
        doc_id = str(item["doc_id"])
        if wanted and doc_id not in wanted:
            continue
        source = json.loads(
            (root / "source_tables" / f"{doc_id}.json").read_text(encoding="utf-8")
        )
        document = json.loads(
            (root / "documents" / f"{doc_id}.json").read_text(encoding="utf-8")
        )
        replay = replay_doc(source, recipes)
        gold = gold_summary(document)
        missing = {
            feature: gold["features"][feature] - replay["features"].get(feature, 0)
            for feature in gold["features"]
            if gold["features"][feature] > replay["features"].get(feature, 0)
        }
        replay["gold"] = gold
        replay["missing"] = missing
        replay["feature_rows"] = {
            feature: {
                "gold": gold["features"].get(feature, 0),
                "replay": replay["features"].get(feature, 0),
            }
            for feature in sorted(gold["features"])
        }
        results.append(replay)
        print(
            f"{doc_id[:3]:>3} {item.get('standard_no', '')[:34]:<34} "
            f"gold={sum(gold['features'].values()):<5d} replay={replay['props']:<5d} "
            f"missing={json.dumps(missing, ensure_ascii=False)[:120]}"
        )
    if args.out:
        Path(args.out).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
