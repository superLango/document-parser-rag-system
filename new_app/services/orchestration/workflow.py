import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path

import httpx
from hanson_contracts import (
    AgentBudget,
    AgentResult,
    AgentTask,
    DocumentRef,
    EngineRef,
    ExecutionRequest,
    ExecutionResult,
    ObjectInput,
    ParserAssetRef,
    RecipeRef,
    ResourceLimits,
    ReviewReport,
    ReviewRequest,
    RouteDecision,
    TableAssignment,
    TemplateRef,
)
from sqlalchemy import func, or_, select

from services.shared.storage import ObjectStore

from .config import settings
from .db import SessionLocal
from .models import Artifact, Document, Feedback, Finding, Run, RunEvent, RunStage
from .models import ReviewReport as ReviewReportRow
from .state import TERMINAL_STATES, RunState, ensure_transition, is_terminal

logger = logging.getLogger(__name__)

_tasks: dict[str, asyncio.Task[None]] = {}
_store: ObjectStore | None = None

StageAction = Callable[[Run], Awaitable[dict]]


def now() -> datetime:
    return datetime.now(UTC)


# P2-01：阶段级进度（0-100），只增不减；人工复核停在 95。
STAGE_PROGRESS: dict[RunState, int] = {
    RunState.RECEIVED: 0,
    RunState.OCR_RUNNING: 10,
    RunState.OCR_DONE: 25,
    RunState.ROUTING: 30,
    RunState.ROUTED: 35,
    RunState.SANDBOX_RUNNING: 45,
    RunState.PARSED: 70,
    RunState.REVIEWING: 80,
    RunState.REVIEW_PASSED: 90,
    RunState.REPAIRING: 85,
    RunState.REPARSING: 60,
    RunState.HUMAN_REVIEW: 95,
    RunState.STRUCTURED_READY: 100,
}


def progress_for(state: RunState) -> int:
    return STAGE_PROGRESS.get(state, 0)


def set_store(store: ObjectStore) -> None:
    global _store
    _store = store


def get_store() -> ObjectStore:
    if _store is None:
        raise RuntimeError("object store is not initialized")
    return _store


