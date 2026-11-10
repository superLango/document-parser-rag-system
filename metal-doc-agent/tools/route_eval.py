"""Routing evaluation over replayed runs (M2.5.2-05).

Applies ``decide_route`` to every table in ``runs/<run>/<doc>/tablegrid`` and
reports queue distribution, per-profile novelty and per-document queueing.

Usage:
    python -m tools.route_eval --runs runs/m2_baseline \
      --out eval/recipes/routing.json
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from metal_doc_agent.contracts import TableGrid
from metal_doc_agent.recipes import decide_route, doc_queue, load_recipes
from metal_doc_agent.tablegrid.profile import annotate_table

ROOT = Path(__file__).resolve().parents[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", default=str(ROOT / "runs" / "m2_baseline"))
    parser.add_argument("--out", default=str(ROOT / "eval" / "recipes" / "routing.json"))
    args = parser.parse_args(argv)

    runs_dir = Path(args.runs)
    recipes = load_recipes()
    docs: dict[str, list[dict]] = defaultdict(list)
    by_profile: dict[str, Counter] = defaultdict(Counter)
    admin_tables = 0

    for table_path in sorted(runs_dir.glob("*/tablegrid/*.json")):
        doc_id = table_path.parents[1].name
        table = annotate_table(
            TableGrid.model_validate(
                json.loads(table_path.read_text(encoding="utf-8"))
            )
        )
        if table.profile == "admin":
            # Signature blocks / revision history / document lists are not
            # extraction targets and never enter a routing lane.
            admin_tables += 1
            continue
        decision = decide_route(table, recipes)
        docs[doc_id].append(
            {
                "table_id": table.table_id,
                "profile": table.profile,
                **decision.to_dict(),
            }
        )
        by_profile[table.profile][decision.queue] += 1
        by_profile[table.profile]["tables"] += 1

    doc_summary = {}
    for doc_id, tables in docs.items():
        decisions = [
            _DecisionView(entry) for entry in tables
        ]
        doc_summary[doc_id] = {
            "queue": doc_queue(decisions),
            "tables": len(tables),
            "production": sum(1 for entry in tables if entry["queue"] == "production"),
            "explore": sum(1 for entry in tables if entry["queue"] == "explore"),
            "human": sum(1 for entry in tables if entry["queue"] == "human"),
        }

    total_tables = sum(len(tables) for tables in docs.values())
    novelty = sum(
        1
        for tables in docs.values()
        for entry in tables
        if entry["status"] == "unknown"
    )
    summary = {
        "documents": len(docs),
        "tables": total_tables,
        "production_tables": sum(entry["production"] for entry in doc_summary.values()),
        "explore_tables": sum(entry["explore"] for entry in doc_summary.values()),
        "human_tables": sum(entry["human"] for entry in doc_summary.values()),
        "production_docs": sum(
            1 for entry in doc_summary.values() if entry["queue"] == "production"
        ),
        "production_doc_rate": round(
            sum(1 for entry in doc_summary.values() if entry["queue"] == "production")
            / max(1, len(doc_summary)),
            4,
        ),
        "novelty_rate": round(novelty / max(1, total_tables), 4),
        "recipes": len(recipes),
        "admin_tables": admin_tables,
        "tables_total": total_tables + admin_tables,
    }
    report = {
        "runs": runs_dir.as_posix(),
        "summary": summary,
        "by_profile": {profile: dict(stats) for profile, stats in by_profile.items()},
        "documents": doc_summary,
        "tables": {doc_id: entries for doc_id, entries in docs.items()},
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    print(f"out={out}")
    return 0


class _DecisionView:
    """Minimal decision view so ``doc_queue`` can read a serialized entry."""

    def __init__(self, entry: dict) -> None:
        self.queue = entry["queue"]


if __name__ == "__main__":
    raise SystemExit(main())
