import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

import httpx
from hanson_contracts import (
    DocumentRef,
    EngineRef,
    ExecutionRequest,
    ExecutionResult,
    ObjectInput,
    RecipeRef,
    ResourceLimits,
    ReviewReport,
    ReviewRequest,
    TableAssignment,
    TemplateRef,
)
from sqlalchemy import func, select

from services.shared.storage import ObjectStore

from .config import settings
from .db import SessionLocal
from .models import Artifact, Document, Finding, Run, RunEvent, RunStage
from .models import ReviewReport as ReviewReportRow
from .state import TERMINAL_STATES, RunState, ensure_transition, is_terminal

logger = logging.getLogger(__name__)

_tasks: dict[str, asyncio.Task[None]] = {}
_store: ObjectStore | None = None

StageAction = Callable[[Run], Awaitable[dict]]


def now() -> datetime:
    return datetime.now(UTC)


def set_store(store: ObjectStore) -> None:
    global _store
    _store = store


def get_store() -> ObjectStore:
    if _store is None:
        raise RuntimeError("object store is not initialized")
    return _store


async def _append_event(
    session,
    run: Run,
    event_type: str,
    stage: str,
    status: str,
    payload: dict | None = None,
) -> None:
    result = await session.execute(
        select(func.max(RunEvent.sequence)).where(RunEvent.run_id == run.id)
    )
    sequence = (result.scalar() or 0) + 1
    session.add(
        RunEvent(
            run_id=run.id,
            sequence=sequence,
            type=event_type,
            stage=stage,
            status=status,
            payload=payload or {},
        )
    )


async def _store_artifact(session, run: Run, role: str, payload: dict) -> str:
    data = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
    key = f"runs/{run.id}/{role}.json"
    await get_store().put_bytes(key, data, "application/json")
    session.add(
        Artifact(
            run_id=run.id,
            role=role,
            storage_key=key,
            sha256=hashlib.sha256(data).hexdigest(),
            bytes=len(data),
        )
    )
    return key


async def _attempt_stage(
    run_id: str,
    stage: str,
    running_state: RunState,
    done_state: RunState,
    artifact_role: str | None,
    action: StageAction,
    attempt: int,
) -> None:
    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        if run is None or is_terminal(run.status):
            return

        if run.status == done_state.value:
            logger.info("run %s already at %s; skip stage %s", run_id, done_state, stage)
            return

        result = await session.execute(
            select(RunStage).where(RunStage.run_id == run_id, RunStage.stage == stage)
        )
        stage_row = result.scalars().first()
        if stage_row is not None and stage_row.status == "completed":
            logger.info("run %s stage %s already completed; skip", run_id, stage)
            return

        started = now()
        if run.status != running_state.value:
            ensure_transition(run.status, running_state)
            run.status = running_state.value
        run.stage = stage
        run.started_at = run.started_at or started

        if stage_row is None:
            stage_row = RunStage(run_id=run_id, stage=stage, started_at=started)
            session.add(stage_row)
        else:
            stage_row.status = "running"
            stage_row.started_at = started
            stage_row.finished_at = None
            stage_row.error_code = None

        await _append_event(
            session, run, "run.stage.started", stage, "started", {"attempt": attempt}
        )
        await session.commit()

        await asyncio.sleep(settings.mock_stage_delay_seconds)
        _inject_mock_failure(stage, attempt)
        output = await action(run)
        if artifact_role is None:
            if "output_refs" in output:
                artifact_key = str(output.get("result_key") or "")
                output_refs = dict(output.get("output_refs") or {})
            else:
                # 回滚到 fake 沙箱时没有外部执行，按普通阶段产物落盘。
                artifact_key = await _store_artifact(session, run, "result", output)
                output_refs = {"artifact": artifact_key}
        else:
            artifact_key = await _store_artifact(session, run, artifact_role, output)
            output_refs = {"artifact": artifact_key}
        ensure_transition(run.status, done_state)
        run.status = done_state
        run.stage = done_state
        stage_row.status = "completed"
        # 系统时钟可能回跳（WSL/NTP 校正），保证结束时间不早于开始时间。
        stage_row.finished_at = max(now(), started)
        stage_row.duration_ms = int((stage_row.finished_at - started).total_seconds() * 1000)
        stage_row.output_refs = output_refs
        await _append_event(
            session,
            run,
            "run.stage.completed",
            stage,
            "completed",
            {"attempt": attempt, **output_refs},
        )
        await session.commit()


