"""Optional FastAPI surface with persisted jobs and artifact retrieval.

Install ``.[api]`` to expose it. The API is intentionally a thin layer over
:class:`metal_doc_agent.jobs.JobStore` and :func:`metal_doc_agent.runner.run_job`,
so the same job can also be executed by ``apps/worker``.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from .artifacts import MANIFEST_NAME, read_artifact_manifest, verify_artifacts
from .batches import BatchStore
from .canonicalize import JsonDictionaryAdapter
from .contracts import JobState
from .coverage.plan import load_templates
from .jobs import LANES, JobStore
from .observability import engine_metrics, readiness
from .runner import resume_job, run_job
from .settings import Settings

try:  # pydantic is a hard dependency; the import stays explicit for typing
    from pydantic import BaseModel
except ImportError:  # pragma: no cover - pydantic is required by contracts
    BaseModel = object  # type: ignore[assignment,misc]

try:
    from fastapi import BackgroundTasks, FastAPI, File, Form, Header, HTTPException, Query, Response, UploadFile
    from fastapi.responses import PlainTextResponse

    FASTAPI_AVAILABLE = True
except ImportError:  # pragma: no cover - optional dependency
    FASTAPI_AVAILABLE = False


MAX_UPLOAD_BYTES = 50 * 1024 * 1024
ALLOWED_SUFFIXES = {".md", ".pdf"}
OCR_BACKENDS = {"mock", "glm"}
EXTRACTOR_BACKENDS = {"mock", "qwen"}


class BatchItemRequest(BaseModel):
    path: str | None = None
    job_id: str | None = None
    template: str = "product_full"
    ocr: str = "mock"
    extractor: str = "mock"
    lane: str = "production"


class BatchCreateRequest(BaseModel):
    items: list[BatchItemRequest]
    idempotency_key: str | None = None


def _job_or_404(store: JobStore, job_id: str) -> JobState:
    state = store.get(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="job not found")
    return state


def _artifact_path(state: JobState, relative: str) -> Path:
    root = Path(state.out_dir).resolve()
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid artifact path") from exc
    return path


def _require_artifact(state: JobState, relative: str) -> Path:
    path = _artifact_path(state, relative)
    if not path.exists():
        raise HTTPException(
            status_code=409,
            detail={"error": "artifact not ready", "stage": state.stage, "path": relative},
        )
    return path


def create_app(settings: Settings | None = None) -> Any:
    if not FASTAPI_AVAILABLE:
        raise RuntimeError("FastAPI is not installed. Run: pip install -e \".[api]\"")

    settings = settings or Settings.from_env()
    store = JobStore(settings.data_dir / "jobs")
    batches = BatchStore(settings.data_dir / "batches")
    upload_dir = settings.data_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    templates = load_templates(settings)
    dictionary = _load_dictionary(settings)

    app = FastAPI(title="Metal Document Agent", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": "0.1.0",
            "ocr_backend": settings.ocr_backend,
            "extractor_backend": settings.extractor_backend,
            "business_dictionary": dictionary.version if dictionary else None,
        }

    @app.get("/ready")
    def ready(response: Response) -> dict[str, Any]:
        payload = readiness(settings.project_root, settings.data_dir)
        if payload["status"] != "ok":
            response.status_code = 503
        return payload

    @app.get("/metrics")
    def metrics() -> Any:
        return PlainTextResponse(
            engine_metrics(
                store,
                settings.data_dir / "queues",
                feedback_path=settings.data_dir / "feedback" / "feedback.jsonl",
            ),
            media_type="text/plain; version=0.0.4",
        )

    @app.post("/v1/jobs", status_code=201)
    async def create_job(
        response: Response,
        background: BackgroundTasks,
        file: UploadFile = File(...),
        template: str = Form("product_full"),
        ocr: str = Form("mock"),
        extractor: str = Form("mock"),
        lane: str = Form("production"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        if template not in templates:
            raise HTTPException(status_code=422, detail=f"unknown template: {template}")
        if ocr not in OCR_BACKENDS:
            raise HTTPException(status_code=422, detail=f"unknown ocr backend: {ocr}")
        if extractor not in EXTRACTOR_BACKENDS:
            raise HTTPException(status_code=422, detail=f"unknown extractor: {extractor}")
        if lane not in LANES:
            raise HTTPException(status_code=422, detail=f"unknown lane: {lane}")
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in ALLOWED_SUFFIXES:
            raise HTTPException(status_code=415, detail=f"unsupported file type: {suffix or 'none'}")
        data = await file.read()
        if not data:
            raise HTTPException(status_code=422, detail="empty upload")
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="upload exceeds 50 MB")

        source_sha = hashlib.sha256(data).hexdigest()
        options = {"ocr": ocr, "extractor": extractor, "template": template}
        key = idempotency_key or f"{source_sha}|{ocr}|{extractor}|{template}|{lane}"
        existing = store.find(key)
        if existing is not None:
            response.status_code = 200
            response.headers["X-Idempotent-Replay"] = "true"
            return existing.model_dump(mode="json")

        job_id = uuid.uuid4().hex[:12]
        source_name = Path(file.filename or f"upload{suffix}").name or f"upload{suffix}"
        doc_path = upload_dir / f"{job_id}-{source_name}"
        doc_path.write_bytes(data)
        state, created = store.reserve(
            job_id=job_id,
            idempotency_key=key,
            source_name=file.filename or doc_path.name,
            source_sha256=source_sha,
            doc_path=str(doc_path),
            options=options,
            lane=lane,
        )
        if not created:
            doc_path.unlink(missing_ok=True)
            response.status_code = 200
            response.headers["X-Idempotent-Replay"] = "true"
            return state.model_dump(mode="json")

        background.add_task(run_job, store, state.job_id, settings)
        return state.model_dump(mode="json")

    @app.get("/v1/jobs")
    def list_jobs(
        limit: int = Query(50, ge=1, le=200),
        lane: str | None = Query(default=None),
    ) -> list[dict[str, Any]]:
        if lane is not None and lane not in LANES:
            raise HTTPException(status_code=422, detail=f"unknown lane: {lane}")
        return [
            state.model_dump(mode="json")
            for state in store.list(limit=limit, lane=lane)
        ]

    @app.get("/v1/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        return _job_or_404(store, job_id).model_dump(mode="json")

    @app.get("/v1/jobs/{job_id}/result")
    def get_result(job_id: str) -> Any:
        state = _job_or_404(store, job_id)
        path = _require_artifact(state, "result.json")
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/v1/jobs/{job_id}/evidence")
    def get_evidence(job_id: str, limit: int = Query(1000, ge=1, le=10000)) -> Any:
        state = _job_or_404(store, job_id)
        path = _require_artifact(state, "evidence.jsonl")
        rows: list[Any] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
            if len(rows) >= limit:
                break
        return rows

    @app.get("/v1/jobs/{job_id}/audit")
    def get_audit(job_id: str) -> Any:
        state = _job_or_404(store, job_id)
        path = _require_artifact(state, "audit.md")
        return PlainTextResponse(path.read_text(encoding="utf-8"))

    @app.get("/v1/jobs/{job_id}/items")
    def get_items(job_id: str) -> Any:
        state = _job_or_404(store, job_id)
        path = _artifact_path(state, "item_inventory_aligned.json")
        if not path.exists():
            path = _require_artifact(state, "item_inventory.json")
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/v1/jobs/{job_id}/records")
    def get_records(
        job_id: str, limit: int = Query(2000, ge=1, le=20000)
    ) -> Any:
        state = _job_or_404(store, job_id)
        path = _require_artifact(state, "result.json")
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload.get("records", [])[:limit]

    @app.get("/v1/jobs/{job_id}/alignment")
    def get_alignment(job_id: str) -> Any:
        state = _job_or_404(store, job_id)
        path = _require_artifact(state, "alignment.json")
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/v1/jobs/{job_id}/new-terms")
    def get_new_terms(job_id: str) -> Any:
        state = _job_or_404(store, job_id)
        path = _require_artifact(state, "new_terms.json")
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/v1/jobs/{job_id}/clauses")
    def get_clauses(
        job_id: str, limit: int = Query(2000, ge=1, le=20000)
    ) -> Any:
        state = _job_or_404(store, job_id)
        path = _require_artifact(state, "clauses.jsonl")
        rows: list[Any] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
            if len(rows) >= limit:
                break
        return rows

    @app.get("/v1/jobs/{job_id}/links")
    def get_links(job_id: str) -> Any:
        state = _job_or_404(store, job_id)
        path = _require_artifact(state, "links.json")
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/v1/jobs/{job_id}/coverage-audit")
    def get_coverage_audit(job_id: str) -> Any:
        state = _job_or_404(store, job_id)
        path = _require_artifact(state, "coverage_audit.json")
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/v1/jobs/{job_id}/trace")
    def get_trace(job_id: str) -> Any:
        state = _job_or_404(store, job_id)
        path = _require_artifact(state, "trace.json")
        return json.loads(path.read_text(encoding="utf-8"))

    @app.get("/v1/jobs/{job_id}/artifacts")
    def get_artifacts(job_id: str) -> Any:
        state = _job_or_404(store, job_id)
        if not _artifact_path(state, MANIFEST_NAME).exists():
            raise HTTPException(
                status_code=409,
                detail={"error": "artifact manifest not ready", "stage": state.stage},
            )
        return read_artifact_manifest(state.out_dir).model_dump(mode="json")

    @app.get("/v1/jobs/{job_id}/artifacts/verify")
    def verify_job_artifacts(job_id: str) -> Any:
        state = _job_or_404(store, job_id)
        if not _artifact_path(state, MANIFEST_NAME).exists():
            raise HTTPException(
                status_code=409,
                detail={"error": "artifact manifest not ready", "stage": state.stage},
            )
        result = verify_artifacts(state.out_dir)
        return {"ok": result.ok, "checked": result.checked, "issues": result.issues}

    @app.post("/v1/jobs/{job_id}/retry", status_code=202)
    def retry_job(job_id: str, background: BackgroundTasks) -> dict[str, Any]:
        state = _job_or_404(store, job_id)
        if state.status not in {"failed", "review"}:
            raise HTTPException(
                status_code=409,
                detail=f"job status {state.status} cannot be retried",
            )
        reset = store.reset_for_retry(job_id)
        background.add_task(run_job, store, job_id, settings)
        return reset.model_dump(mode="json")

    @app.post("/v1/jobs/{job_id}/resume", status_code=202)
    def resume_job_endpoint(job_id: str, background: BackgroundTasks) -> dict[str, Any]:
        state = _job_or_404(store, job_id)
        if state.status in {"running", "succeeded"}:
            raise HTTPException(
                status_code=409, detail=f"job status {state.status} cannot be resumed"
            )
        checkpoint = Path(state.out_dir) / "m3_state.json"
        resumable = settings.orchestrate and checkpoint.exists()
        if resumable:
            from .orchestration.state import OrchestrationState

            try:
                previous = OrchestrationState.load(checkpoint)
            except ValueError:
                previous = None
            resumable = previous is not None and previous.status != "failed"
        reset = store.reset_for_retry(job_id)
        if resumable:
            background.add_task(resume_job, store, job_id, settings)
        else:
            background.add_task(run_job, store, job_id, settings)
        return reset.model_dump(mode="json")

    @app.get("/v1/recipes")
    def list_recipes() -> list[dict[str, Any]]:
        return [
            {
                "name": name,
                "field_count": len(fields),
                "required_count": sum(1 for field in fields if field.get("required")),
            }
            for name, fields in sorted(templates.items())
        ]

    @app.post("/v1/batches", status_code=201)
    def create_batch(
        request: BatchCreateRequest,
        response: Response,
        background: BackgroundTasks,
    ) -> dict[str, Any]:
        if not request.items:
            raise HTTPException(status_code=422, detail="batch requires at least one item")
        if len(request.items) > 100:
            raise HTTPException(status_code=422, detail="batch exceeds 100 items")
        if request.idempotency_key:
            existing = batches.find(request.idempotency_key)
            if existing is not None:
                response.status_code = 200
                response.headers["X-Idempotent-Replay"] = "true"
                return batches.refresh(existing.batch_id, store).model_dump(mode="json")

        accepted: list[dict[str, Any]] = []
        for item in request.items:
            if item.ocr not in OCR_BACKENDS:
                raise HTTPException(status_code=422, detail=f"unknown ocr backend: {item.ocr}")
            if item.extractor not in EXTRACTOR_BACKENDS:
                raise HTTPException(
                    status_code=422, detail=f"unknown extractor backend: {item.extractor}"
                )
            if item.template not in templates:
                raise HTTPException(status_code=422, detail=f"unknown template: {item.template}")
            if item.lane not in LANES:
                raise HTTPException(status_code=422, detail=f"unknown lane: {item.lane}")
            if item.job_id:
                state = _job_or_404(store, item.job_id)
                accepted.append(
                    {
                        "job_id": state.job_id,
                        "source_name": state.source_name,
                        "path": state.doc_path,
                        "lane": item.lane,
                    }
                )
                if state.status == "queued":
                    background.add_task(run_job, store, state.job_id, settings)
                continue
            if not item.path:
                raise HTTPException(status_code=422, detail="batch item needs path or job_id")
            source = Path(item.path)
            if not source.exists() or not source.is_file():
                raise HTTPException(status_code=422, detail=f"file not found: {source}")
            if source.suffix.lower() not in ALLOWED_SUFFIXES:
                raise HTTPException(status_code=415, detail=f"unsupported file type: {source.suffix}")
            data = source.read_bytes()
            if len(data) > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail=f"file exceeds 50 MB: {source.name}")
            source_sha = hashlib.sha256(data).hexdigest()
            options = {
                "ocr": item.ocr,
                "extractor": item.extractor,
                "template": item.template,
            }
            key = f"{source_sha}|{item.ocr}|{item.extractor}|{item.template}|{item.lane}"
            state, created = store.reserve(
                idempotency_key=key,
                source_name=source.name,
                source_sha256=source_sha,
                doc_path=str(source),
                options=options,
                lane=item.lane,
            )
            accepted.append(
                {
                    "job_id": state.job_id,
                    "source_name": source.name,
                    "path": str(source),
                    "lane": item.lane,
                }
            )
            if created:
                background.add_task(run_job, store, state.job_id, settings)

        batch, created = batches.create(
            accepted, idempotency_key=request.idempotency_key
        )
        if not created:
            response.status_code = 200
            response.headers["X-Idempotent-Replay"] = "true"
        return batches.refresh(batch.batch_id, store).model_dump(mode="json")

    @app.get("/v1/batches")
    def list_batches(limit: int = Query(50, ge=1, le=200)) -> list[dict[str, Any]]:
        return [
            batches.refresh(item.batch_id, store).model_dump(mode="json")
            for item in batches.list(limit=limit)
        ]

    @app.get("/v1/batches/{batch_id}")
    def get_batch(batch_id: str) -> dict[str, Any]:
        batch = batches.get(batch_id)
        if batch is None:
            raise HTTPException(status_code=404, detail=f"batch not found: {batch_id}")
        return batches.refresh(batch.batch_id, store).model_dump(mode="json")

    @app.get("/v1/business-dictionary")
    def get_business_dictionary(
        entry_type: str | None = Query(default=None, alias="type"),
        q: str | None = Query(default=None),
        limit: int = Query(200, ge=1, le=2000),
    ) -> Any:
        if dictionary is None:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "business dictionary not configured",
                    "path": settings.business_dictionary_path,
                },
            )
        entries = [
            entry
            for entry in dictionary.entries
            if (not entry_type or entry.type == entry_type)
            and (
                not q
                or q in entry.business_name
                or any(q in alias for alias in entry.aliases)
            )
        ]
        counts = Counter(entry.type for entry in dictionary.entries)
        return {
            "version": dictionary.version,
            "source": dictionary.source,
            "counts": {
                "categories": counts["category"],
                "items": counts["item"],
                "methods": counts["method"],
            },
            "total": len(entries),
            "entries": [entry.model_dump(mode="json") for entry in entries[:limit]],
        }

    return app


def _load_dictionary(settings: Settings):
    path = Path(settings.business_dictionary_path)
    if not path.is_absolute():
        path = settings.project_root / path
    if not path.exists():
        return None
    override_path = _override_path(settings)
    try:
        return JsonDictionaryAdapter(path, override_path).load()
    except Exception:  # noqa: BLE001 - the API stays usable without a dictionary
        return None


def _override_path(settings: Settings) -> Path | None:
    value = settings.business_dictionary_override_path
    if not value:
        return None
    path = Path(value)
    return path if path.is_absolute() else settings.project_root / path


if FASTAPI_AVAILABLE:  # pragma: no cover - optional dependency
    app = create_app()
