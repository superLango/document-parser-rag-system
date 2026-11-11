import asyncio
from pathlib import Path

from services.shared.storage import LocalObjectStore, StorageConfig


def _store(tmp_path: Path) -> LocalObjectStore:
    return LocalObjectStore(
        StorageConfig(
            endpoint="",
            bucket="test",
            access_key="",
            secret_key="",
            local_dir=tmp_path,
        )
    )


def test_local_store_roundtrip(tmp_path) -> None:
    store = _store(tmp_path)

    async def run() -> bytes:
        await store.ensure_ready()
        await store.put_bytes("runs/r1/result.json", b'{"ok": true}', "application/json")
        return await store.get_bytes("runs/r1/result.json")

    assert asyncio.run(run()) == b'{"ok": true}'


def test_local_store_rejects_path_traversal(tmp_path) -> None:
    store = _store(tmp_path)

    async def run() -> None:
        await store.ensure_ready()
        await store.put_bytes("../escape.txt", b"bad")

    try:
        asyncio.run(run())
    except ValueError:
        return
    raise AssertionError("path traversal should be rejected")