def _inject_mock_failure(stage: str, attempt: int) -> None:
    """开发期故障注入，用于验证阶段重试；接入真实实现后移除。"""
    if settings.mock_fail_stage == stage and attempt <= settings.mock_fail_times:
        raise RuntimeError(f"mock failure in stage {stage} attempt {attempt}")


async def _record_stage_failure(
    run_id: str,
    stage: str,
    attempt: int,
    final: bool,
    exc: Exception,
) -> None:
    logger.warning(
        "stage %s failed for run %s (attempt %s/%s, final=%s): %s",
        stage,
        run_id,
        attempt,
        settings.stage_max_attempts,
        final,
        exc,
    )
    async with SessionLocal() as session:
        result = await session.execute(
            select(RunStage).where(RunStage.run_id == run_id, RunStage.stage == stage)
        )
        stage_row = result.scalars().first()
        if stage_row is not None:
            stage_row.status = "failed"
            stage_row.error_code = "INTERNAL"
            if stage_row.started_at is not None:
                stage_row.finished_at = max(now(), stage_row.started_at)
                stage_row.duration_ms = int(
                    (stage_row.finished_at - stage_row.started_at).total_seconds() * 1000
                )
            else:
                stage_row.finished_at = now()
        run = await session.get(Run, run_id)
        if run is not None:
            await _append_event(
                session,
                run,
                "run.stage.failed",
                stage,
                "failed",
                {
                    "attempt": attempt,
                    "will_retry": not final,
                    "error": str(exc)[:500],
                },
            )
        await session.commit()


async def _execute_stage(
    run_id: str,
    stage: str,
    running_state: RunState,
    done_state: RunState,
    artifact_role: str | None,
    action: StageAction,
) -> None:
    attempts = max(1, settings.stage_max_attempts)
    for attempt in range(1, attempts + 1):
        try:
            await _attempt_stage(
                run_id,
                stage,
                running_state,
                done_state,
                artifact_role,
                action,
                attempt,
            )
            return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            final = attempt >= attempts
            await _record_stage_failure(run_id, stage, attempt, final, exc)
            if final:
                raise
            await asyncio.sleep(settings.stage_retry_backoff_seconds * attempt)


async def _fake_ocr(_: Run) -> dict:
    return {
        "pages": [{"page_no": 1, "width": 1000, "height": 1400}],
        "markdown": "# M1 fake OCR\n\nQ355B 力学性能表。",
        "tables": [
            {
                "table_id": "T1",
                "page_no": 1,
                "profile": "mechanical_properties",
                "n_rows": 2,
                "n_cols": 4,
            }
        ],
        "quality": 0.99,
    }


async def _ocr_stage(run: Run) -> dict:
    async with SessionLocal() as session:
        document = await session.get(Document, run.document_id)
        if document is None:
            raise RuntimeError(f"document not found: {run.document_id}")
        payload = {
            "document_id": document.id,
            "storage_key": document.storage_key,
            "filename": document.filename,
            "content_type": document.content_type,
            "backend": settings.ocr_backend or None,
        }

    result = await _call_ocr(payload)
    await _record_ocr_artifacts(run, result.get("artifacts") or [])
    return result


