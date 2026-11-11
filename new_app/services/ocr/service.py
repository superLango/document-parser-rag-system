import hashlib
import json
import logging

from services.shared.storage import ObjectStore

from .adapters.base import OcrBackendError
from .adapters.factory import build_adapter
from .adapters.layout import LayoutClient
from .algorithms.repairs import apply_repairs, load_rules
from .algorithms.table_grid import extract_tables
from .config import settings
from .contracts import ArtifactRef, DocumentMeta, OcrRequest, OcrResult

logger = logging.getLogger(__name__)

_store: ObjectStore | None = None


def set_store(store: ObjectStore) -> None:
    global _store
    _store = store


def get_store() -> ObjectStore:
    if _store is None:
        raise RuntimeError("object store is not initialized")
    return _store


async def parse_document(
    data: bytes,
    request: OcrRequest,
    store: ObjectStore,
) -> OcrResult:
    adapter = build_adapter(request.backend, request.filename)
    output = await adapter.parse(data, request)
    result = output.result

    await _run_layout(result, output.assets)
    result.artifacts.extend(await _persist_assets(store, output.assets))

    tables = extract_tables(result.pages)
    tables, applied = apply_repairs(
        tables,
        document=DocumentMeta(file_name=request.filename),
        rules=load_rules(settings.table_repairs_path or None),
    )
    result.tables = tables
    if applied:
        logger.info(
            "applied table repairs document=%s rules=%s",
            request.document_id,
            ",".join(applied),
        )
    for table in tables:
        logger.info(
            "table document=%s table_id=%s page_no=%s profile=%s rows=%s cols=%s",
            request.document_id,
            table.table_id,
            table.page_no,
            table.profile,
            table.n_rows,
            table.n_cols,
        )

    result.quality, result.warnings = assess_quality(result)
    result.artifacts.extend(await _persist_result(store, request.document_id, result))
    return result


async def _run_layout(result: OcrResult, assets: dict[str, bytes]) -> None:
    """Attach PP-DocLayoutV3 blocks; failures degrade to warnings."""
    if not settings.layout_base_url:
        return
    client = LayoutClient(settings.layout_base_url, settings.layout_timeout_seconds)
    for page in result.pages:
        image = assets.get(page.image_key or "")
        if image is None:
            continue
        try:
            blocks, failures, raw = await client.analyze(
                page_no=page.page_no,
                width=page.width,
                height=page.height,
                dpi=page.dpi,
                image=image,
            )
        except OcrBackendError as exc:
            result.warnings.append(f"layout page {page.page_no}: {exc.code}")
            logger.warning(
                "layout failed document=%s page=%s code=%s",
                result.document_id,
                page.page_no,
                exc.code,
            )
            continue
        if failures:
            result.warnings.append(
                f"layout page {page.page_no}: {len(failures)} block failures"
            )
        result.layout.extend(blocks)
        key = f"ocr/{result.document_id}/layout/{page.page_no}.json"
        page.layout_key = key
        assets[key] = json.dumps(raw, ensure_ascii=False, indent=2).encode("utf-8")
        logger.info(
            "layout document=%s page=%s blocks=%s",
            result.document_id,
            page.page_no,
            len(blocks),
        )


async def _persist_assets(
    store: ObjectStore, assets: dict[str, bytes]
) -> list[ArtifactRef]:
    refs: list[ArtifactRef] = []
    for key, payload in assets.items():
        content_type = _content_type(key)
        await store.put_bytes(key, payload, content_type)
        refs.append(_artifact_ref(key, payload, content_type))
    return refs


def _content_type(key: str) -> str:
    if key.endswith(".png"):
        return "image/png"
    if key.endswith(".json"):
        return "application/json"
    return "application/octet-stream"


async def _persist_result(
    store: ObjectStore, document_id: str, result: OcrResult
) -> list[ArtifactRef]:
    payloads = (
        ("markdown.md", result.markdown.encode("utf-8"), "text/markdown"),
        (
            "pages.json",
            _dump([page.model_dump() for page in result.pages]),
            "application/json",
        ),
        (
            "tables.json",
            _dump([table.model_dump() for table in result.tables]),
            "application/json",
        ),
        (
            "layout.json",
            _dump([block.model_dump() for block in result.layout]),
            "application/json",
        ),
    )
    refs: list[ArtifactRef] = []
    for name, payload, content_type in payloads:
        key = f"ocr/{document_id}/{name}"
        await store.put_bytes(key, payload, content_type)
        refs.append(_artifact_ref(key, payload, content_type))

    key = f"ocr/{document_id}/ocr.json"
    summary = result.model_dump()
    payload = _dump(summary)
    await store.put_bytes(key, payload, "application/json")
    refs.append(_artifact_ref(key, payload, "application/json"))
    return refs


def _artifact_ref(key: str, payload: bytes, content_type: str) -> ArtifactRef:
    return ArtifactRef(
        key=key,
        sha256=hashlib.sha256(payload).hexdigest(),
        bytes=len(payload),
        content_type=content_type,
    )


def _dump(payload) -> bytes:
    return json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")


def assess_quality(result: OcrResult) -> tuple[float, list[str]]:
    if not result.pages:
        return 0.0, ["no pages"]
    empty_pages = [page.page_no for page in result.pages if len(page.markdown.strip()) < 20]
    warnings = [f"page {page_no} has little text" for page_no in empty_pages]
    if result.backend != "mock" and not result.tables:
        warnings.append("no tables detected")
    score = 1.0 - len(empty_pages) / len(result.pages)
    return round(max(0.0, min(1.0, score)), 3), warnings
