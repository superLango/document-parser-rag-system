import asyncio
import hashlib
import json
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import func, select

from .config import settings
from .db import SessionLocal
from .models import Artifact, Run, RunEvent, RunStage
from .state import TERMINAL_STATES, RunState, ensure_transition, is_terminal
from .storage import ObjectStore

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


async def _execute_stage(
    run_id: str,
    stage: str,
    running_state: RunState,
    done_state: RunState,
    artifact_role: str,
    action: StageAction,
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

        await _append_event(session, run, "run.stage.started", stage, "started", {})
        await session.commit()

        try:
            await asyncio.sleep(settings.mock_stage_delay_seconds)
            output = await action(run)
            artifact_key = await _store_artifact(session, run, artifact_role, output)
            ensure_transition(run.status, done_state)
            run.status = done_state
            run.stage = done_state
            stage_row.status = "completed"
            stage_row.finished_at = now()
            stage_row.duration_ms = int(
                (stage_row.finished_at - started).total_seconds() * 1000
            )
            stage_row.output_refs = {"artifact": artifact_key}
            await _append_event(
                session,
                run,
                "run.stage.completed",
                stage,
                "completed",
                {"artifact": artifact_key},
            )
            await session.commit()
        except Exception as exc:
            logger.exception("stage %s failed for run %s", stage, run_id)
            stage_row.status = "failed"
            stage_row.finished_at = now()
            stage_row.error_code = "INTERNAL"
            stage_row.duration_ms = int((stage_row.finished_at - started).total_seconds() * 1000)
            await session.commit()
            raise exc


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
                select(Artifact).where(Artifact.run_id == run.id, Artifact.role == "result")
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
            _fake_ocr,
        )
        await _execute_stage(
            run_id,
            "routing",
            RunState.ROUTING,
            RunState.ROUTED,
            "routing",
            _fake_route,
        )
        await _execute_stage(
            run_id,
            "sandbox",
            RunState.SANDBOX_RUNNING,
            RunState.PARSED,
            "result",
            _fake_sandbox,
        )
        await _execute_stage(
            run_id,
            "review",
            RunState.REVIEWING,
            RunState.REVIEW_PASSED,
            "review",
            _fake_review,
        )
        await _finalize(run_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        await _mark_failed(run_id, "INTERNAL", str(exc))


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
