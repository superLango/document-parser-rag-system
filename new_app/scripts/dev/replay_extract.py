"""离线复现「提取」导出的解析结果：md → OCR 表格 → 路由 → 沙箱 runner → records。

尽量贴近生产链路（extract_tables + repairs + quality + matcher + 兄弟表兜底 + runner.run_builtin），
不含 RouterAgent（LLM）与分页信息，所以记录数可能与生产略有出入。

用法（在 new_app 下）：
  python scripts/dev/replay_extract.py --docs <提取目录> --ids 0ff7c056,13c27dd9 \
      [--engine services/sandbox/runtime] [--dict <dictionary_data.json>] --out <输出目录>
每个文档输出 <out>/<folder>/records.json（与导出 JSON 同结构）。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from services.ocr.algorithms.quality import score_tables  # noqa: E402
from services.ocr.algorithms.repairs import apply_repairs, load_rules  # noqa: E402
from services.ocr.algorithms.table_grid import extract_tables  # noqa: E402
from services.ocr.contracts import DocumentMeta, Page  # noqa: E402
from services.orchestration.workflow import (  # noqa: E402
    ROUTE_AGENT_MIN_CONFIDENCE,
    ROUTE_LOW_CONFIDENCE,
    apply_sibling_fallback,
    select_agent_tables,
)
from services.recipe_registry.matcher import match_table  # noqa: E402
from services.recipe_registry.package import RecipeManifest  # noqa: E402

RECIPES = ROOT / "services/recipe_registry/data/recipes"
MIN_QUALITY = 0.25


def stable_recipes() -> dict[str, dict]:
    pointers = json.loads((RECIPES / "registry.json").read_text(encoding="utf-8"))["channels"]["stable"]
    return {
        rid: json.loads((RECIPES / rid / ver / "manifest.json").read_text(encoding="utf-8"))
        for rid, ver in pointers.items()
    }


AGENT_URL = ""


def route_with_agent(pending: list[tuple[dict, dict]], manifests: dict[str, dict]) -> None:
    """与 orchestration._route_with_agent 相同的请求：真实 RouterAgent 给低置信表选配方。"""
    import httpx

    task = {
        "task_id": f"route-replay-{pending[0][1]['table_id']}",
        "trace_id": "replay",
        "role": "router",
        "objective": "Assign every table to exactly one recipe from the catalog.",
        "inputs": {
            "tables": [table for table, _ in pending],
            "catalog": [{"recipe_id": rid, "version": m["version"]} for rid, m in manifests.items()],
            "deterministic": [item for _, item in pending],
        },
        "budget": {"max_steps": 1, "max_tool_calls": 0, "max_tokens": 32000, "wall_time_seconds": 90},
    }
    try:
        response = httpx.post(f"{AGENT_URL.rstrip('/')}/internal/agent:run", json=task, timeout=180)
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        print(f"  agent error: {exc}", file=sys.stderr)
        return
    if response.status_code != 200 or payload.get("degraded"):
        print(f"  agent degraded: {response.status_code} {str(payload)[:200]}", file=sys.stderr)
        return
    chosen = {str(a.get("table_id")): a for a in (payload.get("output") or {}).get("assignments") or []}
    for table, item in pending:
        pick = chosen.get(str(table.get("table_id")))
        if pick and float(pick.get("confidence") or 0) >= ROUTE_AGENT_MIN_CONFIDENCE:
            item.update(recipe_id=pick.get("recipe_id"), version=pick.get("version"), status="agent",
                        score=float(pick["confidence"]), confidence=float(pick["confidence"]))
        print(f"  agent {table.get('table_id')}: {pick and (pick.get('recipe_id'), pick.get('confidence'))}")


def route(markdown: str, name: str, manifests: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    tables = extract_tables([Page(page_no=1, markdown=markdown)])
    tables, _ = apply_repairs(tables, document=DocumentMeta(file_name=name), rules=load_rules(None))
    tables = score_tables(tables)
    dumped = [t.model_dump(mode="json") for t in tables]
    models = [RecipeManifest.model_validate(m) for m in manifests.values()]
    assignments = []
    for table, raw in zip(tables, dumped):
        if float(raw.get("quality", 1.0)) < MIN_QUALITY:
            continue
        m = match_table(table, models)
        assignments.append(
            {
                "table_id": table.table_id,
                "page_no": table.page_no,
                "recipe_id": m.recipe_id,
                "version": m.version,
                "status": m.status,
                "score": m.score,
                "confidence": m.score,
                "margin": m.margin,
            }
        )
    by_id = {t["table_id"]: t for t in dumped}
    pending = select_agent_tables(
        [(by_id[a["table_id"]], a) for a in assignments if not a.get("recipe_id") or float(a.get("score") or 0) < ROUTE_LOW_CONFIDENCE]
    )
    if pending and AGENT_URL:
        route_with_agent(pending, manifests)
    else:
        # shortcut: 没有 --agent-url 时，按表画像直接给同名配方模拟 RouterAgent，结果可能与生产有出入。
        for table, entry in pending:
            recipe_id = f"{table['profile']}_v1"
            if recipe_id in manifests:
                entry.update(recipe_id=recipe_id, version=manifests[recipe_id]["version"], score=0.7, status="agent")
    apply_sibling_fallback(assignments, by_id)
    routed = [a for a in assignments if a.get("recipe_id") and float(a.get("score") or 0) >= ROUTE_LOW_CONFIDENCE]
    return dumped, routed


def run_doc(folder: Path, out: Path, engine: Path, manifests: dict[str, dict]) -> int:
    md_path = next(folder.glob("*.md"))
    markdown = md_path.read_text(encoding="utf-8", errors="ignore")
    tables, routed = route(markdown, md_path.stem + ".pdf", manifests)
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        (work / "input").mkdir()
        (work / "output").mkdir()
        for rid, manifest in manifests.items():
            (work / "recipes" / rid).mkdir(parents=True)
            (work / "recipes" / rid / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        request = {
            "recipe": {"recipe_id": routed[0]["recipe_id"]} if routed else {},
            "assignments": routed,
            "document": {"filename": md_path.stem + ".pdf"},
        }
        (work / "input" / "request.json").write_text(json.dumps(request, ensure_ascii=False), encoding="utf-8")
        # shortcut: 导出的 md 没有分页；封面判定（方法标准等）只看第 1 页，这里取开头一段当封面。
        cut = markdown.find("\n", 1500)
        cut = len(markdown) if cut < 0 else cut
        pages = [{"page_no": 1, "markdown": markdown[:cut]}, {"page_no": 2, "markdown": markdown[cut:]}]
        ocr = {"markdown": markdown, "tables": tables, "pages": pages}
        (work / "input" / "ocr.json").write_text(json.dumps(ocr, ensure_ascii=False), encoding="utf-8")
        env = dict(os.environ)
        env.update(
            HANSON_ENGINE_DIR=str(engine),
            HANSON_INPUT_DIR=str(work / "input"),
            HANSON_OUTPUT_DIR=str(work / "output"),
            HANSON_RECIPE_DIR=str(work / "recipes"),
            HANSON_REQUEST=str(work / "input" / "request.json"),
            PYTHONIOENCODING="utf-8",
        )
        proc = subprocess.run([sys.executable, "-B", str(engine / "runner.py")], env=env, capture_output=True, text=True, encoding="utf-8")
        if proc.returncode:
            print(proc.stderr[-2000:], file=sys.stderr)
            return proc.returncode
        target = out / folder.name
        target.mkdir(parents=True, exist_ok=True)
        records = json.loads((work / "output" / "records.json").read_text(encoding="utf-8"))["records"]
        (target / "records.json").write_text(json.dumps({"result": None, "records": records}, ensure_ascii=False, indent=1), encoding="utf-8")
        for name in ("inventory.json", "diagnostics.json"):
            shutil.copy(work / "output" / name, target / name)
    print(f"{folder.name[:8]} tables={len(tables)} routed={len(routed)} records={len(records)}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", required=True)
    ap.add_argument("--ids", default="", help="逗号分隔的文件夹名前缀；空=全部")
    ap.add_argument("--engine", default=str(ROOT / "services/sandbox/runtime"))
    ap.add_argument("--dict", default="", help="替换 dictionary_data.json（如派克词典）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--agent-url", default="", help="agent 服务地址；给了就用真实 RouterAgent 路由低置信表")
    args = ap.parse_args()
    global AGENT_URL
    AGENT_URL = args.agent_url
    engine = Path(args.engine).resolve()
    if args.dict:
        copy = Path(tempfile.mkdtemp()) / "engine"
        shutil.copytree(engine, copy, ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copy(args.dict, copy / "dictionary_data.json")
        engine = copy
    prefixes = [p for p in args.ids.split(",") if p]
    folders = sorted(
        p for p in Path(args.docs).iterdir()
        if p.is_dir() and any(p.glob("*.md")) and (not prefixes or any(p.name.startswith(x) for x in prefixes))
    )
    manifests = stable_recipes()
    out = Path(args.out)
    return max((run_doc(f, out, engine, manifests) for f in folders), default=0)


if __name__ == "__main__":
    raise SystemExit(main())
