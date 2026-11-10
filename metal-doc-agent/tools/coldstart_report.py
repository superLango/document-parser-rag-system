"""Cold-start dashboard: clustering, T1/T2/T3 and G2.5 metrics (M2.5.4-01/02/04).

Usage:
    python -m tools.coldstart_report --runs runs/m2_baseline \
      --out eval/coldstart.json --md eval/coldstart.md
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from metal_doc_agent.contracts import TableGrid
from metal_doc_agent.queues import QueueStore
from metal_doc_agent.recipes import build_report, load_recipes, render_markdown
from metal_doc_agent.recipes.lifecycle import RecipeRegistry
from metal_doc_agent.tablegrid.profile import annotate_table

ROOT = Path(__file__).resolve().parents[1]
RECIPE_DIR = ROOT / "configs" / "recipes"
CANDIDATE_DIR = RECIPE_DIR / "candidates"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs", default=str(ROOT / "runs" / "m2_baseline"))
    parser.add_argument("--recipes", default=str(RECIPE_DIR))
    parser.add_argument("--queues", default=str(ROOT / "data" / "queues"))
    parser.add_argument("--out", default=str(ROOT / "eval" / "coldstart.json"))
    parser.add_argument("--md", default=str(ROOT / "eval" / "coldstart.md"))
    parser.add_argument("--top", type=int, default=20)
    args = parser.parse_args(argv)

    tables = _load_tables(Path(args.runs))
    recipes = load_recipes(Path(args.recipes))
    queue_stats = _queue_stats(Path(args.queues))
    candidate_files = len(list(CANDIDATE_DIR.glob("*.json")))
    registry = RecipeRegistry(Path(args.recipes) / "registry.json")
    promoted = sum(
        1
        for path in CANDIDATE_DIR.glob("*.json")
        if registry.level_of(path.stem) in {"L3", "L4"}
    )
    report = build_report(
        tables,
        recipes,
        queue_stats=queue_stats,
        candidate_files=candidate_files,
        promoted_candidates=promoted,
    )
    report["generated_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    report["runs"] = str(Path(args.runs))
    report["recipes"] = str(Path(args.recipes))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    md = Path(args.md)
    md.parent.mkdir(parents=True, exist_ok=True)
    md.write_text(render_markdown(report, top=args.top), encoding="utf-8")
    metrics = report["metrics"]
    print(
        f"tables={metrics['tables']} docs={metrics['documents']} "
        f"hit={metrics['hit_rate']:.4f} novelty={metrics['novelty_rate']:.4f} "
        f"t3={metrics['t3_ratio']:.4f} clusters={metrics['clusters']} "
        f"tiers={metrics['tiers']}"
    )
    print(f"out={out}")
    return 0


def _load_tables(runs_dir: Path) -> list[tuple[str, TableGrid]]:
    tables: list[tuple[str, TableGrid]] = []
    for path in sorted(runs_dir.glob("*/tablegrid/*.json")):
        table = annotate_table(
            TableGrid.model_validate_json(path.read_text(encoding="utf-8"))
        )
        tables.append((path.parents[1].name, table))
    return tables


def _queue_stats(queue_dir: Path) -> dict[str, int]:
    if not queue_dir.exists():
        return {"production": 0, "explore": 0, "human": 0}
    return QueueStore(queue_dir).stats()


if __name__ == "__main__":
    raise SystemExit(main())
