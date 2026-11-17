import json
import os
import sys
from pathlib import Path

RUNTIME_DIR = os.environ.get("REPLAY_RUNTIME_DIR", "/app/services/sandbox/runtime")
RECIPE_DIR = Path(os.environ.get("REPLAY_RECIPE_DIR", "/app/services/recipe_registry/data/recipes"))
sys.path.insert(0, RUNTIME_DIR)
from services.ocr.algorithms.table_grid import TABLE_RE, parse_table as parse_html_table
from services.recipe_registry.matcher import match_table, signature_tokens, signature_score
from services.recipe_registry.package import RecipeManifest
import builtin

REG = RECIPE_DIR
reg = json.loads((REG / "registry.json").read_text(encoding="utf-8"))["channels"]["stable"]
recipes = {}
for rid, ver in reg.items():
    m = json.loads((REG / rid / ver / "manifest.json").read_text(encoding="utf-8"))
    recipes[rid] = (m, RecipeManifest.model_validate(m))
rl = [v[1] for v in recipes.values()]

folder = Path("/data/标准拆分提取-20261117-094032/84")
md = next(folder.glob("*.md")).read_text(encoding="utf-8", errors="ignore")
tables = TABLE_RE.findall(md)
for idx in range(0, 3):
    t = parse_html_table(tables[idx], f"T{idx+1}", page_no=idx + 1)
    print("\n== T%d profile=%s rows=%d cols=%d ==" % (idx + 1, t.profile, t.n_rows, t.n_cols))
    print("header_paths:", json.dumps(t.header_paths, ensure_ascii=False)[:500])
    print("rows:", json.dumps(t.rows[:3], ensure_ascii=False)[:500])
    m = match_table(t, rl)
    print("match:", m.recipe_id, m.version, round(m.score, 3), m.status)
    for manifest in rl:
        score = signature_score(t, manifest.signature)
        if score > 0.05:
            print("   score %-32s %.3f tokens=%s" % (manifest.recipe_id, score, manifest.signature.tokens[:10]))
    if m.recipe_id:
        man = recipes[m.recipe_id][0]
        print("bindings.measures:", list((man.get("bindings") or {}).get("measures") or {})[:20])
        diags = []
        recs, _, summary = builtin.parse_table(t.model_dump(mode="json"), man, {"table_id": f"T{idx+1}", "recipe_id": m.recipe_id, "version": m.version}, diags)
        print("parsed records=%d" % len(recs))
        for r in recs[:3]:
            print("   grade=%s cond=%s props=%s" % (r.get("grade"), r.get("condition_key"), list((r.get("properties") or {}))))
        print("diags:", [d.get("code") for d in diags][:10])
