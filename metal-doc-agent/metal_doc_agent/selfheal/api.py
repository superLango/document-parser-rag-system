"""Standalone FastAPI service for the self-heal route (default off).

When ``SELFHEAL_ENABLED=0`` only ``/healthz`` exists; no database is opened,
no route is registered and no file is written. When enabled, the service owns
its own SQLite database and never calls into the production platform API.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from .config import SelfHealSettings
from .contracts import FeedbackCreate, FeedbackStatus
from .feedback import FeedbackService
from .l2 import rollback_overlay
from .pipeline import SelfHealPipeline
from .storage import SelfHealStore

STATIC_DIR = Path(__file__).resolve().parents[2] / "apps" / "selfheal" / "static"


class MessagePayload(BaseModel):
    content: str
    role: str = "user"


class AuditPayload(BaseModel):
    job_dir: str
    out_dir: str | None = None


def create_selfheal_app(
    settings: SelfHealSettings | None = None,
    *,
    pipeline: SelfHealPipeline | None = None,
):
    from fastapi import FastAPI, HTTPException
    from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse

    settings = settings or SelfHealSettings.from_env()
    app = FastAPI(
        title="Hanson SelfHeal",
        version="0.1.0",
        docs_url="/docs" if settings.enabled else None,
        redoc_url="/redoc" if settings.enabled else None,
        openapi_url="/openapi.json" if settings.enabled else None,
    )

    @app.get("/healthz")
    def healthz() -> dict[str, Any]:
        return {"status": "ok", "enabled": settings.enabled}

    if not settings.enabled:
        return app

    settings.ensure_dirs()
    store = SelfHealStore(settings.db_path)
    service = FeedbackService(store, settings)
    runner = pipeline or SelfHealPipeline(store, settings)

    @app.post("/v1/selfheal/feedback")
    def create_feedback(payload: FeedbackCreate) -> dict[str, Any]:
        outcome = service.create(payload)
        return {
            "feedback": outcome["feedback"].model_dump(mode="json"),
            "problems": outcome["problems"],
            "finding_id": outcome["finding"].finding_id if outcome["finding"] else None,
        }

    @app.get("/v1/selfheal/feedback")
    def list_feedback(doc_id: str | None = None, status: str | None = None) -> dict[str, Any]:
        items = store.list_feedback(doc_id=doc_id, status=status)
        return {"items": [item.model_dump(mode="json") for item in items]}

    @app.get("/v1/selfheal/feedback/{feedback_id}")
    def get_feedback(feedback_id: str) -> dict[str, Any]:
        item = store.get_feedback(feedback_id)
        if item is None:
            raise HTTPException(status_code=404, detail="feedback not found")
        return {
            "feedback": item.model_dump(mode="json"),
            "messages": [message.model_dump(mode="json") for message in store.list_messages(feedback_id)],
            "findings": [
                finding.model_dump(mode="json")
                for finding in store.list_findings_for_feedback(feedback_id)
            ],
        }

    @app.post("/v1/selfheal/feedback/{feedback_id}/messages")
    def add_message(feedback_id: str, payload: MessagePayload) -> dict[str, Any]:
        if store.get_feedback(feedback_id) is None:
            raise HTTPException(status_code=404, detail="feedback not found")
        message = service.add_message(feedback_id, payload.content, payload.role)
        return message.model_dump(mode="json")

    @app.post("/v1/selfheal/feedback/{feedback_id}/process")
    def process(feedback_id: str) -> dict[str, Any]:
        if store.get_feedback(feedback_id) is None:
            raise HTTPException(status_code=404, detail="feedback not found")
        outcome = runner.process_feedback(feedback_id)
        return outcome.model_dump(mode="json")

    ARTIFACT_KINDS = {"table_fix", "sandbox", "audit"}
    ARTIFACT_NAMES = {
        "result.json",
        "repair_diff.json",
        "plan.json",
        "item_inventory_aligned.json",
        "item_inventory.json",
        "outline.json",
        "cross_standard_merge.json",
        "evidence.jsonl",
        "clauses.jsonl",
    }

    def _artifact_path(feedback_id: str, kind: str, name: str) -> Path:
        if store.get_feedback(feedback_id) is None:
            raise HTTPException(status_code=404, detail="feedback not found")
        if kind not in ARTIFACT_KINDS or name not in ARTIFACT_NAMES:
            raise HTTPException(status_code=400, detail="unsupported artifact")
        path = settings.jobs_root / feedback_id / kind / name
        if not path.exists():
            raise HTTPException(status_code=404, detail="artifact not found")
        return path

    @app.get("/v1/selfheal/feedback/{feedback_id}/repair")
    def get_repair(feedback_id: str) -> dict[str, Any]:
        if store.get_feedback(feedback_id) is None:
            raise HTTPException(status_code=404, detail="feedback not found")
        base = settings.jobs_root / feedback_id
        for kind in ("table_fix", "sandbox", "audit"):
            result_path = base / kind / "result.json"
            if not result_path.exists():
                continue
            summary = {}
            diff_path = base / kind / "repair_diff.json"
            if diff_path.exists():
                try:
                    summary = json.loads(diff_path.read_text(encoding="utf-8"))
                except ValueError:
                    summary = {}
            plan = {}
            plan_path = base / kind / "plan.json"
            if plan_path.exists():
                try:
                    plan = json.loads(plan_path.read_text(encoding="utf-8"))
                except ValueError:
                    plan = {}
            return {
                "available": True,
                "kind": kind,
                "summary": summary.get("summary") or {},
                "table_id": plan.get("table_id"),
                "spec": plan.get("spec"),
                "out_dir": str(base / kind),
            }
        return {"available": False}

    @app.get("/v1/selfheal/feedback/{feedback_id}/artifact")
    def get_artifact(
        feedback_id: str,
        name: str = "result.json",
        kind: str = "table_fix",
    ):
        path = _artifact_path(feedback_id, kind, name)
        return FileResponse(path, media_type="application/json", filename=name)

    @app.get("/v1/selfheal/feedback/{feedback_id}/artifact-text")
    def get_artifact_text(
        feedback_id: str,
        name: str = "evidence.jsonl",
        kind: str = "table_fix",
    ):
        path = _artifact_path(feedback_id, kind, name)
        return PlainTextResponse(
            path.read_text(encoding="utf-8", errors="ignore"),
            media_type="text/plain",
        )

    @app.get("/v1/selfheal/jobs/{job_id}")
    def get_job(job_id: str) -> dict[str, Any]:
        feedback = store.list_feedback()
        scoped = [item for item in feedback if item.job_id == job_id]
        doc_ids = {item.doc_id for item in scoped}
        findings = [
            finding.model_dump(mode="json")
            for doc_id in doc_ids
            for finding in store.list_findings(doc_id=doc_id)
            if finding.job_id == job_id
        ]
        return {
            "job_id": job_id,
            "feedback": [item.model_dump(mode="json") for item in scoped],
            "findings": findings,
        }

    @app.get("/v1/selfheal/jobs/{job_id}/diff")
    def get_job_diff(job_id: str) -> dict[str, Any]:
        return {"job_id": job_id, "diff": _latest_diff(store, settings, job_id)}

    @app.get("/v1/selfheal/proposals/{proposal_id}")
    def get_proposal(proposal_id: str) -> dict[str, Any]:
        proposal = store.get_proposal(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="proposal not found")
        gate = store.latest_gate(proposal_id)
        return {
            "proposal": proposal.model_dump(mode="json"),
            "gate": gate.model_dump(mode="json") if gate else None,
        }

    @app.post("/v1/selfheal/proposals/{proposal_id}/rollback")
    def rollback(proposal_id: str) -> dict[str, Any]:
        proposal = store.get_proposal(proposal_id)
        if proposal is None:
            raise HTTPException(status_code=404, detail="proposal not found")
        store.update_proposal_status(proposal_id, "rolled_back")
        try:
            rollback_overlay(proposal)
        except OSError:
            pass
        return {"proposal_id": proposal_id, "status": "rolled_back"}

    @app.get("/v1/selfheal/metrics")
    def metrics() -> dict[str, Any]:
        return store.metrics()

    @app.post("/v1/selfheal/audit")
    def audit(payload: AuditPayload) -> dict[str, Any]:
        findings = runner.audit_job(payload.job_dir, payload.out_dir)
        return {"findings": [finding.model_dump(mode="json") for finding in findings]}

    @app.get("/selfheal/ui")
    def ui():
        index = STATIC_DIR / "index.html"
        if not index.exists():
            return JSONResponse({"detail": "ui not installed"}, status_code=404)
        return FileResponse(index)

    return app


def _latest_diff(store: SelfHealStore, settings: SelfHealSettings, job_id: str) -> dict | None:
    import json

    for item in store.list_feedback():
        if item.job_id != job_id:
            continue
        base = settings.jobs_root / item.feedback_id
        repair = base / "sandbox" / "repair_diff.json"
        if repair.exists():
            return json.loads(repair.read_text(encoding="utf-8"))
        shadows = sorted(base.glob("shadow_*"), reverse=True)
        for child in shadows:
            path = child / "shadow_diff.json"
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))
    return None
