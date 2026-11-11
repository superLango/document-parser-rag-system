"""Binding coverage and recipe hit report over replayed runs (M2.5.1-03/06).

Reads ``runs/<run>/<doc>/tablegrid/*.json``, routes each table to an active
recipe, binds columns, and reports:

* doc-level recipe hit rate (any table routed ``exact``)
* table-level exact/candidate/unknown distribution
* bound vs unmapped columns per profile

Usage:
    python -m tools.recipe_coverage --runs runs/m2_baseline \
      --out eval/recipes/binding-coverage.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from metal_doc_agent.contracts import TableGrid
from metal_doc_agent.recipes import bind_columns, load_recipes, route_table
from metal_doc_agent.tablegrid.profile import annotate_table

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", default=str(ROOT / "runs" / "m2_baseline"))
    parser.add_argument("--out", default=str(ROOT / "eval" / "recipes" / "binding-coverage.json"))
    args = parser.parse_args(argv)

    runs_dir = Path(args.runs)
    recipes = load_recipes()
    docs: dict[str, dict] = {}
    by_profile: dict[str, Counter] = defaultdict(Counter)

    for table_path in sorted(runs_dir.glob("*/tablegrid/*.json")):
        doc_id = table_path.parents[1].name
        table = annotate_table(
            TableGrid.model_validate(
                json.loads(table_path.read_text(encoding="utf-8"))
            )
        )
        if table.profile == "admin":
            # Cover pages, signature blocks and document lists are not extraction
            # targets; counting their columns would understate binding coverage.
            continue
        match = route_table(table, recipes)
        result = bind_columns(table, recipe=match.recipe, match_status=match.status)
        mapped = sum(1 for binding in result.bindings if binding.status != "unmapped")
        total = len(result.bindings)
        entry = docs.setdefault(
            doc_id, {"tables": 0, "exact": 0, "candidate": 0, "unknown": 0, "mapped": 0, "columns": 0}
        )
        entry["tables"] += 1
        entry[match.status] = entry.get(match.status, 0) + 1
        entry["mapped"] += mapped
        entry["columns"] += total
        stats = by_profile[table.profile]
        stats["tables"] += 1
        stats[match.status] += 1
        stats["mapped"] += mapped
        stats["columns"] += total

    doc_hits = sum(1 for entry in docs.values() if entry["exact"] > 0)
    doc_candidates = sum(
        1 for entry in docs.values() if entry["exact"] > 0 or entry["candidate"] > 0
    )
    summary = {
        "documents": len(docs),
        "doc_hit_rate": round(doc_hits / len(docs), 4) if docs else 0.0,
        "doc_candidate_rate": round(doc_candidates / len(docs), 4) if docs else 0.0,
        "tables": sum(entry["tables"] for entry in docs.values()),
        "exact": sum(entry["exact"] for entry in docs.values()),
        "candidate": sum(entry["candidate"] for entry in docs.values()),
        "unknown": sum(entry["unknown"] for entry in docs.values()),
        "bound_columns": sum(entry["mapped"] for entry in docs.values()),
        "total_columns": sum(entry["columns"] for entry in docs.values()),
        "binding_rate": round(
            sum(entry["mapped"] for entry in docs.values())
            / max(1, sum(entry["columns"] for entry in docs.values())),
            4,
        ),
        "recipes": len(recipes),
    }
    report = {
        "runs": runs_dir.as_posix(),
        "summary": summary,
        "by_profile": {profile: dict(stats) for profile, stats in by_profile.items()},
        "documents": docs,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    print(f"out={out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
