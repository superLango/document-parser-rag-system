import asyncio

from services.orchestration.storage import LocalObjectStore


def test_local_store_roundtrip(tmp_path) -> None:
    store = LocalObjectStore(tmp_path)

    async def run() -> bytes:
        await store.ensure_ready()
        await store.put_bytes("runs/r1/result.json", b'{"ok": true}', "application/json")
        return await store.get_bytes("runs/r1/result.json")

    assert asyncio.run(run()) == b'{"ok": true}'


def test_local_store_rejects_path_traversal(tmp_path) -> None:
    store = LocalObjectStore(tmp_path)

    async def run() -> None:
        await store.ensure_ready()
        await store.put_bytes("../escape.txt", b"bad")

    try:
        asyncio.run(run())
    except ValueError:
        return
    raise AssertionError("path traversal should be rejected")
