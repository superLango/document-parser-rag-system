"""将旧知识库数据合并到“标准拆分”模块，并支持回滚。

用法（在 apps/api 目录或容器内执行）::

    python -m hanson_api.migrate_modules --dry-run
    python -m hanson_api.migrate_modules --apply
    python -m hanson_api.migrate_modules --rollback

迁移动作：
1. 每个工作空间复用最早的知识库作为标准拆分模块（没有则新建）；
2. 其余知识库的文档改挂到模块，旧知识库软删除归档；
3. 所有知识库词典的别名取并集写入模块词典；
4. 迁移记录与词典备份写入平台数据目录，供 ``--rollback`` 使用。
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select

from .config import PlatformSettings
from .db import (
    build_engine,
    build_session_factory,
    init_db,
    verify_migrations,
)
from .models import Document, KnowledgeBase, Workspace
from .modules import MODULES, module_key_of

STANDARD_KEY = "standard_split"
RECORD_NAME = "module_migration.json"
BACKUP_NAME = "module_migration_backup"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _workspace_kbs(db, workspace_id: str) -> list[KnowledgeBase]:
    return list(
        db.execute(
            select(KnowledgeBase)
            .where(
                KnowledgeBase.workspace_id == workspace_id,
                KnowledgeBase.deleted_at.is_(None),
            )
            .order_by(KnowledgeBase.created_at.asc())
        )
        .scalars()
        .all()
    )


def _dictionary_dir(settings: PlatformSettings) -> Path:
    return Path(settings.engine_data_dir) / "dictionaries"


def _merge_dictionary(module_path: Path, source_path: Path, version: str) -> int:
    """把 source 的别名并入 module，返回新增/更新的词条数。"""

    if not source_path.exists():
        return 0
    module_raw = json.loads(module_path.read_text(encoding="utf-8"))
    source_raw = json.loads(source_path.read_text(encoding="utf-8"))
    index = {
        (entry.get("type"), entry.get("business_code")): entry
        for entry in module_raw.get("entries") or []
    }
    changed = 0
    for entry in source_raw.get("entries") or []:
        key = (entry.get("type"), entry.get("business_code"))
        if not key[1]:
            continue
        target = index.get(key)
        if target is None:
            copied = dict(entry)
            copied["aliases"] = sorted(
                {*(copied.get("aliases") or [])}, key=len, reverse=True
            )
            module_raw.setdefault("entries", []).append(copied)
            index[key] = copied
            changed += 1
            continue
        before = set(target.get("aliases") or [])
        merged = before | set(entry.get("aliases") or [])
        if merged != before:
            target["aliases"] = sorted(merged, key=len, reverse=True)
            changed += 1
    if changed:
        module_raw["version"] = version
        module_path.write_text(
            json.dumps(module_raw, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return changed


def _ensure_module_dictionary(settings: PlatformSettings, module_kb_id: str) -> Path:
    path = _dictionary_dir(settings) / f"{module_kb_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        base = Path(settings.engine_root) / "configs" / "business_dictionary.hanson.json"
        if base.exists():
            shutil.copyfile(base, path)
        else:
            path.write_text(
                json.dumps(
                    {"version": "module-v1", "source": "module", "entries": []},
                    ensure_ascii=False,
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
    return path


def migrate(settings: PlatformSettings, *, apply: bool) -> int:
    engine = build_engine(settings)
    if settings.db_auto_create:
        init_db(engine)
    else:
        verify_migrations(engine)
    session_factory = build_session_factory(engine)
    stamp = _stamp()
    spec = MODULES[STANDARD_KEY]
    backup_dir = Path(settings.data_dir) / BACKUP_NAME / stamp
    record: dict = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "module": STANDARD_KEY,
        "workspaces": [],
        "kbs": [],
        "backup_dir": str(backup_dir),
    }

    try:
        with session_factory() as db:
            workspaces = list(db.execute(select(Workspace).where(Workspace.deleted_at.is_(None))).scalars())
            for workspace in workspaces:
                kbs = _workspace_kbs(db, workspace.id)
                module_kb = next(
                    (kb for kb in kbs if module_key_of(kb) == STANDARD_KEY), None
                )
                created = False
                if module_kb is None:
                    reusable = next(
                        (kb for kb in kbs if module_key_of(kb) is None), None
                    )
                    if reusable is not None:
                        module_kb = reusable
                        record["workspaces"].append(
                            {
                                "workspace_id": workspace.id,
                                "module_kb_id": module_kb.id,
                                "created": False,
                                "original": {
                                    "name": module_kb.name,
                                    "description": module_kb.description,
                                    "config": module_kb.config or {},
                                },
                            }
                        )
                        module_kb.name = spec.name
                        module_kb.description = spec.summary
                        module_kb.config = {
                            "module": STANDARD_KEY,
                            "builtin": True,
                        }
                    else:
                        module_kb = KnowledgeBase(
                            workspace_id=workspace.id,
                            name=spec.name,
                            description=spec.summary,
                            owner_id=workspace.owner_id,
                            config={"module": STANDARD_KEY, "builtin": True},
                        )
                        db.add(module_kb)
                        db.flush()
                        created = True
                        record["workspaces"].append(
                            {
                                "workspace_id": workspace.id,
                                "module_kb_id": module_kb.id,
                                "created": True,
                                "original": None,
                            }
                        )

                module_dict = (
                    _ensure_module_dictionary(settings, module_kb.id)
                    if apply
                    else None
                )
                version = f"{spec.key}-{stamp}"
                for kb in kbs:
                    if kb.id == module_kb.id or module_key_of(kb) == STANDARD_KEY:
                        continue
                    documents = list(
                        db.execute(
                            select(Document).where(Document.kb_id == kb.id)
                        )
                        .scalars()
                        .all()
                    )
                    for document in documents:
                        document.kb_id = module_kb.id
                    if apply and module_dict is not None:
                        _merge_dictionary(
                            module_dict,
                            _dictionary_dir(settings) / f"{kb.id}.json",
                            version,
                        )
                    kb.deleted_at = _now()
                    record["kbs"].append(
                        {
                            "old_kb_id": kb.id,
                            "workspace_id": workspace.id,
                            "module_kb_id": module_kb.id,
                            "document_ids": [doc.id for doc in documents],
                            "was_archived": False,
                        }
                    )
                    print(
                        f"[{'apply' if apply else 'dry-run'}] {workspace.id}: "
                        f"{kb.id} -> {module_kb.id} ({len(documents)} documents)"
                    )

            if apply:
                backup_dir.mkdir(parents=True, exist_ok=True)
                source_dir = _dictionary_dir(settings)
                if source_dir.exists():
                    shutil.copytree(
                        source_dir,
                        backup_dir / "dictionaries",
                        dirs_exist_ok=True,
                    )
                (Path(settings.data_dir) / RECORD_NAME).write_text(
                    json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                db.commit()
                print(f"migration record: {Path(settings.data_dir) / RECORD_NAME}")
            else:
                db.rollback()
                print("dry-run: database rolled back; no files written")
    finally:
        engine.dispose()
    return 0


def rollback(settings: PlatformSettings, record_path: Path) -> int:
    if not record_path.exists():
        raise SystemExit(f"migration record not found: {record_path}")
    record = json.loads(record_path.read_text(encoding="utf-8"))
    engine = build_engine(settings)
    if settings.db_auto_create:
        init_db(engine)
    else:
        verify_migrations(engine)
    session_factory = build_session_factory(engine)
    try:
        with session_factory() as db:
            for item in record.get("kbs", []):
                old_kb = db.get(KnowledgeBase, item["old_kb_id"])
                ids = item.get("document_ids") or []
                if ids:
                    documents = list(
                        db.execute(
                            select(Document).where(Document.id.in_(ids))
                        )
                        .scalars()
                        .all()
                    )
                    for document in documents:
                        if document.kb_id == item["module_kb_id"]:
                            document.kb_id = item["old_kb_id"]
                if old_kb is not None:
                    old_kb.deleted_at = None
            for item in record.get("workspaces", []):
                module_kb = db.get(KnowledgeBase, item["module_kb_id"])
                if module_kb is None:
                    continue
                if item.get("created"):
                    remaining = db.scalar(
                        select(func.count(Document.id)).where(
                            Document.kb_id == module_kb.id,
                            Document.deleted_at.is_(None),
                        )
                    )
                    if not remaining:
                        module_kb.deleted_at = _now()
                else:
                    original = item.get("original") or {}
                    module_kb.name = original.get("name", module_kb.name)
                    module_kb.description = original.get("description", "")
                    module_kb.config = original.get("config") or {}
            db.commit()
    finally:
        engine.dispose()

    backup_dir = Path(record.get("backup_dir", ""))
    source_dir = backup_dir / "dictionaries"
    target_dir = _dictionary_dir(settings)
    if source_dir.exists():
        target_dir.mkdir(parents=True, exist_ok=True)
        for path in source_dir.glob("*.json"):
            shutil.copyfile(path, target_dir / path.name)
        print(f"dictionaries restored from {source_dir}")
    print(f"rollback complete: {record_path}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Merge knowledge bases into modules")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run", action="store_true")
    group.add_argument("--apply", action="store_true")
    group.add_argument("--rollback", action="store_true")
    parser.add_argument(
        "--record",
        type=Path,
        default=None,
        help="migration record path (default: <data_dir>/module_migration.json)",
    )
    args = parser.parse_args(argv)
    settings = PlatformSettings.from_env()
    if args.rollback:
        record = args.record or Path(settings.data_dir) / RECORD_NAME
        return rollback(settings, record)
    return migrate(settings, apply=bool(args.apply))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
