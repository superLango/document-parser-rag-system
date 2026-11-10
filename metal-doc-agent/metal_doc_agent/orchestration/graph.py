"""Fixed-trunk orchestration graph (M3.1-01/05).

LangGraph is not a dependency of this project; this module implements the same
semantics the plan asks for — typed nodes, conditional edges, bounded step
count, checkpoint after every node and resume from the checkpointed stage.
There is no open ReAct loop: every node is a plain function and the graph edges
are declared statically.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..contracts import TableGrid
from ..pipeline import PipelineResult
from ..queues import QueueStore
from ..recipes import decide_route, doc_queue, load_recipes
from ..settings import Settings
from .context import assemble_context, compact_context, context_regression
from .repair import OCR_QUALITY_FLOOR, decide_repair
from .state import OrchestrationState, RouteInfo, StepError, StepRecord
from .tools import PipelineTools

TERMINALS = {"publish", "human", "fail"}
NodeResult = str | tuple[str, dict[str, Any]] | None
NodeFn = Callable[[OrchestrationState, "NodeContext"], NodeResult]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@dataclass
class NodeContext:
    settings: Settings
    out_dir: Path
    tools: PipelineTools
    checkpoints: Path


@dataclass
class WorkflowGraph:
    nodes: dict[str, NodeFn]
    start: str = "plan"
    history_limit: int = 200

    def run(self, state: OrchestrationState, ctx: NodeContext) -> OrchestrationState:
        while True:
            stage = state.stage
            if stage not in self.nodes:
                if stage in TERMINALS:
                    break
                state.status = "failed"
                state.terminal_reason = f"unknown_stage:{stage}"
                break
            if state.status == "running" and state.cost.steps >= state.budget.max_steps:
                _set_terminal(state, "human", "budget_exhausted")
                state.stage = "human"
                continue
            node = self.nodes[stage]
            started = time.perf_counter()
            detail: dict[str, Any] = {}
            status = "ok"
            try:
                output = node(state, ctx)
            except Exception as exc:  # noqa: BLE001 - node failures become repair input
                output = "repair"
                status = "error"
                state.errors.append(
                    StepError(code="node_failed", stage=stage, message=str(exc))
                )
                detail = {"error": str(exc)}
            if isinstance(output, tuple):
                output, detail = output[0], output[1]
            elapsed = round((time.perf_counter() - started) * 1000, 2)
            state.cost.steps += 1
            state.cost.elapsed_ms = round(state.cost.elapsed_ms + elapsed, 2)
            state.history.append(
                StepRecord(node=stage, at=_now(), ms=elapsed, status=status, detail=detail)
            )
            if len(state.history) > self.history_limit:
                state.history = state.history[-self.history_limit :]
            if output is None:
                break
            state.stage = output  # type: ignore[assignment]
            state.save(ctx.checkpoints)
        return state


def _set_terminal(state: OrchestrationState, status: str, reason: str) -> None:
    state.status = status  # type: ignore[assignment]
    state.terminal_reason = reason


# ---------------------------------------------------------------------------
# workflow nodes
# ---------------------------------------------------------------------------


def node_plan(state: OrchestrationState, ctx: NodeContext) -> NodeResult:
    from ..ingest import ingest

    doc_path = Path(state.options.get("doc_path") or "")
    if not doc_path.exists():
        _set_terminal(state, "failed", "invalid_input:file_not_found")
        return "fail", {"path": str(doc_path)}
    document, pages = ingest(doc_path)
    state.doc_id = document.doc_id
    page_count = document.page_count or len(pages)
    state.artifacts["doc_path"] = str(doc_path)
    return "extract", {"doc_id": document.doc_id, "page_count": page_count}


def node_extract(state: OrchestrationState, ctx: NodeContext) -> NodeResult:
    doc_path = state.artifacts["doc_path"]
    try:
        result: PipelineResult = ctx.tools.call(
            "run_extract",
            doc_path=doc_path,
            ocr=state.options.get("ocr") or None,
            extractor=state.options.get("extractor") or None,
            template=state.options.get("template") or None,
        )
    except Exception as exc:  # noqa: BLE001 - classified and repaired downstream
        state.errors.append(
            StepError(code="extract_failed", stage="extract", message=str(exc))
        )
        return "repair", {"error": str(exc)}
    state.cost.extract_calls = ctx.tools.extract_calls
    state.cost.ocr_pages = ctx.tools.ocr_pages
    state.cost.model_tokens = ctx.tools.model_tokens
    state.artifacts.update(
        {
            "result": "result.json",
            "pages": "pages.json",
            "tablegrid": "tablegrid/",
            "evidence": "evidence.jsonl",
            "trace": "trace.json",
            "audit": "audit.md",
        }
    )
    return "ocr_gate", {"records": len(result.result.records), "tables": len(result.result.tables)}


def node_ocr_gate(state: OrchestrationState, ctx: NodeContext) -> NodeResult:
    pages = ctx.tools.call("load_artifact", name="pages.json")
    quality = ocr_quality(pages)
    state.context["ocr_quality"] = quality
    state.context["ocr_pages"] = len(pages)
    if quality < OCR_QUALITY_FLOOR and state.retries.ocr < state.budget.max_ocr_retries:
        return "reocr", {"quality": quality}
    return "route", {"quality": quality}


def node_reocr(state: OrchestrationState, ctx: NodeContext) -> NodeResult:
    state.retries.ocr += 1
    state.attempt += 1
    dpi = ctx.settings.ocr_dpi + 50 * state.retries.ocr
    try:
        ctx.tools.call(
            "run_extract",
            doc_path=state.artifacts["doc_path"],
            ocr=state.options.get("ocr") or None,
            extractor=state.options.get("extractor") or None,
            template=state.options.get("template") or None,
            ocr_dpi=dpi,
        )
    except Exception as exc:  # noqa: BLE001
        state.errors.append(
            StepError(code="ocr_retry_failed", stage="reocr", message=str(exc))
        )
        return "repair", {"dpi": dpi, "error": str(exc)}
    return "ocr_gate", {"dpi": dpi, "retry": state.retries.ocr}


def node_route(state: OrchestrationState, ctx: NodeContext) -> NodeResult:
    recipes = load_recipes(ctx.settings.project_root / "configs" / "recipes")
    tables = [t for t in _load_tables(ctx.out_dir) if t.profile != "admin"]
    if not tables:
        return "validate", {"tables": 0}
    decisions = [decide_route(table, recipes) for table in tables]
    queue = doc_queue(decisions)
    best = max(decisions, key=lambda item: item.confidence)
    state.route = RouteInfo(
        queue=queue,
        recipe_id=best.recipe_id,
        confidence=best.confidence,
        reasons=sorted({reason for item in decisions for reason in item.reasons})[:20],
    )
    state.context["route_tables"] = {
        table.table_id: decision.to_dict()
        for table, decision in zip(tables, decisions)
    }
    if queue == "human":
        _set_terminal(state, "human", "route_human")
        return "human", {"tables": len(tables), "queue": queue}
    return "validate", {"tables": len(tables), "queue": queue}


def node_validate(state: OrchestrationState, ctx: NodeContext) -> NodeResult:
    audit = ctx.tools.call("validate")
    codes = [issue.code for issue in audit.issues if issue.severity == "error"]
    state.context["audit"] = {
        "status": audit.status,
        "codes": codes,
        "coverage_missing": int(audit.stats.get("coverage_missing") or 0),
        "errors": int(audit.stats.get("issue_errors") or 0),
        "warnings": int(audit.stats.get("issue_warnings") or 0),
    }
    detail = {
        "status": audit.status,
        "errors": len(codes),
        "coverage_missing": audit.stats.get("coverage_missing", 0),
    }
    if audit.status == "fail":
        return "repair", detail
    return "coverage", detail


def node_coverage(state: OrchestrationState, ctx: NodeContext) -> NodeResult:
    audit = state.context.get("audit") or {}
    missing = int(audit.get("coverage_missing") or 0)
    if missing > 0:
        return "repair", {"coverage_missing": missing}
    return "assemble", {"coverage_missing": 0}


def node_repair(state: OrchestrationState, ctx: NodeContext) -> NodeResult:
    audit = state.context.get("audit") or {}
    decision = decide_repair(
        state,
        ocr_quality=float(state.context.get("ocr_quality", 1.0)),
        audit_status=str(audit.get("status") or "pass"),
        issue_codes=list(audit.get("codes") or []),
        coverage_missing=int(audit.get("coverage_missing") or 0),
    )
    state.context["repair"] = decision.to_dict()
    if decision.action == "retry_ocr":
        state.retries.ocr += 1
        state.attempt += 1
        return "reocr", decision.to_dict()
    if decision.action == "retry_extract":
        state.retries.extract += 1
        state.attempt += 1
        # A failed extract must not be replayed with the same expectations.
        if state.errors:
            state.errors[-1].retryable = False
        return "extract", decision.to_dict()
    if decision.action == "human":
        _set_terminal(state, "human", decision.code)
        return "human", decision.to_dict()
    return "assemble", decision.to_dict()


def node_assemble(state: OrchestrationState, ctx: NodeContext) -> NodeResult:
    result = ctx.tools.result()
    tables = result.result.tables
    clauses = [
        {"clause_id": clause.clause_id, "title": clause.title, "text": ""}
        for clause in result.result.clauses[:12]
    ]
    fields = [item.field for item in (result.result.coverage.items if result.result.coverage else [])]
    evidence_ids = [item.evidence_id for item in result.evidence[:50]]
    context = assemble_context(
        {"doc_id": result.result.document.doc_id},
        table=tables[0] if tables else None,
        clauses=clauses,
        schema_fields=fields,
        previous_errors=[error.model_dump() for error in state.errors],
        evidence_ids=evidence_ids,
    )
    compacted = compact_context(context)
    regression = context_regression(context, compacted)
    state.context["context"] = {
        "tokens": context["tokens"],
        "compacted_tokens": compacted["tokens"],
        "lossless": regression["lossless"],
        "token_reduction": regression["token_reduction"],
    }
    ctx.tools.call("write_artifact", name="m3_context.json", data=compacted)
    state.artifacts["context"] = "m3_context.json"
    payload = _state_payload(state, result)
    ctx.tools.call("write_artifact", name="m3_trace.json", data=payload)
    state.artifacts["m3_trace"] = "m3_trace.json"
    state.save(ctx.checkpoints)
    return "publish_gate", {"context_tokens": context["tokens"], "lossless": regression["lossless"]}


def node_publish_gate(state: OrchestrationState, ctx: NodeContext) -> NodeResult:
    audit = state.context.get("audit")
    if not audit:
        _set_terminal(state, "human", "audit_missing")
        return "human", {"status": "missing"}
    status = str(audit.get("status") or "pass")
    if state.route.queue == "human":
        _set_terminal(state, "human", "route_human")
        return "human", {"status": status}
    if status == "pass":
        return "publish", {"status": status}
    if status == "review":
        _set_terminal(state, "review", "audit_review")
        return "human", {"status": status}
    _set_terminal(state, "human", "audit_failed")
    return "human", {"status": status}


def node_publish(state: OrchestrationState, ctx: NodeContext) -> NodeResult:
    _set_terminal(state, "published", "published")
    lane = "production" if state.route.queue == "production" else "explore"
    _enqueue(state, ctx, lane, state.route.reasons)
    return None


def node_human(state: OrchestrationState, ctx: NodeContext) -> NodeResult:
    if state.status == "running":
        _set_terminal(state, "human", state.terminal_reason or "human_review")
    try:
        result = ctx.tools.result()
        ctx.tools.call("write_artifact", name="m3_trace.json", data=_state_payload(state, result))
        state.artifacts["m3_trace"] = "m3_trace.json"
    except Exception:  # noqa: BLE001 - trace is best-effort on the human path
        pass
    _enqueue(state, ctx, "human", [state.terminal_reason or "human_review"])
    return None


def node_fail(state: OrchestrationState, ctx: NodeContext) -> NodeResult:
    _set_terminal(state, "failed", state.terminal_reason or "failed")
    return None


def build_workflow() -> WorkflowGraph:
    return WorkflowGraph(
        nodes={
            "plan": node_plan,
            "extract": node_extract,
            "ocr_gate": node_ocr_gate,
            "reocr": node_reocr,
            "route": node_route,
            "validate": node_validate,
            "repair": node_repair,
            "coverage": node_coverage,
            "assemble": node_assemble,
            "publish_gate": node_publish_gate,
            "publish": node_publish,
            "human": node_human,
            "fail": node_fail,
        },
        start="plan",
    )


# ---------------------------------------------------------------------------
# entrypoint
# ---------------------------------------------------------------------------


def run_orchestrated(
    doc_path: str | Path,
    out_dir: str | Path,
    settings: Settings | None = None,
    *,
    job_id: str | None = None,
    options: dict[str, str] | None = None,
    resume: bool = False,
    tools: PipelineTools | None = None,
) -> OrchestrationState:
    settings = settings or Settings.from_env()
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    checkpoint = out / "m3_state.json"
    if resume and checkpoint.exists():
        state = OrchestrationState.load(checkpoint)
    else:
        state = OrchestrationState(
            job_id=job_id or uuid.uuid4().hex[:12],
            options={"doc_path": str(doc_path), **(options or {})},
        )
    ctx = NodeContext(
        settings=settings,
        out_dir=out,
        tools=tools or PipelineTools(settings, out),
        checkpoints=checkpoint,
    )
    graph = build_workflow()
    state = graph.run(state, ctx)
    state.save(checkpoint)
    return state


def resume_orchestration(
    out_dir: str | Path,
    settings: Settings | None = None,
    *,
    decision: str | None = None,
) -> OrchestrationState:
    """Resume a checkpoint; ``decision='publish'`` approves a human hold."""
    settings = settings or Settings.from_env()
    out = Path(out_dir)
    state = OrchestrationState.load(out / "m3_state.json")
    if decision == "publish":
        state.status = "running"
        state.stage = "publish"
        state.terminal_reason = "human_approved"
    elif decision == "fail":
        state.status = "running"
        state.stage = "fail"
    ctx = NodeContext(
        settings=settings, out_dir=out, tools=PipelineTools(settings, out), checkpoints=out / "m3_state.json"
    )
    state = build_workflow().run(state, ctx)
    state.save(ctx.checkpoints)
    return state


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def ocr_quality(pages: list[dict]) -> float:
    if not pages:
        return 0.0
    good = 0
    for page in pages:
        text = str(page.get("markdown") or "").strip()
        if len(text) >= 20:
            good += 1
    return round(good / len(pages), 4)


def _load_tables(out_dir: Path) -> list[TableGrid]:
    tables: list[TableGrid] = []
    for path in sorted((out_dir / "tablegrid").glob("*.json")):
        tables.append(TableGrid.model_validate_json(path.read_text(encoding="utf-8")))
    return tables


def _state_payload(state: OrchestrationState, result: PipelineResult) -> dict[str, Any]:
    return {
        "job_id": state.job_id,
        "doc_id": state.doc_id,
        "status": state.status,
        "stage": state.stage,
        "attempt": state.attempt,
        "route": state.route.model_dump(),
        "audit": state.context.get("audit"),
        "ocr_quality": state.context.get("ocr_quality"),
        "context": state.context.get("context"),
        "cost": state.cost.model_dump(),
        "errors": [error.model_dump() for error in state.errors],
        "history": [item.model_dump() for item in state.history],
        "pipeline_steps": result.trace.get("steps", []),
        "versions": result.trace.get("versions", {}),
    }


def _enqueue(state: OrchestrationState, ctx: NodeContext, lane: str, reasons: list[str]) -> None:
    item = {
        "doc_id": state.doc_id,
        "job_id": state.job_id,
        "queue": lane,
        "status": state.status,
        "reason": state.terminal_reason,
        "reasons": reasons,
        "attempt": state.attempt,
    }
    try:
        QueueStore(Path(ctx.settings.data_dir) / "queues").enqueue(lane, item)
    except OSError:
        pass