async def _call_ocr(payload: dict) -> dict:
    url = f"{settings.ocr_url.rstrip('/')}/internal/ocr/parse"
    try:
        async with httpx.AsyncClient(timeout=settings.ocr_timeout_seconds) as client:
            response = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"ocr service unavailable: {exc}") from exc
    if response.status_code != 200:
        raise RuntimeError(f"ocr service error {response.status_code}: {response.text[:500]}")
    return response.json()


async def _record_ocr_artifacts(run: Run, artifacts: list[dict]) -> None:
    if not artifacts:
        return
    async with SessionLocal() as session:
        for item in artifacts:
            key = str(item.get("key") or "")
            if not key:
                continue
            session.add(
                Artifact(
                    run_id=run.id,
                    role=key.rsplit("/", 1)[-1],
                    storage_key=key,
                    sha256=str(item.get("sha256") or ""),
                    bytes=int(item.get("bytes") or 0),
                )
            )
        await session.commit()


async def _fake_route(_: Run) -> dict:
    return {
        "assignments": [
            {
                "table_id": "T1",
                "recipe_id": "mechanical_properties",
                "version": "2.0.0",
                "confidence": 0.92,
                "reasons": ["fake-signature-match"],
            }
        ],
        "fallback": "generic",
        "confidence": 0.92,
    }


async def _route_stage(run: Run) -> dict:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Artifact)
            .where(Artifact.run_id == run.id, Artifact.role == "ocr")
            .order_by(Artifact.created_at.desc())
        )
        artifact = result.scalars().first()
    if artifact is None:
        raise RuntimeError(f"ocr artifact missing for run {run.id}")

    data = json.loads(await get_store().get_bytes(artifact.storage_key))
    tables = data.get("tables") or []
    assignments = []
    for table in tables:
        match = await _match_table(table)
        assignments.append(
            {
                "table_id": table.get("table_id"),
                "page_no": table.get("page_no"),
                "recipe_id": match.get("recipe_id"),
                "version": match.get("version"),
                "status": match.get("status"),
                "score": match.get("score"),
                "confidence": match.get("score"),
            }
        )
    confidence = max((item.get("score") or 0.0 for item in assignments), default=0.0)
    return {
        "assignments": assignments,
        "fallback": "generic",
        "confidence": round(confidence, 4),
    }


async def _match_table(table: dict) -> dict:
    url = f"{settings.recipe_registry_url.rstrip('/')}/internal/recipes/match"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json={"table": table})
    except httpx.HTTPError as exc:
        raise RuntimeError(f"recipe registry unavailable: {exc}") from exc
    if response.status_code != 200:
        raise RuntimeError(
            f"recipe registry error {response.status_code}: {response.text[:300]}"
        )
    return response.json()["result"]


