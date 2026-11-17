"""按 gold_standard_30/source_tables 回放单表并打印记录细节。"""

import html
import json
import os
import sys
from pathlib import Path

RUNTIME_DIR = os.environ.get("REPLAY_RUNTIME_DIR", "/app/services/sandbox/runtime")
RECIPE_DIR = Path(os.environ.get("REPLAY_RECIPE_DIR", "/app/services/recipe_registry/data/recipes"))
sys.path.insert(0, RUNTIME_DIR)
from services.ocr.algorithms.table_grid import parse_table as parse_html_table
from services.recipe_registry.matcher import match_table
from services.recipe_registry.package import RecipeManifest
import builtin


def load_recipes():
    registry = json.loads((RECIPE_DIR / "registry.json").read_text(encoding="utf-8"))
    pointers = registry["channels"]["stable"]
    out = []
    for recipe_id, version in pointers.items():
        manifest = json.loads(
            (RECIPE_DIR / recipe_id / version / "manifest.json").read_text(encoding="utf-8")
        )
        out.append((manifest, RecipeManifest.model_validate(manifest)))
    return out


def table_html(table):
    parts = ["<table><thead>"]
    for row in table.get("header_rows") or []:
        parts.append("<tr>" + "".join(f"<th>{html.escape(str(c))}</th>" for c in row) + "</tr>")
    parts.append("</thead><tbody>")
    for row in table.get("data_rows") or []:
        parts.append("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in row) + "</tr>")
    parts.append("</tbody></table>")
    return "".join(parts)


def main():
    doc_id = sys.argv[1]
    wanted = set(sys.argv[2:])
    root = Path(os.environ.get("GOLD_DIR", "/data/gold_standard_30"))
    source = json.loads((root / "source_tables" / f"{doc_id}.json").read_text(encoding="utf-8"))
    recipes = load_recipes()
    recipe_list = [item[1] for item in recipes]
    by_id = {item[0]["recipe_id"]: item[0] for item in recipes}
    builtin._table_fingerprints.clear()
    builtin._DOCUMENT_TEXT_CACHE = str(source.get("title") or "")
    for table in source.get("tables") or []:
        table_id = table.get("table_id")
        if wanted and table_id not in wanted:
            continue
        grid = parse_html_table(
            table_html(table),
            table_id,
            page_no=int(table.get("page_no") or 0),
            caption=str(table.get("caption") or ""),
            context=str(source.get("title") or ""),
        )
        print(f"\n== {table_id} rows={grid.n_rows} cols={grid.n_cols} profile={grid.profile}")
        payload = grid.model_dump(mode="json")
        print("header_paths:", json.dumps(payload.get("header_paths"), ensure_ascii=False))
        print("headers:", json.dumps(builtin._flatten_headers(payload), ensure_ascii=False))
        print("layout_headers:", json.dumps(builtin._table_layout(payload)[0], ensure_ascii=False))
        match = match_table(grid, recipe_list)
        print("match:", match.recipe_id, match.version, round(match.score, 3), match.status)
        if not match.recipe_id:
            continue
        manifest = by_id[match.recipe_id]
        bindings = manifest.get("bindings") or {}
        headers = builtin._table_layout(payload)[0]
        print("bindings:", json.dumps(bindings.get("measures"), ensure_ascii=False)[:400])
        bound = {builtin._canonical_measure(str(name)) for name in (bindings.get("measures") or {})}
        if len(headers) > 3:
            print(
                "probe:",
                json.dumps(
                    {
                        "h2": headers[2],
                        "printed": builtin._printed_measure(builtin.normalize(headers[2])),
                        "parts": builtin._header_parts(headers[2]),
                        "group": builtin._group_label(headers[2]),
                        "alias": builtin._alias_matches(
                            builtin.normalize(headers[2]), "cev"
                        ),
                        "find_single": builtin._find_column(
                            [headers[2]], ["CEV"], set(), skip_group=True,
                            measure="CEV", bound_measures={"CEV"},
                        ),
                    },
                    ensure_ascii=False,
                ),
            )
        for name in bindings.get("measures") or {}:
            col = builtin._find_column(
                headers, [str(name)], set(), skip_group=True,
                measure=str(name), bound_measures=bound,
            )
            print("  measure", name, "->", col)
        diags = []
        records, _, summary = builtin.parse_table(
            grid.model_dump(mode="json"),
            by_id[match.recipe_id],
            {"table_id": table_id, "recipe_id": match.recipe_id, "version": match.version},
            diags,
        )
        print("summary:", json.dumps(summary, ensure_ascii=False), "records:", len(records))
        for record in records[:400]:
            props = {
                key: (val or {}).get("raw")
                for key, val in (record.get("properties") or {}).items()
            }
            print(
                "  grade=%s cond=%s props=%s"
                % (record.get("grade"), record.get("condition_key"), json.dumps(props, ensure_ascii=False)[:400])
            )
        for diag in diags:
            if diag.get("severity") != "info":
                print("  diag:", diag.get("code"), json.dumps(diag.get("detail"), ensure_ascii=False)[:240])


if __name__ == "__main__":
    main()
