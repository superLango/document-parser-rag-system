#!/usr/bin/env python3
"""离线回放：md 中的 HTML 表格 → TableGrid → 配方匹配 → sandbox 解析。

不依赖模型/OCR 服务，用于在本地对比“生产结果 vs 当前算法重放”的覆盖差异。
用法（容器内）：
  python replay_md_parse.py --docs /data/标准拆分提取-... --folders 84,155,10 --out /out/replay.json
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

RECIPE_DIR = Path(os.environ.get("REPLAY_RECIPE_DIR", "/app/services/recipe_registry/data/recipes"))
RUNTIME_DIR = Path(os.environ.get("REPLAY_RUNTIME_DIR", "/app/services/sandbox/runtime"))
sys.path.insert(0, str(RUNTIME_DIR))

import builtin
import projection as projection_module

from services.ocr.algorithms.table_grid import TABLE_RE
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


def categories(records: list[dict]) -> Counter:
    counter: Counter = Counter()
    for rec in records:
        for prop in (rec.get("properties") or {}).values():
            if isinstance(prop, dict):
                counter[str(prop.get("business_category") or "")] += 1
    return counter


MEASURE_HINT_RE = re.compile(
    r"抗拉|屈服|延伸|伸长|收缩|冲击|硬度|晶粒|夹杂|低倍|高倍|超声|尺寸|外观|腐蚀|"
    r"\brm\b|rp0\.2|\bkv2\b|\bku2\b|\bhrc\b|\bhbw?\b|\bhv\b",
    re.IGNORECASE,
)


def replay_doc(
    folder: Path,
    recipes: dict[str, tuple[dict, RecipeManifest]],
    limit: int,
    dump_records: bool = False,
    dump_inventory: bool = False,
) -> dict:
    md_path = next(folder.glob("*.md"))
    text = md_path.read_text(encoding="utf-8", errors="ignore")
    # 生产环境每个沙箱进程只解析一份文档；回放是长进程，必须按文档清理
    # 表格指纹与文档文本缓存，否则相同样表/牌号提示会跨文档串扰。
    builtin._table_fingerprints.clear()
    builtin._DOCUMENT_TEXT_CACHE = text
    tables = TABLE_RE.findall(text)[:limit]
    recipe_list = [item[1] for item in recipes.values()]
    all_records: list[dict] = []
    all_evidence: list[dict] = []
    table_dumps: list[dict] = []
    table_rows = []
    diagnostics: list[dict] = []
    for index, html in enumerate(tables, start=1):
        table_id = f"{folder.name}-T{index}"
        table = parse_html_table(html, table_id, page_no=index, context=text[:500])
        if not table.rows:
            continue
        match = match_table(table, recipe_list)
        measure_cols = sum(
            1 for cell in (table.rows[0] if table.rows else []) if MEASURE_HINT_RE.search(str(cell))
        )
        entry = {
            "table_id": table_id,
            "profile": table.profile,
            "rows": table.n_rows,
            "cols": table.n_cols,
            "measure_cols": measure_cols,
            "recipe": match.recipe_id,
            "score": round(match.score, 3),
            "status": match.status,
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
            records, evidence, summary = builtin.parse_table(
                table.model_dump(mode="json"), manifest, assignment, diagnostics
            )
            entry["records"] = summary.get("records", len(records))
            entry["props"] = sum(len(rec.get("properties") or {}) for rec in records)
            all_records.extend(records)
            all_evidence.extend(evidence)
            table_dumps.append(table.model_dump(mode="json"))
        table_rows.append(entry)

    prose_records, prose_evidence = builtin.document_heat_records({"markdown": text})
    all_records.extend(prose_records)
    all_evidence.extend(prose_evidence)

    all_records.sort(
        key=lambda item: (item.get("page_no", 0), item.get("table_id", ""), item.get("row_index", 0))
    )
    all_records = builtin._merge_fragments(all_records)
    all_records, _ = builtin._disambiguate_duplicate_keys(all_records, diagnostics)
    ocr_payload = {
        "schema_version": "replay/1",
        "markdown": text,
        "tables": table_dumps,
        "pages": [],
        "layout": [],
        "backend": "replay",
    }
    intelligence = projection_module.apply_document_intelligence(
        all_records, all_evidence, ocr_payload, diagnostics
    )
    result = {
        "folder": folder.name,
        "name": md_path.stem,
        "tables": len(tables),
        "records": len(all_records),
        "categories": dict(categories(all_records)),
        "table_details": table_rows,
        "diagnostics": len(diagnostics),
        "prod": _prod_summary(folder),
    }
    if dump_records:
        result["record_list"] = [
            {
                "page": rec.get("page_no"),
                "grade": rec.get("grade"),
                "cond": rec.get("condition_key"),
                "profile": rec.get("profile"),
                "props": sorted(rec.get("properties") or {}),
                "values": {
                    key: {
                        "raw": (val or {}).get("raw"),
                        "comparator": (val or {}).get("comparator"),
                        "lower": (val or {}).get("lower"),
                        "upper": (val or {}).get("upper"),
                        "unit": (val or {}).get("unit"),
                    }
                    for key, val in (rec.get("properties") or {}).items()
                    if isinstance(val, dict)
                },
                "cats": sorted(
                    {
                        str((p or {}).get("business_category") or "")
                        for p in (rec.get("properties") or {}).values()
                        if isinstance(p, dict)
                    }
                ),
            }
            for rec in all_records
        ]
    if dump_inventory:
        result["intelligence"] = intelligence.get("intelligence", {})
        result["inventory_items"] = [
            {
                "feature": entry.get("feature"),
                "item": entry.get("item"),
                "clause_id": entry.get("clause_id"),
                "requirement": (entry.get("requirement") or "")[:200],
                "requirements": [
                    {
                        "text": (row.get("text") or "")[:200],
                        "clause_id": row.get("clause_id"),
                    }
                    for row in (entry.get("requirements") or [])
                ],
            }
            for entry in (intelligence.get("inventory") or {}).get("items", [])
        ]
    return result


def _prod_summary(folder: Path) -> dict:
    files = list(folder.glob("*.json"))
    if not files:
        return {}
    try:
        data = json.loads(files[0].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    records = data.get("records") or []
    return {"records": len(records), "categories": dict(categories(records))}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--docs", required=True)
    parser.add_argument("--folders", default="")
    parser.add_argument("--limit", type=int, default=200)
    parser.add_argument("--channel", default="stable")
    parser.add_argument("--dump", action="store_true")
    parser.add_argument("--dump-inventory", action="store_true")
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    docs_root = Path(args.docs)
    names = [name for name in args.folders.split(",") if name and name != "."]
    folders = (
        [docs_root / name for name in names]
        if names
        else sorted(p for p in docs_root.iterdir() if p.is_dir())
    )
    recipes = load_recipes(args.channel)
    results = []
    for folder in folders:
        if not folder.is_dir() or not any(folder.glob("*.md")):
            continue
        results.append(
            replay_doc(
                folder,
                recipes,
                args.limit,
                dump_records=args.dump,
                dump_inventory=args.dump_inventory,
            )
        )
        item = results[-1]
        print(
            f"{item['folder']:>4} tables={item['tables']:<4d} "
            f"records={item['records']:<4d} "
            f"cats={json.dumps(item['categories'], ensure_ascii=False)[:120]}"
        )
    if args.out:
        Path(args.out).write_text(
            json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
