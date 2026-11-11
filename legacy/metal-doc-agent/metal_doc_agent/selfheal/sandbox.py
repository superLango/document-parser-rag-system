"""Sandbox project roots for overlay (L2) and document-level (L1) repairs.

A sandbox is a throwaway copy of ``configs/`` plus the standards library. The
pipeline runs against it with ``METAL_DOC_HOME`` pointed at the copy, so the
production configuration is never written.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import SelfHealSettings

Mutator = Callable[[Path], None]


@dataclass
class OverlayProject:
    root: Path
    configs: Path

    @property
    def table_repairs(self) -> Path:
        return self.configs / "table_repairs.json"

    @property
    def column_aliases(self) -> Path:
        return self.configs / "column_aliases.json"


def create_overlay_project(
    settings: SelfHealSettings,
    overlay_dir: str | Path,
    mutators: dict[str, Mutator] | None = None,
) -> OverlayProject:
    root = Path(overlay_dir)
    configs = root / "project" / "configs"
    if configs.exists():
        shutil.rmtree(configs)
    configs.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(settings.project_root / "configs", configs)
    library_src = settings.project_root / "data" / "standards_library"
    library_dst = root / "project" / "data" / "standards_library"
    if library_src.exists() and not library_dst.exists():
        library_dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(library_src, library_dst)
    for relative, mutate in (mutators or {}).items():
        target = configs / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_text("{}\n", encoding="utf-8")
        mutate(target)
    return OverlayProject(root=root / "project", configs=configs)


def update_json(path: Path, updater: Callable[[dict], None]) -> None:
    payload = {}
    if path.exists() and path.stat().st_size:
        payload = json.loads(path.read_text(encoding="utf-8"))
    updater(payload)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def append_alias(alias: str, canonical: str) -> Mutator:
    def mutate(path: Path) -> None:
        def updater(payload: dict) -> None:
            aliases = payload.setdefault("property_aliases", {})
            values = aliases.setdefault(canonical, [])
            if alias not in values:
                values.append(alias)

        update_json(path, updater)

    return mutate


def append_table_repair(document_key: str, table_id: str, spec: dict) -> Mutator:
    def mutate(path: Path) -> None:
        def updater(payload: dict) -> None:
            documents = payload.setdefault("documents", {})
            tables = documents.setdefault(document_key, {})
            tables[table_id] = spec

        update_json(path, updater)

    return mutate