async def append_event(
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
    await append_event(
        session,
        run,
        "artifact.created",
        run.stage,
        "completed",
        {
            "role": role,
            "storage_key": key,
            "sha256": hashlib.sha256(data).hexdigest(),
            "bytes": len(data),
        },
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
    force: bool = False,
) -> None:
    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        if run is None or is_terminal(run.status):
            return

        if run.status == done_state.value and not force:
            logger.info("run %s already at %s; skip stage %s", run_id, done_state, stage)
            return

        result = await session.execute(
            select(RunStage).where(RunStage.run_id == run_id, RunStage.stage == stage)
        )
        stage_row = result.scalars().first()
        if stage_row is not None and stage_row.status == "completed" and not force:
            logger.info("run %s stage %s already completed; skip", run_id, stage)
            return

        started = now()
        if run.status != running_state.value:
            ensure_transition(run.status, running_state)
            run.status = running_state.value
        run.stage = stage
        run.progress = max(int(run.progress or 0), progress_for(running_state))
        run.started_at = run.started_at or started

        if stage_row is None:
            stage_row = RunStage(run_id=run_id, stage=stage, started_at=started)
            session.add(stage_row)
        else:
            stage_row.status = "running"
            stage_row.started_at = started
            stage_row.finished_at = None
            stage_row.error_code = None

        await append_event(
            session, run, "run.stage.started", stage, "started", {"attempt": attempt}
        )
        await session.commit()

        if settings.environment == "dev":
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
        if run.status != done_state:
            ensure_transition(run.status, done_state)
        run.status = done_state
        run.stage = done_state
        run.progress = max(int(run.progress or 0), progress_for(done_state))
        stage_row.status = "completed"
        # 系统时钟可能回跳（WSL/NTP 校正），保证结束时间不早于开始时间。
        stage_row.finished_at = max(now(), started)
        stage_row.duration_ms = int(
            (stage_row.finished_at - started).total_seconds() * 1000
        )
        stage_row.output_refs = output_refs
        await append_event(
            session,
            run,
            "run.stage.completed",
            stage,
            "completed",
            {"attempt": attempt, **output_refs},
        )
        if stage == "routing" and output.get("needs_human"):
            await append_event(
                session,
                run,
                "run.route.needs_human",
                stage,
                "warning",
                {
                    "tables": list(output["needs_human"])[:50],
                    "count": len(output["needs_human"]),
                    "agent_used": bool(output.get("agent_used")),
                },
            )
        await session.commit()
        return output


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
            stage_row.error_code = getattr(exc, "error_code", "INTERNAL")
            if stage_row.started_at is not None:
                stage_row.finished_at = max(now(), stage_row.started_at)
                stage_row.duration_ms = int(
                    (stage_row.finished_at - stage_row.started_at).total_seconds() * 1000
                )
            else:
                stage_row.finished_at = now()
        run = await session.get(Run, run_id)
        if run is not None:
            await append_event(
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
    force: bool = False,
) -> dict:
    attempts = max(1, settings.stage_max_attempts)
    for attempt in range(1, attempts + 1):
        try:
            output = await _attempt_stage(
                run_id,
                stage,
                running_state,
                done_state,
                artifact_role,
                action,
                attempt,
                force=force,
            )
            if output is None:
                # 阶段已完成被跳过时回读已落盘产物，避免下游拿到 None 再 .get()。
                return await _artifact_payload(run_id, artifact_role) if artifact_role else {}
            return output
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            # Deterministic review rejections and OCR backend outages are not
            # transient; retrying only extends the outage.
            final = attempt >= attempts or isinstance(
                exc, (ReviewGateError, OcrStageError, RoutingStageError)
            )
            await _record_stage_failure(run_id, stage, attempt, final, exc)
            if final:
                raise
            await asyncio.sleep(settings.stage_retry_backoff_seconds * attempt)


async def _fake_ocr(_: Run) -> dict:
    return {
        "simulated": True,
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


async def _call_ocr(payload: dict, *, allow_native_fallback: bool = True) -> dict:
    url = f"{settings.ocr_url.rstrip('/')}/internal/ocr/parse"
    try:
        async with httpx.AsyncClient(timeout=settings.ocr_timeout_seconds) as client:
            response = await client.post(url, json=payload)
    except httpx.TimeoutException as exc:
        # 大页数文档走视觉 OCR 可能超过编排超时；退回到原生文本解析，
        # 让 run 以“低覆盖 + review 提示”的方式完成，而不是直接失败。
        if allow_native_fallback and str(payload.get("content_type") or "").endswith("pdf"):
            logger.warning(
                "ocr timeout for %s; retrying with native pdf text",
                payload.get("document_id"),
            )
            return await _call_ocr(
                {**payload, "backend": "pdf"}, allow_native_fallback=False
            )
        raise OcrStageError(
            "OCR_BACKEND_UNAVAILABLE", f"ocr service timeout: {exc}"
        ) from exc
    except httpx.HTTPError as exc:
        raise OcrStageError(
            "OCR_BACKEND_UNAVAILABLE", f"ocr service unavailable: {exc}"
        ) from exc
    if response.status_code != 200:
        code = "OCR_SERVICE_ERROR"
        try:
            detail = response.json().get("detail")
            if isinstance(detail, dict) and detail.get("code"):
                code = str(detail["code"])
        except ValueError:
            pass
        raise OcrStageError(
            code, f"ocr service error {response.status_code}: {response.text[:500]}"
        )
    try:
        return response.json()
    except ValueError as exc:
        raise OcrStageError("OCR_SERVICE_ERROR", "ocr response is not JSON") from exc


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
            await append_event(
                session,
                run,
                "artifact.created",
                run.stage,
                "completed",
                {
                    "role": key.rsplit("/", 1)[-1],
                    "storage_key": key,
                    "sha256": str(item.get("sha256") or ""),
                    "bytes": int(item.get("bytes") or 0),
                },
            )
        await session.commit()


async def _fake_route(_: Run) -> dict:
    return {
        "simulated": True,
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


ROUTE_LOW_CONFIDENCE = 0.6
# RouterAgent 只处理“像表但未命中配方”的低置信表：必须是性能/成分表，
# 且质量门禁通过；否则一律转人工，避免散文碎片被模型硬塞配方。
ROUTE_AGENT_PROFILES = {"mechanical_properties", "chemical_composition"}
ROUTE_AGENT_BLOCKED_FLAGS = {
    "prose_fragment",
    "single_column",
    "no_numeric_cells",
    "no_data_rows",
    "missing_header",
}
ROUTE_AGENT_MIN_CONFIDENCE = 0.7
ROUTE_AGENT_MAX_TABLES = 8
# 同一文档内结构相近的表格必须路由到同一配方：RouterAgent 不可用时，
# 否则这些表会整表转人工并从解析结果中消失（GB/T 3880.2 的 8 张力学表）。
ROUTE_SIBLING_MIN_SIMILARITY = 0.85
ROUTE_SIBLING_MAX_COL_DIFF = 8


def select_agent_tables(
    pending: list[tuple[dict, dict]],
) -> list[tuple[dict, dict]]:
    """Pick high-quality property tables that deterministic routing gave up on."""
    selected: list[tuple[dict, dict]] = []
    for table, item in pending:
        quality = float(table.get("quality", 1.0))
        flags = {str(flag) for flag in table.get("quality_flags") or []}
        profile = str(table.get("profile") or "").lower()
        if quality < 0.7 or flags & ROUTE_AGENT_BLOCKED_FLAGS:
            continue
        if profile not in ROUTE_AGENT_PROFILES:
            continue
        selected.append((table, item))
    selected.sort(key=lambda pair: float(pair[0].get("quality") or 0.0), reverse=True)
    return selected[:ROUTE_AGENT_MAX_TABLES]


def apply_sibling_fallback(
    assignments: list[dict], tables_by_id: dict[str, dict]
) -> int:
    """Route low-confidence property tables that mirror an already routed table.

    Deterministic matching can miss a table by a few points (orientation
    misclassification, one extra column).  When the structure is nearly
    identical to a sibling that did route, dropping the table loses every
    record in it; assigning the sibling's recipe is evidence-based and keeps
    the document complete.  The RouterAgent still gets the first chance.
    """
    from services.ocr.contracts import TableGrid
    from services.recipe_registry.matcher import signature_tokens, token_similarity

    def _grid(table: dict) -> TableGrid | None:
        try:
            return TableGrid.model_validate(table)
        except (TypeError, ValueError):
            return None

    routed: dict[str, tuple[dict, TableGrid]] = {}
    for item in assignments:
        if not item.get("recipe_id"):
            continue
        if float(item.get("score") or 0) < ROUTE_LOW_CONFIDENCE:
            continue
        table = tables_by_id.get(str(item.get("table_id")))
        if table is None:
            continue
        grid = _grid(table)
        if grid is None or grid.profile not in ROUTE_AGENT_PROFILES:
            continue
        routed[str(item.get("table_id"))] = (item, grid)

    filled = 0
    for item in assignments:
        if item.get("recipe_id") and float(item.get("score") or 0) >= ROUTE_LOW_CONFIDENCE:
            continue
        table = tables_by_id.get(str(item.get("table_id")))
        if table is None:
            continue
        quality = float(table.get("quality", 1.0))
        flags = {str(flag) for flag in table.get("quality_flags") or []}
        if quality < 0.7 or flags & ROUTE_AGENT_BLOCKED_FLAGS:
            continue
        grid = _grid(table)
        if grid is None or grid.profile not in ROUTE_AGENT_PROFILES:
            continue
        tokens = signature_tokens(grid)
        if not tokens:
            continue
        best_item: dict | None = None
        best_similarity = 0.0
        for sibling_id, (sibling_item, sibling_grid) in routed.items():
            if sibling_grid.profile != grid.profile:
                continue
            if (
                grid.profile == "chemical_composition"
                and sibling_grid.orientation != grid.orientation
            ):
                continue
            if abs(sibling_grid.n_cols - grid.n_cols) > ROUTE_SIBLING_MAX_COL_DIFF:
                continue
            similarity = token_similarity(tokens, signature_tokens(sibling_grid))
            if similarity > best_similarity:
                best_similarity = similarity
                best_item = sibling_item
        if best_item is None or best_similarity < ROUTE_SIBLING_MIN_SIMILARITY:
            continue
        item.update(
            recipe_id=best_item["recipe_id"],
            version=best_item.get("version"),
            status="sibling",
            score=best_item.get("score") or 0.0,
            confidence=best_item.get("score") or 0.0,
            margin=best_item.get("margin") or 0.0,
            runner_up=best_item.get("runner_up"),
            reasons=[f"same header structure as {best_item.get('table_id')}"],
        )
        filled += 1
    return filled


async def _recipe_catalog(channel: str) -> list[dict]:
    url = f"{settings.recipe_registry_url.rstrip('/')}/internal/recipes"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url)
    except httpx.HTTPError:
        return []
    if response.status_code != 200:
        return []
    catalog: list[dict] = []
    for item in response.json() or []:
        versions = item.get("versions") or []
        version = (item.get("channels") or {}).get(channel)
        if not version and versions:
            version = versions[-1].get("version")
        if item.get("recipe_id") and version:
            catalog.append(
                {"recipe_id": item["recipe_id"], "version": str(version)}
            )
    return catalog


async def _route_with_agent(
    run: Run,
    tables: list[dict],
    deterministic: list[dict],
    catalog: list[dict],
) -> RouteDecision | None:
    task = AgentTask(
        task_id=f"route-{run.id}",
        trace_id=run.trace_id or run.id,
        role="router",
        objective="Assign every table to exactly one recipe from the catalog.",
        inputs={
            "tables": tables,
            "catalog": catalog,
            "deterministic": deterministic,
        },
        budget=AgentBudget(
            max_steps=1, max_tool_calls=0, max_tokens=32000, wall_time_seconds=90
        ),
    )
    url = f"{settings.agent_url.rstrip('/')}/internal/agent:run"
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(url, json=task.model_dump(mode="json"))
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        payload = response.json()
        if payload.get("degraded"):
            return None
        return RouteDecision.model_validate(payload.get("output") or {})
    except ValueError:
        return None


def filter_tables_by_quality(
    tables: list[dict], threshold: float
) -> tuple[list[dict], list[dict]]:
    """Split OCR tables into routable and low-quality buckets."""
    if threshold <= 0:
        return list(tables), []
    kept: list[dict] = []
    filtered: list[dict] = []
    for table in tables:
        quality = float(table.get("quality", 1.0))
        if quality < threshold:
            filtered.append(
                {
                    "table_id": table.get("table_id"),
                    "page_no": table.get("page_no"),
                    "quality": quality,
                    "flags": list(table.get("quality_flags") or []),
                }
            )
            continue
        kept.append(table)
    return kept, filtered


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
    all_tables = data.get("tables") or []
    threshold = float(settings.min_table_quality or 0.0)
    tables, filtered = filter_tables_by_quality(all_tables, threshold)
    if filtered:
        logger.info(
            "run %s filtered %s low-quality table(s) below %.2f",
            run.id,
            len(filtered),
            threshold,
        )
    assignments: list[dict] = []
    pending: list[tuple[dict, dict]] = []
    for table in tables:
        match = await _match_table(table, run.recipe_channel)
        item = {
            "table_id": table.get("table_id"),
            "page_no": table.get("page_no"),
            "recipe_id": match.get("recipe_id"),
            "version": match.get("version"),
            "status": match.get("status"),
            "score": match.get("score"),
            "confidence": match.get("score"),
            "margin": match.get("margin"),
            "runner_up": match.get("runner_up"),
        }
        assignments.append(item)
        if not item["recipe_id"] or float(item["score"] or 0) < ROUTE_LOW_CONFIDENCE:
            pending.append((table, item))

    agent_used = False
    fallback = "generic"
    agent_pending = select_agent_tables(pending)
    if agent_pending and settings.route_agent_enabled:
        catalog = await _recipe_catalog(run.recipe_channel)
        decision = await _route_with_agent(
            run,
            [table for table, _ in agent_pending],
            [item for _, item in agent_pending],
            catalog,
        )
        if decision is not None:
            agent_used = True
            fallback = decision.fallback
            chosen_by_table = {
                str(item.table_id): item for item in decision.assignments
            }
            for table, item in agent_pending:
                chosen = chosen_by_table.get(str(table.get("table_id")))
                if chosen is None or chosen.confidence < ROUTE_AGENT_MIN_CONFIDENCE:
                    continue
                item.update(
                    recipe_id=chosen.recipe_id,
                    version=chosen.version,
                    status="agent",
                    score=chosen.confidence,
                    confidence=chosen.confidence,
                    reasons=chosen.reasons,
                )

    tables_by_id = {
        str(table.get("table_id")): table
        for table in tables
        if table.get("table_id")
    }
    sibling_filled = apply_sibling_fallback(assignments, tables_by_id)
    if sibling_filled:
        logger.info(
            "run %s routed %s table(s) by sibling structure",
            run.id,
            sibling_filled,
        )

    margin_threshold = float(settings.route_margin_threshold or 0.0)
    for item in assignments:
        item["needs_human"] = (
            not item.get("recipe_id")
            or float(item.get("score") or 0) < ROUTE_LOW_CONFIDENCE
            or (
                margin_threshold > 0
                and float(item.get("margin") or 0) < margin_threshold
            )
        )
    needs_human = [
        str(item.get("table_id")) for item in assignments if item["needs_human"]
    ]
    needs_human.extend(
        str(item.get("table_id")) for item in filtered if item.get("table_id")
    )
    if needs_human:
        fallback = "human"
    routed = [item for item in assignments if not item["needs_human"]]
    if not routed:
        raise RoutingStageError(
            "no table matched a recipe with sufficient confidence"
            + (f" ({len(filtered)} low-quality table(s) filtered)" if filtered else "")
        )
    confidence = max((item.get("score") or 0.0 for item in routed), default=0.0)
    return {
        "assignments": routed,
        "fallback": fallback,
        "confidence": round(confidence, 4),
        "needs_human": needs_human,
        "filtered_tables": filtered,
        "agent_used": agent_used,
        "sibling_fallback": sibling_filled,
    }


async def _match_table(table: dict, channel: str = "stable") -> dict:
    url = f"{settings.recipe_registry_url.rstrip('/')}/internal/recipes/match"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                url, json={"table": table, "channel": channel}
            )
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


class ReviewGateError(RuntimeError):
    """Deterministic review rules rejected the run."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.error_code = "REVIEW_FAILED"
        self.run_state = RunState.REVIEW_FAILED


class RoutingStageError(RuntimeError):
    """No table matched a recipe; never fall back to a concrete recipe."""

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.error_code = "UNROUTED"
        self.run_state = RunState.UNROUTED


class OcrStageError(RuntimeError):
    """OCR failure with a stable code; backend outages are not retried."""

    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


async def validate_parser_version(version: str) -> dict:
    """Confirm an immutable parser bundle exists before pinning a run to it."""
    url = (
        f"{settings.recipe_registry_url.rstrip('/')}/internal/assets/parser/"
        f"{settings.parser_asset_id}/versions/{version}"
    )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"recipe registry unavailable: {exc}") from exc
    if response.status_code != 200:
        raise ValueError(f"unknown parser version: {version}")
    return response.json()


def _canary_selected(run_id: str, percent: int) -> bool:
    """Stable hash bucket so the same run always lands on the same side."""
    if percent <= 0:
        return False
    if percent >= 100:
        return True
    bucket = int(hashlib.sha256(run_id.encode("utf-8")).hexdigest()[:8], 16) % 100
    return bucket < percent


def _canary_should_pin(
    run_id: str, percent: int, *, candidate: str | None, stable: str | None
) -> bool:
    if not candidate or candidate == stable:
        return False
    return _canary_selected(run_id, percent)


async def _parser_channels() -> dict:
    url = (
        f"{settings.recipe_registry_url.rstrip('/')}/internal/assets/parser/"
        f"{settings.parser_asset_id}"
    )
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        logger.warning("parser asset registry unavailable: %s", exc)
        return {}
    if response.status_code != 200:
        logger.warning("parser asset registry error %s", response.status_code)
        return {}
    return dict(response.json().get("channels") or {})


async def _maybe_pin_canary_parser(run: Run) -> str | None:
    """P1-07: 按 10% 灰度把本次 run 固定到 candidate 解析引擎。"""
    if settings.table_engine != "candidate" or run.parser_version:
        return None
    channels = await _parser_channels()
    candidate = channels.get("candidate")
    stable = channels.get("stable")
    if not _canary_should_pin(
        run.id,
        settings.table_engine_canary_percent,
        candidate=candidate,
        stable=stable,
    ):
        return None
    run.parser_version = str(candidate)
    return str(candidate)


async def _payload_for_output(result: ExecutionResult, role: str) -> dict:
    item = result.outputs.get(role)
    if item is None:
        return {}
    data = await get_store().get_bytes(item.storage_key)
    payload = json.loads(data)
    return payload if isinstance(payload, dict) else {}


async def _artifact_payload(run_id: str, role: str) -> dict:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Artifact)
            .where(Artifact.run_id == run_id, Artifact.role == role)
            .order_by(Artifact.created_at.desc())
        )
        artifact = result.scalars().first()
    if artifact is None:
        return {}
    data = await get_store().get_bytes(artifact.storage_key)
    payload = json.loads(data)
    return payload if isinstance(payload, dict) else {}


async def _baseline_parser_run(run: Run, candidate_version: str) -> Run | None:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Run)
            .where(
                Run.document_id == run.document_id,
                Run.id != run.id,
                Run.status == RunState.STRUCTURED_READY.value,
                or_(
                    Run.parser_version.is_(None),
                    Run.parser_version != candidate_version,
                ),
            )
            .order_by(Run.finished_at.desc())
        )
        return result.scalars().first()


async def _registry_post(path: str, payload: dict) -> dict:
    url = f"{settings.recipe_registry_url.rstrip('/')}{path}"
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, json=payload)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"recipe registry unavailable: {exc}") from exc
    if response.status_code not in {200, 201}:
        raise RuntimeError(
            f"registry error {response.status_code}: {response.text[:300]}"
        )
    return response.json()


async def _rollback_table_canary(candidate_version: str, run_id: str) -> dict:
    """候选解析引擎出现回退：candidate 指针退回 stable，后续 run 不再灰度。"""
    note = f"table engine canary auto rollback; run={run_id}"
    payload = {"channel": "candidate", "actor": "table-canary", "note": note}
    try:
        ref = await _registry_post(
            f"/internal/assets/parser/{settings.parser_asset_id}/rollback", payload
        )
        stable = (await _parser_channels()).get("stable")
        if stable and ref.get("version") != stable:
            ref = await _registry_post(
                f"/internal/assets/parser/{settings.parser_asset_id}/versions/"
                f"{stable}/promote",
                payload,
            )
        return {"rolled_back": True, "version": str(ref.get("version") or "")}
    except Exception as exc:  # noqa: BLE001 - 回滚失败必须留痕但不能吞掉
        logger.exception("table engine auto rollback failed")
        return {"rolled_back": False, "error": str(exc)[:300]}


async def _evaluate_table_canary(
    run: Run, result: ExecutionResult, candidate_version: str
) -> dict:
    """对比候选引擎与 stable 基线；回退时自动把 candidate 指针退回 stable。"""
    from .shadow import compare_shadow
    from .snapshots import latest_snapshot

    baseline = await _baseline_parser_run(run, candidate_version)
    if baseline is None:
        return {"skipped": "no baseline"}
    baseline_payload = await _artifact_payload(baseline.id, "records")
    baseline_diagnostics = (await _artifact_payload(baseline.id, "diagnostics")).get(
        "diagnostics"
    ) or []
    candidate_payload = await _payload_for_output(result, "records")
    candidate_diagnostics = (await _payload_for_output(result, "diagnostics")).get(
        "diagnostics"
    ) or []
    snapshot = await latest_snapshot(run.document_id)
    metrics = compare_shadow(
        baseline_payload.get("records") or [],
        candidate_payload.get("records") or [],
        snapshot,
        baseline_diagnostics=baseline_diagnostics,
        candidate_diagnostics=candidate_diagnostics,
    )
    detail = {
        "candidate_version": candidate_version,
        "baseline_run_id": baseline.id,
        "canary_percent": settings.table_engine_canary_percent,
        **metrics,
    }
    if not metrics["passed"] and settings.table_engine_auto_rollback:
        detail["rollback"] = await _rollback_table_canary(candidate_version, run.id)
    return detail



async def build_sandbox_request(
    run: Run,
    *,
    recipe_override: RecipeRef | None = None,
    table_id: str | None = None,
    ocr_override: ObjectInput | None = None,
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
    elif isinstance(run.recipe_override, dict):
        override = run.recipe_override
        ref = RecipeRef(
            recipe_id=str(override.get("recipe_id") or ""),
            version=str(
                override.get("candidate_version") or override.get("version") or ""
            ),
            digest=str(override.get("digest") or ""),
        )
        if ref.recipe_id and ref.version:
            assignments = _override_assignments(assignments, ref, table_id)
    if not assignments:
        raise RoutingStageError("no routed tables; refusing to run a fallback recipe")
    primary = assignments[0]
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
        ocr=ocr_override
        or ObjectInput(storage_key=ocr_artifact.storage_key, sha256=ocr_artifact.sha256),
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
        parser=(
            ParserAssetRef(
                asset_id=settings.parser_asset_id,
                version=run.parser_version,
            )
            if run.parser_version
            else None
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
        # 同一 recipe 的所有分表必须保持版本一致，否则沙箱会报
        # SANDBOX_RECIPE_CONFLICT（候选版本与回放表中的旧版本冲突）。
        match = item.recipe_id == override.recipe_id or (
            table_id is not None and item.table_id == table_id
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


def _canonical_bytes(payload) -> bytes:
    return (
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


async def _call_agent_task(task: AgentTask) -> AgentResult | None:
    url = f"{settings.agent_url.rstrip('/')}/internal/agent:run"
    try:
        async with httpx.AsyncClient(timeout=settings.model_fallback_timeout_seconds) as client:
            response = await client.post(url, json=task.model_dump(mode="json"))
    except httpx.HTTPError:
        return None
    if response.status_code != 200:
        return None
    try:
        return AgentResult.model_validate(response.json())
    except ValueError:
        return None


async def _apply_model_fallback(run: Run, result: ExecutionResult) -> dict:
    """Ask the agent for missing prose items and merge only quoted results."""
    from . import model_fallback as fallback

    records_output = result.outputs.get("records")
    evidence_output = result.outputs.get("evidence")
    intelligence_output = result.outputs.get("document_intelligence")
    if records_output is None or evidence_output is None or intelligence_output is None:
        return {
            "schema_version": fallback.SCHEMA_VERSION,
            "enabled": True,
            "triggered": False,
            "status": "skipped",
            "reason": "document_intelligence_artifacts_missing",
        }
    store = get_store()
    records_payload = json.loads(await store.get_bytes(records_output.storage_key))
    records = list(records_payload.get("records") or [])
    evidence_lines = (
        (await store.get_bytes(evidence_output.storage_key))
        .decode("utf-8")
        .splitlines()
    )
    evidence = [json.loads(line) for line in evidence_lines if line.strip()]
    intelligence = json.loads(
        await store.get_bytes(intelligence_output.storage_key)
    )
    async with SessionLocal() as session:
        ocr_artifact = await _latest_artifact(session, run.id, "ocr")
    if ocr_artifact is None:
        return {
            "schema_version": fallback.SCHEMA_VERSION,
            "enabled": True,
            "triggered": False,
            "status": "skipped",
            "reason": "ocr_missing",
        }
    ocr_payload = json.loads(await store.get_bytes(ocr_artifact.storage_key))
    reasons = fallback.should_trigger(
        intelligence, [item.model_dump(mode="json") for item in result.diagnostics]
    )
    report: dict = {
        "schema_version": fallback.SCHEMA_VERSION,
        "enabled": True,
        "triggered": bool(reasons),
        "reasons": reasons,
        "status": "skipped",
        "accepted": [],
        "rejected": [],
        "records_added": 0,
    }
    if not reasons:
        return report
    text = fallback.document_text(ocr_payload)
    task = AgentTask.model_validate(
        fallback.build_task(
            run.id,
            run.trace_id,
            text,
            intelligence,
            records,
            max_items=settings.model_fallback_max_items,
            token_budget=settings.model_fallback_token_budget,
        )
    )
    report["task_id"] = task.task_id
    agent_result = await _call_agent_task(task)
    if agent_result is None:
        report["status"] = "failed"
        report["error"] = "agent_unavailable"
        return report
    report["prompt_id"] = agent_result.prompt_id
    report["usage"] = agent_result.usage.model_dump()
    if agent_result.status != "completed" or agent_result.degraded:
        report["status"] = "failed"
        report["error"] = agent_result.error_code or "agent_not_completed"
        return report
    accepted, rejected = fallback.validate_proposals(
        agent_result.output.get("items"),
        text,
        fallback.existing_features(records, intelligence),
        max_items=settings.model_fallback_max_items,
    )
    report["accepted"] = accepted
    report["rejected"] = rejected
    if not accepted:
        report["status"] = "rejected"
        return report
    merged_records, merged_evidence, added = fallback.merge_proposals(
        records, evidence, accepted
    )
    records_bytes = _canonical_bytes(
        {"schema_version": "sandbox-records/1", "records": merged_records}
    )
    evidence_bytes = "".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for item in merged_evidence
    ).encode("utf-8")
    await store.put_bytes(records_output.storage_key, records_bytes, "application/json")
    await store.put_bytes(
        evidence_output.storage_key, evidence_bytes, "application/x-ndjson"
    )
    records_output.sha256 = hashlib.sha256(records_bytes).hexdigest()
    records_output.bytes = len(records_bytes)
    evidence_output.sha256 = hashlib.sha256(evidence_bytes).hexdigest()
    evidence_output.bytes = len(evidence_bytes)
    manifest_output = result.outputs.get("manifest")
    if manifest_output is not None:
        try:
            manifest_payload = json.loads(
                await store.get_bytes(manifest_output.storage_key)
            )
            if isinstance(manifest_payload, dict):
                outputs = manifest_payload.setdefault("outputs", {})
                outputs["records.json"] = records_output.sha256
                outputs["evidence.jsonl"] = evidence_output.sha256
                manifest_bytes = _canonical_bytes(manifest_payload)
                await store.put_bytes(
                    manifest_output.storage_key, manifest_bytes, "application/json"
                )
                manifest_output.sha256 = hashlib.sha256(manifest_bytes).hexdigest()
                manifest_output.bytes = len(manifest_bytes)
        except Exception:  # noqa: BLE001 - report still records the merge
            logger.warning("failed to refresh manifest after model fallback", exc_info=True)
    report["status"] = "accepted"
    report["records_added"] = len(added)
    return report


async def _persist_model_fallback_artifact(run: Run, report: dict) -> None:
    task_id = str(report.get("task_id") or "report")
    key = f"runs/{run.id}/model_fallback/{task_id}.json"
    data = _canonical_bytes(report)
    store = get_store()
    await store.put_bytes(key, data, "application/json")
    async with SessionLocal() as session:
        row = await session.get(Run, run.id)
        if row is None:
            return
        session.add(
            Artifact(
                run_id=run.id,
                role="model_fallback",
                storage_key=key,
                sha256=hashlib.sha256(data).hexdigest(),
                bytes=len(data),
            )
        )
        await append_event(
            session,
            row,
            "artifact.created",
            row.stage,
            "completed",
            {
                "role": "model_fallback",
                "storage_key": key,
                "status": report.get("status"),
                "records_added": report.get("records_added", 0),
            },
        )
        await session.commit()


async def _sandbox_stage(run: Run) -> dict:
    canary_version = await _maybe_pin_canary_parser(run)
    request = await build_sandbox_request(run)
    result = await _call_sandbox(request)
    if result.status != "succeeded":
        raise SandboxStageError(
            result.error_code or "SANDBOX_FAILED",
            result.error_message or f"sandbox finished with status {result.status}",
        )
    fallback_report = None
    if settings.model_fallback_enabled:
        try:
            fallback_report = await _apply_model_fallback(run, result)
        except Exception as exc:  # noqa: BLE001 - fallback must never break parsing
            logger.exception("model fallback failed for run %s", run.id)
            fallback_report = {
                "schema_version": "document-model-fallback/1",
                "enabled": True,
                "triggered": False,
                "status": "failed",
                "error": str(exc)[:300],
            }
    artifacts = await _record_sandbox_artifacts(run, result)
    if fallback_report is not None:
        await _persist_model_fallback_artifact(run, fallback_report)
    canary_detail = None
    if canary_version:
        try:
            canary_detail = await _evaluate_table_canary(run, result, canary_version)
        except Exception as exc:  # noqa: BLE001 - 灰度对比失败不影响主链路
            logger.exception("table engine canary comparison failed")
            canary_detail = {"error": str(exc)[:300]}
        await _persist_canary_event(run.id, canary_detail)
    return {
        "status": result.status,
        "result_key": artifacts.get("result", ""),
        "output_refs": {"artifacts": artifacts},
        "outputs": {role: item.storage_key for role, item in result.outputs.items()},
        "metrics": result.metrics.model_dump(mode="json"),
        "diagnostics": [item.model_dump(mode="json") for item in result.diagnostics],
        "table_engine": canary_detail,
    }


async def _persist_canary_event(run_id: str, detail: dict) -> None:
    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        if run is None:
            return
        await append_event(
            session,
            run,
            "run.table_engine.canary",
            run.stage,
            "completed",
            detail,
        )
        await session.commit()


async def _cross_standard_source(
    document_id: str,
) -> dict:
    """Load the latest parsed/OCR artifacts of one referenced standard."""
    from . import library

    async with SessionLocal() as session:
        runs = (
            await session.execute(
                select(Run)
                .where(Run.document_id == document_id)
                .order_by(Run.created_at.desc())
            )
        ).scalars().all()
        chosen = None
        artifact_rows: dict[str, Artifact] = {}
        for candidate in runs:
            artifacts = (
                await session.execute(
                    select(Artifact).where(Artifact.run_id == candidate.id)
                )
            ).scalars().all()
            roles = {item.role for item in artifacts}
            if "ocr" not in roles:
                continue
            chosen = candidate
            for item in artifacts:
                artifact_rows.setdefault(item.role, item)
            if "records" in roles:
                break
        if chosen is None:
            return {"document_id": document_id, "status": "missing", "text": ""}
        store = get_store()

        async def _payload(role: str) -> dict:
            artifact = artifact_rows.get(role)
            if artifact is None:
                return {}
            try:
                return json.loads(await store.get_bytes(artifact.storage_key))
            except Exception:  # noqa: BLE001 - a broken source must not break the run
                return {}

        async def _lines(role: str) -> list[dict]:
            artifact = artifact_rows.get(role)
            if artifact is None:
                return []
            try:
                raw = (await store.get_bytes(artifact.storage_key)).decode("utf-8")
            except Exception:  # noqa: BLE001
                return []
            return [json.loads(line) for line in raw.splitlines() if line.strip()]

        ocr = await _payload("ocr")
        pages = [
            {
                "page_no": int(page.get("page_no") or index + 1),
                "markdown": str(page.get("markdown") or ""),
            }
            for index, page in enumerate(ocr.get("pages") or [])
            if isinstance(page, dict)
        ]
        text = str(ocr.get("markdown") or "")
        if not text:
            text = "\n".join(page["markdown"] for page in pages)
        records = (await _payload("records")).get("records") or []
        inventory = await _payload("inventory")
        evidence = await _lines("evidence")
        result = await _payload("result")
        clauses = await _payload("clauses")
        status = "parsed" if "records" in artifact_rows else "ocr_ready"
        if records:
            try:
                async with SessionLocal() as session:
                    await library.refresh_from_run(
                        session,
                        chosen,
                        references=await _payload("references"),
                        records=records,
                        page_count=len(ocr.get("pages") or []),
                    )
            except Exception:  # noqa: BLE001 - index refresh is best effort
                logger.warning("failed to refresh library index for %s", chosen.id, exc_info=True)
        return {
            "document_id": document_id,
            "run_id": chosen.id,
            "status": status,
            "records": records,
            "inventory": inventory,
            "evidence": evidence,
            "result": result,
            "clauses": clauses,
            "pages": pages,
            "text": text,
            "page_count": len(ocr.get("pages") or []),
        }


async def _cross_standard_stage(run: Run) -> dict:
    """Resolve content references against the library and merge expansions."""
    from . import cross_standard, library

    report: dict = {
        "schema_version": cross_standard.SCHEMA_VERSION,
        "enabled": bool(settings.cross_standard_enabled),
        "tasks": [],
        "stats": {},
        "agent": {},
    }
    if not settings.cross_standard_enabled:
        return report
    async with SessionLocal() as session:
        references_artifact = await _latest_artifact(session, run.id, "references")
        records_artifact = await _latest_artifact(session, run.id, "records")
        evidence_artifact = await _latest_artifact(session, run.id, "evidence")
        ocr_artifact = await _latest_artifact(session, run.id, "ocr")
        if references_artifact is None or records_artifact is None:
            report["stats"] = {"tasks": 0}
            return report
        references = json.loads(
            await get_store().get_bytes(references_artifact.storage_key)
        )
        records = (
            json.loads(await get_store().get_bytes(records_artifact.storage_key))
        ).get("records") or []
        evidence = [
            json.loads(line)
            for line in (
                await get_store().get_bytes(evidence_artifact.storage_key)
            ).decode("utf-8").splitlines()
            if line.strip()
        ] if evidence_artifact else []
        ocr = (
            json.loads(await get_store().get_bytes(ocr_artifact.storage_key))
            if ocr_artifact else {}
        )
        library_rows = list((await library.ensure_index(session)).values())
    candidates = references.get("cross_standard_candidates") or []
    tasks = cross_standard.resolve_tasks(candidates, library_rows, records)
    tasks = tasks[: settings.cross_standard_max_tasks]
    sources: dict[str, dict] = {}
    expanded_tasks: list[dict] = []
    imported: list[dict] = []
    for task in tasks:
        resolution = task.get("resolution") or {}
        document_id = str(resolution.get("document_id") or "")
        if not document_id:
            expanded_tasks.append(task)
            continue
        if document_id == run.document_id:
            task["status"] = "skipped"
            task["gap"] = "被引标准与当前文档相同"
            expanded_tasks.append(task)
            continue
        if document_id not in sources:
            if len(sources) >= settings.cross_standard_max_sources:
                task["status"] = "skipped"
                task["gap"] = "超过来源数量预算"
                expanded_tasks.append(task)
                continue
            sources[document_id] = await _cross_standard_source(document_id)
        source = sources[document_id]
        if source["status"] == "missing":
            task["status"] = "needs_source"
            task["gap"] = "来源文档尚无 OCR 产物"
            expanded_tasks.append(task)
            continue
        outcome = (
            cross_standard.expand_deterministic(
                task,
                records,
                evidence,
                source.get("records") or [],
                source.get("inventory") or {},
                source.get("evidence") or [],
            )
            if task.get("status") == "resolved"
            else {"status": task.get("status"), "reason": ""}
        )
        if outcome.get("status") == "expanded":
            records, evidence, added = cross_standard.apply_proposals(
                records, evidence, task, outcome.get("proposals") or []
            )
            task["status"] = "expanded"
            task["expansion"] = {
                "records_added": len(added),
                "properties_added": len(
                    [
                        item
                        for item in outcome.get("proposals") or []
                        if item.get("kind") == "property"
                    ]
                ),
                "conflicts": outcome.get("conflicts") or [],
            }
            imported.append(
                {"task_id": task.get("task_id"), "record_ids": added}
            )
        elif outcome.get("status") in {"skipped", "conflict"}:
            task["status"] = outcome["status"]
            task["gap"] = outcome.get("reason") or ""
            if outcome.get("conflicts"):
                task["expansion"] = {"conflicts": outcome["conflicts"]}
        else:
            task["status"] = outcome.get("status") or task.get("status")
        expanded_tasks.append(task)
    # Agent fallback for parameter/text-only tasks.
    agent_report: dict = {"status": "skipped"}
    pending = [
        task
        for task in expanded_tasks
        if task.get("status") in {"needs_agent", "resolved"}
        and task.get("resolution")
    ]
    if pending and settings.cross_standard_agent_enabled:
        task_payload = cross_standard.build_agent_task(
            pending,
            run_id=run.id,
            trace_id=run.trace_id,
            max_items=settings.cross_standard_agent_max_items,
        )
        if task_payload is not None:
            agent_report["status"] = "requested"
            try:
                agent_task = AgentTask.model_validate(task_payload)
                result = await _call_agent_task(agent_task)
                if result is None:
                    agent_report["status"] = "unavailable"
                elif result.status != "completed" or result.degraded:
                    agent_report["status"] = "failed"
                    agent_report["error"] = result.error_code or "agent_not_completed"
                else:
                    source_texts = {
                        document_id: (source.get("text") or "")
                        for document_id, source in sources.items()
                    }
                    accepted, rejected = cross_standard.validate_agent_items(
                        result.output.get("items"), expanded_tasks, source_texts
                    )
                    if accepted:
                        records, evidence, summary = cross_standard.apply_agent_items(
                            expanded_tasks, records, evidence, accepted
                        )
                        agent_report["accepted"] = len(accepted)
                        agent_report["imported"] = summary.get("imported", 0)
                        for item in accepted:
                            for task in expanded_tasks:
                                if task.get("task_id") == item["task_id"]:
                                    task["status"] = "expanded"
                                    task["expansion"] = {
                                        **(task.get("expansion") or {}),
                                        "agent": True,
                                    }
                    agent_report["rejected"] = rejected
                    agent_report["status"] = "completed"
            except Exception as exc:  # noqa: BLE001 - agent is best effort
                logger.warning("cross-standard agent failed", exc_info=True)
                agent_report["status"] = "failed"
                agent_report["error"] = str(exc)[:300]
    for task in expanded_tasks:
        task.pop("_expanded", None)
    stats = cross_standard.summarize(expanded_tasks)
    stats["records_added"] = sum(
        len(item.get("record_ids") or []) for item in imported
    )
    stats["properties_added"] = sum(
        int((task.get("expansion") or {}).get("properties_added") or 0)
        for task in expanded_tasks
    ) + int(agent_report.get("imported") or 0)
    report.update(
        {
            "tasks": expanded_tasks,
            "stats": stats,
            "agent": agent_report,
            "imported": imported,
        }
    )
    if imported or any(task.get("status") == "expanded" for task in expanded_tasks):
        await _persist_cross_standard_merge(run, records, evidence)
    async with SessionLocal() as session:
        try:
            await library.refresh_from_run(
                session,
                run,
                references=references,
                records=records,
                page_count=len(ocr.get("pages") or []),
            )
        except Exception:  # noqa: BLE001 - index refresh is best effort
            logger.warning("failed to refresh library index", exc_info=True)
    return report


async def _persist_cross_standard_merge(
    run: Run, records: list[dict], evidence: list[dict]
) -> None:
    """Rewrite the sandbox records/evidence artifacts after expansion."""
    records_bytes = _canonical_bytes(
        {"schema_version": "sandbox-records/1", "records": records}
    )
    evidence_bytes = "".join(
        json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
        for item in evidence
    ).encode("utf-8")
    store = get_store()
    async with SessionLocal() as session:
        records_artifact = await _latest_artifact(session, run.id, "records")
        evidence_artifact = await _latest_artifact(session, run.id, "evidence")
        manifest_artifact = await _latest_artifact(session, run.id, "manifest")
        if records_artifact is None or evidence_artifact is None:
            return
        await store.put_bytes(
            records_artifact.storage_key, records_bytes, "application/json"
        )
        await store.put_bytes(
            evidence_artifact.storage_key, evidence_bytes, "application/x-ndjson"
        )
        records_artifact.sha256 = hashlib.sha256(records_bytes).hexdigest()
        records_artifact.bytes = len(records_bytes)
        evidence_artifact.sha256 = hashlib.sha256(evidence_bytes).hexdigest()
        evidence_artifact.bytes = len(evidence_bytes)
        if manifest_artifact is not None:
            try:
                manifest_payload = json.loads(
                    await store.get_bytes(manifest_artifact.storage_key)
                )
            except Exception:  # noqa: BLE001
                manifest_payload = None
            if isinstance(manifest_payload, dict):
                outputs = manifest_payload.setdefault("outputs", {})
                outputs["records.json"] = records_artifact.sha256
                outputs["evidence.jsonl"] = evidence_artifact.sha256
                manifest_bytes = _canonical_bytes(manifest_payload)
                await store.put_bytes(
                    manifest_artifact.storage_key, manifest_bytes, "application/json"
                )
                manifest_artifact.sha256 = hashlib.sha256(manifest_bytes).hexdigest()
                manifest_artifact.bytes = len(manifest_bytes)
        await session.commit()


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
            await append_event(
                session,
                run,
                "artifact.created",
                run.stage,
                "completed",
                {
                    "role": role,
                    "storage_key": item.storage_key,
                    "sha256": item.sha256,
                    "bytes": item.bytes,
                },
            )
        await session.commit()
    return keys


async def _fake_sandbox(_: Run) -> dict:
    return {
        "simulated": True,
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
        ocr_artifact = await _latest_artifact(session, run.id, "ocr")
        diagnostics_artifact = await _latest_artifact(session, run.id, "diagnostics")
        intelligence_artifact = await _latest_artifact(
            session, run.id, "document_intelligence"
        )
        inventory_artifact = await _latest_artifact(session, run.id, "inventory")
        references_artifact = await _latest_artifact(session, run.id, "references")
        override_artifact = await _latest_artifact(
            session, run.id, "metadata_override"
        )
    if records_artifact is None:
        raise RuntimeError(f"records artifact missing for run {run.id}")
    if evidence_artifact is None:
        raise RuntimeError(f"evidence artifact missing for run {run.id}")
    records_payload = json.loads(await get_store().get_bytes(records_artifact.storage_key))
    records = records_payload.get("records") or []
    if override_artifact is not None:
        # 反馈修复的文档级元数据覆盖：只填空值，不改已有取值。
        from .feedback.document_repair import apply_metadata_override

        override = json.loads(await get_store().get_bytes(override_artifact.storage_key))
        filled = apply_metadata_override(records, override)
        if filled:
            data = _canonical_bytes(
                {"schema_version": "sandbox-records/1", "records": records}
            )
            digest = hashlib.sha256(data).hexdigest()
            key = f"runs/{run.id}/review/records-{digest[:12]}.json"
            await get_store().put_bytes(key, data, "application/json")
            async with SessionLocal() as session:
                session.add(
                    Artifact(
                        run_id=run.id,
                        role="records",
                        storage_key=key,
                        sha256=digest,
                        bytes=len(data),
                    )
                )
                await session.commit()
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
    pages = 0
    if ocr_artifact is not None:
        ocr_payload = json.loads(await get_store().get_bytes(ocr_artifact.storage_key))
        pages = len(ocr_payload.get("pages") or [])
    diagnostics: list[dict] = []
    if diagnostics_artifact is not None:
        diagnostics_payload = json.loads(
            await get_store().get_bytes(diagnostics_artifact.storage_key)
        )
        diagnostics = diagnostics_payload.get("diagnostics") or []

    async def _artifact_object(artifact) -> dict:
        if artifact is None:
            return {}
        payload = json.loads(await get_store().get_bytes(artifact.storage_key))
        return payload if isinstance(payload, dict) else {}

    request = ReviewRequest(
        run_id=run.id,
        trace_id=run.trace_id,
        records=records,
        evidence=evidence,
        tables=result.get("tables") or [],
        template=result.get("template") or {},
        pages=pages,
        diagnostics=diagnostics,
        document_intelligence=await _artifact_object(intelligence_artifact),
        inventory=await _artifact_object(inventory_artifact),
        references=await _artifact_object(references_artifact),
    )
    report = await _call_review(request)
    await _persist_review(run, report)
    if not records and any(
        item.rule_id == "DOC-NO-APPLICABLE-TABLES" for item in report.findings
    ):
        # 没有可产出记录的表：转 UNROUTED，而不是“解析失败/待人工修复”。
        raise RoutingStageError("no applicable record table; nothing to parse")
    await _auto_feedback(run, report)
    if report.status == "fail":
        errors = int((report.stats or {}).get("deterministic_errors") or 0)
        raise ReviewGateError(
            f"review gate failed with {errors} deterministic error(s)"
        )
    return report.model_dump(mode="json")


async def _auto_feedback(run: Run, report: ReviewReport) -> None:
    """文档级门禁命中后自动创建 feedback，失败不影响 review 结果落盘。"""
    actionable = [
        item
        for item in report.findings
        if str(item.rule_id).startswith("DOC-") and item.severity != "info"
    ]
    if not actionable:
        return
    try:
        from .feedback.service import FeedbackService

        created = await FeedbackService().create_from_review(
            run.id, run.document_id, actionable
        )
        logger.info("run %s auto-created %s feedback item(s)", run.id, len(created))
    except Exception:
        logger.exception("failed to auto-create feedback for run %s", run.id)


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
                        message=finding.message,
                        rule_id=str(finding.rule_id or ""),
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
        "simulated": True,
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
            if settings.human_review_required:
                ensure_transition(run.status, RunState.HUMAN_REVIEW)
                run.status = RunState.HUMAN_REVIEW.value
                run.stage = RunState.HUMAN_REVIEW.value
                run.progress = max(int(run.progress or 0), 95)
                run.finished_at = None
                await append_event(
                    session,
                    run,
                    "run.human_review_required",
                    RunState.HUMAN_REVIEW.value,
                    "waiting",
                    {"actor": "system"},
                )
                await session.commit()
                return
            ensure_transition(run.status, RunState.STRUCTURED_READY)
            run.status = RunState.STRUCTURED_READY.value
            run.stage = RunState.STRUCTURED_READY.value
            run.progress = 100
            run.finished_at = now()
            result = await session.execute(
                select(Artifact)
                .where(Artifact.run_id == run.id, Artifact.role == "result")
                .order_by(Artifact.created_at.desc())
            )
            artifact = result.scalars().first()
            run.result_key = artifact.storage_key if artifact else None
            await append_event(
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
        await append_event(
            session,
            run,
            "run.cancelled",
            RunState.CANCELLED.value,
            "cancelled",
            {},
        )
        await session.commit()


async def _mark_terminal(
    run_id: str, state: RunState, error_code: str, detail: str
) -> None:
    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        if run is None or is_terminal(run.status):
            return
        run.status = state.value
        run.stage = state.value
        run.error_code = error_code
        run.finished_at = now()
        await append_event(
            session,
            run,
            "run.failed",
            state.value,
            "failed",
            {"error_code": error_code, "detail": detail[:1000]},
        )
        await session.commit()


async def _maybe_adapt_edition(run_id: str) -> None:
    """P1-12/Phase 2: compare the document against its edition profile.

    Runs between routing and sandbox.  Adaptation is advisory: any failure is
    downgraded to a warning so it can never block parsing.
    """
    if not settings.edition_profile_enabled:
        return
    try:
        await _adapt_edition(run_id)
    except Exception as exc:  # noqa: BLE001 - advisory stage
        logger.warning("edition adaptation skipped for %s: %s", run_id, exc)


async def _adapt_edition(run_id: str) -> None:
    from services.adaptation import (
        AdaptationController,
        AdaptationLevel,
        DriftAnalyzer,
        EditionStore,
    )
    from services.adaptation.candidate import (
        build_code_candidate,
        build_recipe_candidate,
        save_candidate,
    )
    from services.adaptation.profile import resolve_standard

    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        if run is None:
            return
        document = await session.get(Document, run.document_id)
        if document is None:
            return
        ocr_artifact = (
            await session.execute(
                select(Artifact).where(
                    Artifact.run_id == run_id, Artifact.role == "ocr"
                )
            )
        ).scalars().first()
        routing_artifact = (
            await session.execute(
                select(Artifact).where(
                    Artifact.run_id == run_id, Artifact.role == "routing"
                )
            )
        ).scalars().first()
    resolved = resolve_standard(document.filename)
    if resolved is None or ocr_artifact is None:
        return
    standard_id, edition = resolved
    ocr = json.loads(await get_store().get_bytes(ocr_artifact.storage_key))
    pins: dict[str, str] = {}
    if routing_artifact is not None:
        routing = json.loads(await get_store().get_bytes(routing_artifact.storage_key))
        for item in routing.get("assignments") or []:
            recipe_id = str(item.get("recipe_id") or "")
            version = str(item.get("version") or "")
            if recipe_id and version:
                pins.setdefault(recipe_id, version)
    root = (
        Path(settings.edition_profile_dir)
        if settings.edition_profile_dir
        else Path(__file__).resolve().parent / "data" / "editions"
    )
    store = EditionStore(root)
    profile = store.get(standard_id, edition)
    if profile is None:
        store.save(
            store.build(
                standard_id,
                edition,
                ocr,
                sample_doc_id=document.id,
                recipe_pins=pins,
            )
        )
        await _record_edition_event(
            run_id,
            {
                "standard_id": standard_id,
                "edition": edition,
                "level": AdaptationLevel.L0_NONE.value,
                "reasons": ["profile_created"],
                "candidate_path": "",
            },
        )
        return
    report = DriftAnalyzer().compare(profile, ocr)
    controller = AdaptationController(store)
    plan = controller.plan(report)
    candidate_path = ""
    if plan.level == AdaptationLevel.L1_PROFILE_PATCH:
        controller.apply_l1(profile, report, ocr)
    elif plan.level in {
        AdaptationLevel.L2_RECIPE_CANDIDATE,
        AdaptationLevel.L3_CODE_CANDIDATE,
    }:
        base = (
            _base_recipe_manifest(pins)
            if plan.level == AdaptationLevel.L2_RECIPE_CANDIDATE
            else None
        )
        if plan.level == AdaptationLevel.L2_RECIPE_CANDIDATE and base is not None:
            candidate = build_recipe_candidate(standard_id, edition, base, report)
        else:
            candidate = build_code_candidate(standard_id, edition, report)
        candidate_path = str(save_candidate(candidate, root / "candidates"))
    await _record_edition_event(
        run_id,
        {
            "standard_id": standard_id,
            "edition": edition,
            "level": plan.level.value,
            "reasons": plan.reasons,
            "expected_tables": report.expected_tables,
            "matched_tables": report.matched_tables,
            "drift_count": len(report.drifts),
            "candidate_path": candidate_path,
            "requires_human": plan.requires_human,
        },
    )


def _base_recipe_manifest(pins: dict[str, str]) -> dict | None:
    recipes_root = (
        Path(__file__).resolve().parents[1] / "recipe_registry" / "data" / "recipes"
    )
    for recipe_id, version in pins.items():
        path = recipes_root / recipe_id / version / "manifest.json"
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    return None


async def _record_edition_event(run_id: str, payload: dict) -> None:
    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        if run is None:
            return
        await append_event(
            session,
            run,
            "run.edition.adaptation",
            run.stage,
            "completed",
            payload,
        )
        await session.commit()


async def run_workflow(run_id: str, skip_ocr: bool = False) -> None:
    try:
        if skip_ocr:
            async with SessionLocal() as session:
                run = await session.get(Run, run_id)
                if run is None:
                    return
                ensure_transition(run.status, RunState.OCR_RUNNING)
                run.status = RunState.OCR_RUNNING.value
                run.stage = RunState.OCR_RUNNING.value
                ensure_transition(run.status, RunState.OCR_DONE)
                run.status = RunState.OCR_DONE.value
                run.stage = RunState.OCR_DONE.value
                await append_event(
                    session,
                    run,
                    "run.ocr.reused",
                    RunState.OCR_DONE.value,
                    "completed",
                    {"source": "previous run"},
                )
                await session.commit()
        else:
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
        await _maybe_adapt_edition(run_id)
        repair_attempts = 0
        while True:
            await _execute_stage(
                run_id,
                "sandbox",
                RunState.SANDBOX_RUNNING,
                RunState.PARSED,
                None,
                _fake_sandbox if settings.sandbox_use_fake else _sandbox_stage,
                force=repair_attempts > 0,
            )
            await _execute_stage(
                run_id,
                "cross_standard",
                RunState.PARSED,
                RunState.PARSED,
                "cross_standard",
                _cross_standard_stage,
                # PARSED 既是运行态也是完成态；force 绕过“已完成即跳过”的检查。
                force=True,
            )
            try:
                review_output = await _execute_stage(
                    run_id,
                    "review",
                    RunState.REVIEWING,
                    RunState.REVIEW_PASSED,
                    "review",
                    _fake_review if settings.review_use_fake else _review_stage,
                    force=repair_attempts > 0,
                )
            except ReviewGateError:
                if (
                    not settings.auto_repair_enabled
                    or repair_attempts >= settings.auto_repair_max_attempts
                ):
                    raise
                repaired = await _auto_repair(run_id)
                if not repaired:
                    raise
                repair_attempts += 1
                continue
            if (
                review_output.get("status") == "warn"
                and settings.auto_repair_enabled
                and repair_attempts < settings.auto_repair_max_attempts
            ):
                repaired = await _auto_repair(run_id)
                if repaired:
                    repair_attempts += 1
                    continue
            break
        await _finalize(run_id)
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        logger.exception("run %s workflow failed", run_id)
        state = getattr(exc, "run_state", RunState.FAILED)
        await _mark_terminal(
            run_id, state, getattr(exc, "error_code", "INTERNAL"), str(exc)
        )


async def _repair_budget_used(run_id: str) -> tuple[int, float]:
    """累计该 run 已消耗的自动修复预算（token / 秒）。"""
    async with SessionLocal() as session:
        result = await session.execute(
            select(RunEvent.payload).where(
                RunEvent.run_id == run_id,
                RunEvent.type == "run.repair.completed",
            )
        )
        tokens = 0
        seconds = 0.0
        for payload in result.scalars():
            item = payload or {}
            tokens += int(item.get("tokens_used") or 0)
            seconds += float(item.get("wall_time_seconds") or 0.0)
        return tokens, seconds


async def _record_repair_usage(
    run_id: str, processed: int, verified: int, tokens: int, seconds: float
) -> None:
    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        if run is None:
            return
        await append_event(
            session,
            run,
            "run.repair.completed",
            run.stage,
            "completed",
            {
                "processed": processed,
                "verified": verified,
                "tokens_used": tokens,
                "wall_time_seconds": round(seconds, 3),
            },
        )
        await session.commit()


async def _auto_repair(run_id: str) -> bool:
    """Run open feedback through repair; queue a sandbox reparse on success."""
    from .feedback.service import FeedbackService

    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        if run is None or run.status not in {
            RunState.REVIEWING.value,
            RunState.REVIEW_PASSED.value,
        }:
            return False
        original_status = run.status
        ensure_transition(run.status, RunState.REPAIRING)
        run.status = RunState.REPAIRING.value
        run.stage = RunState.REPAIRING.value
        result = await session.execute(
            select(Feedback.id)
            .where(Feedback.run_id == run_id, Feedback.status == "open")
            .order_by(Feedback.created_at.asc())
        )
        feedback_ids = [str(item) for item in result.scalars()]
        await append_event(
            session,
            run,
            "run.repair.started",
            RunState.REPAIRING.value,
            "started",
            {"feedback_ids": feedback_ids[:10], "count": len(feedback_ids)},
        )
        await session.commit()

    if not feedback_ids:
        await _restore_repair_status(run_id, original_status, "no open feedback")
        return False
    if not settings.auto_feedback_enabled:
        await _restore_repair_status(run_id, original_status, "auto feedback disabled")
        return False

    used_tokens, used_seconds = await _repair_budget_used(run_id)
    if (
        used_tokens >= settings.auto_feedback_token_budget
        or used_seconds >= settings.auto_feedback_wall_time_seconds
    ):
        await _restore_repair_status(run_id, original_status, "auto repair budget exhausted")
        return False

    service = FeedbackService()
    candidate = None
    processed = 0
    verified = 0
    tokens_used = 0
    started = time.monotonic()
    selected = feedback_ids[: max(1, settings.auto_feedback_max_items)]
    for feedback_id in selected:
        elapsed = time.monotonic() - started
        remaining_tokens = (
            settings.auto_feedback_token_budget - used_tokens - tokens_used
        )
        remaining_seconds = (
            settings.auto_feedback_wall_time_seconds - used_seconds - elapsed
        )
        if remaining_tokens < 1024 or remaining_seconds <= 0:
            logger.info(
                "run %s auto repair budget exhausted after %s item(s)",
                run_id,
                processed,
            )
            break
        budget = AgentBudget(
            max_tokens=max(1024, remaining_tokens),
            wall_time_seconds=max(
                1.0, min(settings.feedback_timeout_seconds, remaining_seconds)
            ),
        )
        try:
            detail = await service.process(feedback_id, budget=budget)
        except Exception:
            logger.exception("auto repair failed for feedback %s", feedback_id)
            continue
        usage = service.last_usage
        tokens_used += int(usage.get("tokens") or 0)
        processed += 1
        if detail.status in {"verified", "promoted"}:
            verified += 1
        if detail.status == "verified" and detail.candidate is not None:
            candidate = detail.candidate
            break
    await _record_repair_usage(
        run_id, processed, verified, tokens_used, time.monotonic() - started
    )
    if candidate is None:
        await _restore_repair_status(run_id, original_status, "no verified candidate")
        return False

    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        if run is None:
            return False
        ensure_transition(run.status, RunState.REPARSING)
        run.status = RunState.REPARSING.value
        run.stage = RunState.REPARSING.value
        run.recipe_override = candidate.model_dump(mode="json")
        run.repair_attempt = int(run.repair_attempt or 0) + 1
        await append_event(
            session,
            run,
            "run.repair.reparsing",
            RunState.REPARSING.value,
            "started",
            {
                "attempt": run.repair_attempt,
                "candidate": run.recipe_override,
            },
        )
        await session.commit()
    return True


async def _restore_repair_status(
    run_id: str, original_status: str, reason: str
) -> None:
    async with SessionLocal() as session:
        run = await session.get(Run, run_id)
        if run is None or run.status != RunState.REPAIRING.value:
            return
        target = RunState(original_status)
        ensure_transition(RunState.REPAIRING, target)
        run.status = target.value
        run.stage = target.value
        await append_event(
            session,
            run,
            "run.repair.skipped",
            target.value,
            "skipped",
            {"reason": reason},
        )
        await session.commit()


def schedule(run_id: str, skip_ocr: bool = False) -> None:
    current = _tasks.get(run_id)
    if current is not None and not current.done():
        return
    task = asyncio.create_task(run_workflow(run_id, skip_ocr=skip_ocr))
    _tasks[run_id] = task

    def _cleanup(_: asyncio.Task[None]) -> None:
        _tasks.pop(run_id, None)

    task.add_done_callback(_cleanup)


async def resume_incomplete_runs() -> int:
    terminal = [state.value for state in TERMINAL_STATES]
    # HUMAN_REVIEW / HUMAN_APPROVED 是“等待人工”的驻留状态，不是中断；
    # 重启时不能重新调度，否则会被当成未完成 run 再跑一遍并失败。
    human_waiting = [
        RunState.HUMAN_REVIEW.value,
        RunState.HUMAN_APPROVED.value,
    ]
    async with SessionLocal() as session:
        result = await session.execute(
            select(Run).where(
                Run.status.notin_(terminal),
                Run.status.notin_(human_waiting),
            )
        )
        runs = list(result.scalars())
    for run in runs:
        schedule(run.id)
    return len(runs)