class SandboxStageError(RuntimeError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


async def build_sandbox_request(
    run: Run,
    *,
    recipe_override: RecipeRef | None = None,
    table_id: str | None = None,
) -> ExecutionRequest:
    async with SessionLocal() as session:
        document = await session.get(Document, run.document_id)
        if document is None:
            raise RuntimeError(f"document not found: {run.document_id}")
        ocr_result = await session.execute(
            select(Artifact)
            .where(Artifact.run_id == run.id, Artifact.role == "ocr")
            .order_by(Artifact.created_at.desc())
        )
        ocr_artifact = ocr_result.scalars().first()
        routing_result = await session.execute(
            select(Artifact)
            .where(Artifact.run_id == run.id, Artifact.role == "routing")
            .order_by(Artifact.created_at.desc())
        )
        routing_artifact = routing_result.scalars().first()
    if ocr_artifact is None:
        raise RuntimeError(f"ocr artifact missing for run {run.id}")
    if routing_artifact is None:
        raise RuntimeError(f"routing artifact missing for run {run.id}")

    routing = json.loads(await get_store().get_bytes(routing_artifact.storage_key))
    assignments = [
        TableAssignment(
            table_id=str(item.get("table_id") or ""),
            recipe_id=str(item.get("recipe_id")),
            version=str(item.get("version")),
            digest=str(item.get("digest") or ""),
        )
        for item in routing.get("assignments") or []
        if item.get("table_id") and item.get("recipe_id") and item.get("version")
    ]
    if recipe_override is not None:
        assignments = _override_assignments(assignments, recipe_override, table_id)
    primary = (
        assignments[0]
        if assignments
        else TableAssignment(
            table_id="", recipe_id="mechanical_properties_v1", version="1.0.0"
        )
    )
    return ExecutionRequest(
        trace_id=run.trace_id or run.id,
        run_id=run.id,
        document=DocumentRef(
            document_id=document.id,
            filename=document.filename,
            storage_key=document.storage_key,
            sha256=document.sha256,
            size=document.size,
            content_type=document.content_type,
        ),
        ocr=ObjectInput(storage_key=ocr_artifact.storage_key, sha256=ocr_artifact.sha256),
        assignments=assignments,
        recipe=RecipeRef(
            recipe_id=primary.recipe_id,
            version=primary.version,
            digest=primary.digest,
        ),
        template=TemplateRef(
            template_id=settings.sandbox_template_id,
            version=settings.sandbox_template_version,
        ),
        engine=EngineRef(
            version=settings.sandbox_engine_version,
            image=settings.sandbox_engine_image,
        ),
        limits=ResourceLimits(
            cpu=settings.sandbox_cpu,
            memory_mb=settings.sandbox_memory_mb,
            pids=settings.sandbox_pids,
            timeout_seconds=settings.sandbox_run_timeout_seconds,
        ),
    )


def _override_assignments(
    assignments: list[TableAssignment],
    override: RecipeRef,
    table_id: str | None,
) -> list[TableAssignment]:
    updated: list[TableAssignment] = []
    replaced = False
    for item in assignments:
        match = (
            item.table_id == table_id
            if table_id
            else item.recipe_id == override.recipe_id
        )
        if match:
            updated.append(
                TableAssignment(
                    table_id=item.table_id,
                    recipe_id=override.recipe_id,
                    version=override.version,
                    digest=override.digest,
                )
            )
            replaced = True
        else:
            updated.append(item)
    if not replaced:
        updated.append(
            TableAssignment(
                table_id=table_id or "",
                recipe_id=override.recipe_id,
                version=override.version,
                digest=override.digest,
            )
        )
    return updated


async def _sandbox_stage(run: Run) -> dict:
    request = await build_sandbox_request(run)
    result = await _call_sandbox(request)
    if result.status != "succeeded":
        raise SandboxStageError(
            result.error_code or "SANDBOX_FAILED",
            result.error_message or f"sandbox finished with status {result.status}",
        )
    artifacts = await _record_sandbox_artifacts(run, result)
    return {
        "status": result.status,
        "result_key": artifacts.get("result", ""),
        "output_refs": {"artifacts": artifacts},
        "outputs": {role: item.storage_key for role, item in result.outputs.items()},
        "metrics": result.metrics.model_dump(mode="json"),
        "diagnostics": [item.model_dump(mode="json") for item in result.diagnostics],
    }


async def _call_sandbox(request: ExecutionRequest) -> ExecutionResult:
    url = f"{settings.sandbox_url.rstrip('/')}/internal/sandbox/execute"
    try:
        async with httpx.AsyncClient(timeout=settings.sandbox_timeout_seconds) as client:
            response = await client.post(url, json=request.model_dump(mode="json"))
    except httpx.HTTPError as exc:
        raise RuntimeError(f"sandbox service unavailable: {exc}") from exc
    if response.status_code != 200:
        raise RuntimeError(f"sandbox service error {response.status_code}: {response.text[:500]}")
    return ExecutionResult.model_validate(response.json())


async def _record_sandbox_artifacts(run: Run, result: ExecutionResult) -> dict[str, str]:
    keys = {role: item.storage_key for role, item in result.outputs.items()}
    if not keys:
        return {}
    async with SessionLocal() as session:
        existing = await session.execute(
            select(Artifact.storage_key).where(
                Artifact.run_id == run.id, Artifact.storage_key.in_(list(keys.values()))
            )
        )
        present = set(existing.scalars())
        for role, item in result.outputs.items():
            if item.storage_key in present:
                continue
            session.add(
                Artifact(
                    run_id=run.id,
                    role=role,
                    storage_key=item.storage_key,
                    sha256=item.sha256,
                    bytes=item.bytes,
                )
            )
        await session.commit()
    return keys


async def _fake_sandbox(_: Run) -> dict:
    return {
        "records": [
            {
                "record_id": "R1",
                "grade": "Q355B",
                "properties": {"Rm": {"value": 470, "unit": "MPa"}},
                "evidence_refs": ["ev-1"],
            }
        ],
        "tables": [{"table_id": "T1", "record_count": 1}],
    }


async def _latest_artifact(session, run_id: str, role: str) -> Artifact | None:
    result = await session.execute(
        select(Artifact)
        .where(Artifact.run_id == run_id, Artifact.role == role)
        .order_by(Artifact.created_at.desc())
    )
    return result.scalars().first()


async def _review_stage(run: Run) -> dict:
    async with SessionLocal() as session:
        records_artifact = await _latest_artifact(session, run.id, "records")
        evidence_artifact = await _latest_artifact(session, run.id, "evidence")
        result_artifact = await _latest_artifact(session, run.id, "result")
    if records_artifact is None:
        raise RuntimeError(f"records artifact missing for run {run.id}")
    if evidence_artifact is None:
        raise RuntimeError(f"evidence artifact missing for run {run.id}")
    records_payload = json.loads(await get_store().get_bytes(records_artifact.storage_key))
    records = records_payload.get("records") or []
    evidence_lines = (
        (await get_store().get_bytes(evidence_artifact.storage_key))
        .decode("utf-8")
        .splitlines()
    )
    evidence = [json.loads(line) for line in evidence_lines if line.strip()]
    result = (
        json.loads(await get_store().get_bytes(result_artifact.storage_key))
        if result_artifact is not None
        else {}
    )
    request = ReviewRequest(
        run_id=run.id,
        trace_id=run.trace_id,
        records=records,
        evidence=evidence,
        tables=result.get("tables") or [],
        template=result.get("template") or {},
    )
    report = await _call_review(request)
    await _persist_review(run, report)
    return report.model_dump(mode="json")


async def _call_review(request: ReviewRequest) -> ReviewReport:
    url = f"{settings.review_url.rstrip('/')}/internal/review"
    try:
        async with httpx.AsyncClient(timeout=settings.review_timeout_seconds) as client:
            response = await client.post(url, json=request.model_dump(mode="json"))
    except httpx.HTTPError as exc:
        raise RuntimeError(f"review service unavailable: {exc}") from exc
    if response.status_code != 200:
        raise RuntimeError(f"review service error {response.status_code}: {response.text[:500]}")
    return ReviewReport.model_validate(response.json())


async def _persist_review(run: Run, report: ReviewReport) -> None:
    try:
        async with SessionLocal() as session:
            existing = await session.execute(
                select(ReviewReportRow).where(ReviewReportRow.run_id == run.id)
            )
            for row in existing.scalars():
                await session.delete(row)
            await session.flush()
            report_row = ReviewReportRow(
                run_id=run.id,
                status=report.status,
                ruleset_version=report.ruleset_version,
                stats=report.stats,
                degraded=report.degraded,
            )
            session.add(report_row)
            await session.flush()
            for finding in report.findings:
                session.add(
                    Finding(
                        run_id=run.id,
                        report_id=report_row.id,
                        source=finding.source,
                        category=finding.category,
                        severity=finding.severity,
                        target=finding.target,
                        observed=finding.observed,
                        expected=finding.expected,
                        evidence_refs=finding.evidence_refs,
                        confidence=finding.confidence,
                        status="open",
                    )
                )
            await session.commit()
    except Exception:
        logger.exception("failed to persist review report for run %s", run.id)


async def _fake_review(_: Run) -> dict:
    return {
        "status": "pass",
        "findings": [],
        "stats": {"records": 1, "findings": 0},
        "ruleset_version": "m1",
    }


async def _finalize(run_id: str) -> None:
    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        if run is None or is_terminal(run.status):
            return
        if run.status == RunState.REVIEW_PASSED.value:
            ensure_transition(run.status, RunState.STRUCTURED_READY)
            run.status = RunState.STRUCTURED_READY.value
            run.stage = RunState.STRUCTURED_READY.value
            run.finished_at = now()
            result = await session.execute(
                select(Artifact)
                .where(Artifact.run_id == run.id, Artifact.role == "result")
                .order_by(Artifact.created_at.desc())
            )
            artifact = result.scalars().first()
            run.result_key = artifact.storage_key if artifact else None
            await _append_event(
                session,
                run,
                "run.completed",
                RunState.STRUCTURED_READY.value,
                "completed",
                {"result_key": run.result_key},
            )
            await session.commit()


async def cancel(run_id: str) -> None:
    task = _tasks.get(run_id)
    if task is not None and not task.done():
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        if run is None or is_terminal(run.status):
            return
        run.status = RunState.CANCELLED.value
        run.stage = RunState.CANCELLED.value
        run.finished_at = now()
        await _append_event(
            session,
            run,
            "run.cancelled",
            RunState.CANCELLED.value,
            "cancelled",
            {},
        )
        await session.commit()


async def _mark_failed(run_id: str, error_code: str, detail: str) -> None:
    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        if run is None or is_terminal(run.status):
            return
        run.status = RunState.FAILED.value
        run.stage = RunState.FAILED.value
        run.error_code = error_code
        run.finished_at = now()
        await _append_event(
            session,
            run,
            "run.failed",
            RunState.FAILED.value,
            "failed",
            {"error_code": error_code, "detail": detail[:1000]},
        )
        await session.commit()


async def run_workflow(run_id: str) -> None:
    try:
        await _execute_stage(
            run_id,
            "ocr",
            RunState.OCR_RUNNING,
            RunState.OCR_DONE,
            "ocr",
            _fake_ocr if settings.ocr_use_fake else _ocr_stage,
        )
        await _execute_stage(
            run_id,
            "routing",
            RunState.ROUTING,
            RunState.ROUTED,
            "routing",
            _fake_route if settings.route_use_fake else _route_stage,
        )
        await _execute_stage(
            run_id,
            "sandbox",
            RunState.SANDBOX_RUNNING,
            RunState.PARSED,
            None,
            _fake_sandbox if settings.sandbox_use_fake else _sandbox_stage,
        )
        await _execute_stage(
            run_id,
            "review",
            RunState.REVIEWING,
            RunState.REVIEW_PASSED,
            "review",
            _fake_review if settings.review_use_fake else _review_stage,
        )
        await _finalize(run_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await _mark_failed(run_id, getattr(exc, "error_code", "INTERNAL"), str(exc))


def schedule(run_id: str) -> None:
    current = _tasks.get(run_id)
    if current is not None and not current.done():
        return
    task = asyncio.create_task(run_workflow(run_id))
    _tasks[run_id] = task

    def _cleanup(_: asyncio.Task[None]) -> None:
        _tasks.pop(run_id, None)

    task.add_done_callback(_cleanup)


async def resume_incomplete_runs() -> int:
    terminal = [state.value for state in TERMINAL_STATES]
    async with SessionLocal() as session:
        result = await session.execute(select(Run).where(Run.status.notin_(terminal)))
        runs = list(result.scalars())
    for run in runs:
        schedule(run.id)
    return len(runs)
