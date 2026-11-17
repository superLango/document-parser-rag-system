import json
from pathlib import Path

REG = Path("/app/services/recipe_registry/data/recipes")
reg = json.loads((REG / "registry.json").read_text(encoding="utf-8"))["channels"]["stable"]
for rid in ("mechanical_properties_v1", "hardness_v1", "chemical_composition_v1", "dimension_v1", "heat_treatment_v1"):
    ver = reg[rid]
    m = json.loads((REG / rid / ver / "manifest.json").read_text(encoding="utf-8"))
    print("\n==", rid, ver, "profile=", m.get("profile"))
    print("signature tokens:", m["signature"].get("tokens")[:20])
    print("bindings keys:", list(m.get("bindings") or {}))
    measures = (m.get("bindings") or {}).get("measures") or {}
    print("measures:", json.dumps(measures, ensure_ascii=False)[:1200])
    print("key bindings:", json.dumps({k: v for k, v in (m.get("bindings") or {}).items() if k != "measures"}, ensure_ascii=False)[:600])
    print("rules:", json.dumps(m.get("rules") or {}, ensure_ascii=False)[:400])
