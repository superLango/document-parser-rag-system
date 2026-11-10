"""Load pilot run artifacts shared by M1.6/M1.7 tools."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from metal_doc_agent.contracts import (  # noqa: E402
    ColumnBindingResult,
    CrossStandardTask,
    DocumentMeta,
    Page,
    Record,
    TableGrid,
)
from metal_doc_agent.recipes import (  # noqa: E402
    bind_columns,
    load_aliases,
    load_recipes,
    match_recipe,
)


@dataclass
class RunData:
    run_dir: Path
    document: DocumentMeta
    doc_type: str | None
    pages: list[Page]
    tables: list[TableGrid]
    bindings: dict[str, ColumnBindingResult]
    cross_tasks: list[CrossStandardTask]
    records: list[Record]


def load_run(run_dir: Path) -> RunData:
    if not (run_dir / "tablegrid").exists():
        raise FileNotFoundError(f"no tablegrid under {run_dir}")
    pages = [
        Page.model_validate(item)
        for item in json.loads((run_dir / "pages.json").read_text(encoding="utf-8"))
    ]
    tables = [
        TableGrid.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted((run_dir / "tablegrid").glob("T*.json"))
    ]
    recipes = load_recipes(ROOT / "configs" / "recipes")
    aliases = load_aliases(ROOT / "configs" / "column_aliases.json")
    bindings: dict[str, ColumnBindingResult] = {}
    for table in tables:
        match = match_recipe(table, recipes)
        bindings[table.table_id] = bind_columns(
            table,
            recipe=match.recipe,
            aliases=aliases,
            match_status=match.status,
        )
    cross_tasks: list[CrossStandardTask] = []
    task_path = run_dir / "cross_standard_tasks.json"
    if task_path.exists():
        cross_tasks = [
            CrossStandardTask.model_validate(item)
            for item in json.loads(task_path.read_text(encoding="utf-8"))
        ]
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    document = DocumentMeta.model_validate(result.get("document", {}))
    records = [
        Record.model_validate(item) for item in result.get("records", [])
    ]
    return RunData(
        run_dir=run_dir,
        document=document,
        doc_type=result.get("document", {}).get("doc_type"),
        pages=pages,
        tables=tables,
        bindings=bindings,
        cross_tasks=cross_tasks,
        records=records,
    )
