import json
import os
import sys
from pathlib import Path

RUNTIME_DIR = os.environ.get("REPLAY_RUNTIME_DIR", "/app/services/sandbox/runtime")
RECIPE_DIR = Path(os.environ.get("REPLAY_RECIPE_DIR", "/app/services/recipe_registry/data/recipes"))
sys.path.insert(0, RUNTIME_DIR)
from services.ocr.algorithms.table_grid import TABLE_RE, parse_table as parse_html_table
from services.recipe_registry.matcher import match_table
from services.recipe_registry.package import RecipeManifest
import builtin

reg = json.loads((RECIPE_DIR / "registry.json").read_text(encoding="utf-8"))["channels"]["stable"]
recipes = {
    rid: (json.loads((RECIPE_DIR / rid / ver / "manifest.json").read_text(encoding="utf-8")),
          RecipeManifest.model_validate(json.loads((RECIPE_DIR / rid / ver / "manifest.json").read_text(encoding="utf-8"))))
    for rid, ver in reg.items()
}
rl = [v[1] for v in recipes.values()]

docs = Path("/data/标准拆分提取-20261117-094032")
folder = docs / sys.argv[1]
indexes = [int(x) for x in sys.argv[2:]] if len(sys.argv) > 2 else [1]
md = next(folder.glob("*.md")).read_text(encoding="utf-8", errors="ignore")
tables = TABLE_RE.findall(md)
for idx in indexes:
    html = tables[idx - 1]
    t = parse_html_table(html, f"T{idx}", page_no=idx)
    print("\n== T%d profile=%s rows=%d cols=%d ==" % (idx, t.profile, t.n_rows, t.n_cols))
    print("header_paths:", json.dumps(t.header_paths, ensure_ascii=False)[:400])
    for r in t.rows[:5]:
        print("  row:", json.dumps(r, ensure_ascii=False)[:240])
    m = match_table(t, rl)
    print("match:", m.recipe_id, m.version, round(m.score, 3), m.status)
    if m.recipe_id:
        man = recipes[m.recipe_id][0]
        diags = []
        recs, _, summary = builtin.parse_table(
            t.model_dump(mode="json"), man,
            {"table_id": f"T{idx}", "recipe_id": m.recipe_id, "version": m.version}, diags)
        print("records=%d" % len(recs), "summary=", summary)
        for r in recs[:4]:
            print("   grade=%s cond=%s props=%s" % (r.get("grade"), r.get("condition_key"), list((r.get("properties") or {}))[:12]))
        print("diags:", [(d.get("code"), d.get("detail", {}).get("message", "")[:60]) for d in diags][:12])
