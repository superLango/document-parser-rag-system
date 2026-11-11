#!/usr/bin/env python3
"""RouterAgent accuracy against the deterministic M3 matcher."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path

from hanson_contracts import AgentBudget, AgentTask

from services.agent.agents.router import RouterAgent
from services.agent.context import ContextManager, HeuristicTokenizer
from services.agent.model_gateway import ModelEndpoint, ModelGateway, ModelGatewayConfig
from services.agent.prompts import PromptLibrary
from services.agent.session import SessionStore
from services.ocr.contracts import TableGrid
from services.recipe_registry.matcher import match_table
from services.recipe_registry.package import RecipeManifest, load_package

NEW_APP = Path(__file__).resolve().parents[2]
GOLDEN = NEW_APP / "tests" / "golden" / "table"
RECIPES = NEW_APP / "services" / "recipe_registry" / "data" / "recipes"
PROFILE_RECIPES = {
    "chemical_composition": "chemical_composition_v1",
    "inspection": "inspection_rules_v1",
    "mechanical_properties": "mechanical_properties_v1",
    "hardness": "hardness_v1",
}


def load_catalog() -> list[RecipeManifest]:
    manifests: list[RecipeManifest] = []
    for path in sorted(RECIPES.glob("*/*/manifest.json")):
        manifests.append(load_package(path.parent))
    return manifests


def load_tables() -> list[TableGrid]:
    tables: list[TableGrid] = []
    for path in sorted(GOLDEN.glob("*.json")):
        payload = json.loads(path.read_text(encoding="utf-8"))
        for index, expect in enumerate(payload.get("expect") or []):
            tables.append(
                TableGrid(
                    table_id=f"{path.stem}-T{index + 1}",
                    page_no=1,
                    profile=str(expect.get("profile") or "unknown"),
                    orientation=str(expect.get("orientation") or "grade_rows"),
                    n_cols=int(expect.get("n_cols") or 0),
                    header_rows=int(expect.get("header_rows") or 1),
                    header_paths=expect.get("header_paths") or [],
                    rows=expect.get("data_rows") or [],
                )
            )
    return tables


def deterministic_for(table: TableGrid, manifests: list[RecipeManifest]) -> dict:
    result = match_table(table, manifests)
    return {
        "table_id": table.table_id,
        "recipe_id": result.recipe_id,
        "version": result.version,
        "confidence": result.score,
        "status": result.status,
        "reasons": [result.status],
    }


async def evaluate(args: argparse.Namespace) -> int:
    manifests = load_catalog()
    tables = load_tables()
    if not tables:
        raise SystemExit("no golden tables found")
    catalog = [
        {
            "recipe_id": item.recipe_id,
            "version": item.version,
            "profile": item.profile,
            "signature": item.signature.model_dump(),
        }
        for item in manifests
    ]
    results = []
    matches = 0
    gold_matches = 0
    baseline_gold_matches = 0
    gateway = ModelGateway(
        ModelGatewayConfig(
            model=args.model,
            endpoints=(ModelEndpoint(name="tertiary", base_url=args.base_url),),
            timeout_seconds=args.timeout,
            max_tokens=512,
        )
    )
    sessions = SessionStore(args.session_db)
    agent = RouterAgent(
        gateway,
        ContextManager(HeuristicTokenizer(), max_tokens=8000),
        sessions,
        PromptLibrary(),
    )
    try:
        for table in tables:
            baseline = deterministic_for(table, manifests)
            task = AgentTask(
                task_id=f"router-eval-{table.table_id}",
                trace_id="router-eval",
                role="router",
                objective="choose the best recipe for this table",
                inputs={
                    "tables": [table.model_dump(mode="json")],
                    "catalog": catalog,
                    "deterministic": [baseline],
                },
                budget=AgentBudget(max_steps=2, max_tool_calls=0, max_tokens=8000),
            )
            started = time.perf_counter()
            result = await agent.run(task)
            latency_ms = int((time.perf_counter() - started) * 1000)
            assignments = result.output.get("assignments") or []
            chosen = assignments[0] if assignments else {}
            matched = (
                chosen.get("recipe_id") == baseline.get("recipe_id")
                and chosen.get("version") == baseline.get("version")
            )
            gold_recipe = PROFILE_RECIPES.get(table.profile)
            agent_matched_gold = (
                bool(gold_recipe) and chosen.get("recipe_id") == gold_recipe
            )
            baseline_matched_gold = (
                bool(gold_recipe) and baseline.get("recipe_id") == gold_recipe
            )
            matches += 1 if matched else 0
            gold_matches += 1 if agent_matched_gold else 0
            baseline_gold_matches += 1 if baseline_matched_gold else 0
            results.append(
                {
                    "table_id": table.table_id,
                    "profile": table.profile,
                    "gold_recipe": gold_recipe,
                    "deterministic": baseline,
                    "agent": chosen,
                    "matched_deterministic": matched,
                    "agent_matched_gold": agent_matched_gold,
                    "deterministic_matched_gold": baseline_matched_gold,
                    "degraded": result.degraded,
                    "latency_ms": latency_ms,
                    "usage": result.usage.model_dump(),
                }
            )
            print(json.dumps(results[-1], ensure_ascii=False), flush=True)
    finally:
        sessions.close()
        await gateway.close()
    summary = {
        "model": args.model,
        "tables": len(tables),
        "agreement": round(matches / len(tables), 4),
        "agent_accuracy": round(gold_matches / len(tables), 4),
        "deterministic_accuracy": round(baseline_gold_matches / len(tables), 4),
        "results": results,
    }
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"agent_accuracy={summary['agent_accuracy']} "
        f"deterministic_accuracy={summary['deterministic_accuracy']} "
        f"agreement={summary['agreement']} written {output}",
        flush=True,
    )
    return 0 if summary["agent_accuracy"] >= summary["deterministic_accuracy"] else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="RouterAgent accuracy evaluation")
    parser.add_argument("--base-url", default="http://192.168.1.35:9988")
    parser.add_argument("--model", default="Qwen3.6-35B-A3B-NVFP4")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--session-db", default="/tmp/hanson-agent/router-eval.db")
    parser.add_argument("--out", default="docs/reports/M5-router-eval.json")
    args = parser.parse_args()
    return asyncio.run(evaluate(args))


if __name__ == "__main__":
    raise SystemExit(main())
