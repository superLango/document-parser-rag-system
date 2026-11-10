"""Execute one persisted job and keep its state in sync."""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import replace
from pathlib import Path
from typing import Callable

from .contracts import JobState
from .jobs import JobStore
from .logging_setup import bind_job, reset_job
from .pipeline import PipelineResult, run_pipeline
from .settings import Settings

logger = logging.getLogger(__name__)

DEFAULT_OPTIONS = {"ocr": "mock", "extractor": "mock", "template": "product_full"}

ORCHESTRATED_STATUS = {
    "published": ("succeeded", "pass", "done"),
    "review": ("review", "review", "done"),
    "human": ("review", "review", "done"),
    "failed": ("failed", "fail", "error"),
}


def job_options(state: JobState) -> dict[str, str]:
    options = dict(DEFAULT_OPTIONS)
    options.update(state.options)
    return options


def _failure_code_text(text: str) -> str:
    lowered = text.lower()
    if "timeout" in lowered:
        return "timeout"
    if "file_not_found" in lowered or "invalid_input" in lowered:
        return "invalid_input"
    if "ocr" in lowered:
        return "ocr_failed"
    if "layout" in lowered:
        return "layout_failed"
    if "qwen" in lowered or "extract" in lowered:
        return "extract_failed"
    return "engine_failed"


def _failure_code(exc: Exception) -> str:
    """Stable failure taxonomy for OCR / layout / extraction / input errors."""
    if isinstance(exc, FileNotFoundError):
        return "invalid_input"
    if isinstance(exc, ValueError):
        return "invalid_input"
    return _failure_code_text(f"{type(exc).__name__} {exc}")


def run_job(
    store: JobStore,
    job_id: str,
    settings: Settings,
    *,
    progress: Callable[[str, int], None] | None = None,
) -> PipelineResult | None:
    state = store.get(job_id)
    if state is None:
        raise KeyError(f"job not found: {job_id}")
    if state.status != "queued":
        if state.status in {"failed", "review"}:
            store.reset_for_retry(job_id)
        else:
            raise RuntimeError(
                f"job {job_id} is {state.status}; only queued jobs can run"
            )

    claimed = store.claim(job_id)
    if claimed is None:
        raise RuntimeError(f"job {job_id} is owned by another worker")
    state = claimed
    options = job_options(state)

    stop_heartbeat = threading.Event()

    def heartbeat() -> None:
        while not stop_heartbeat.wait(30.0):
            store.touch_claim(job_id)

    beat = threading.Thread(target=heartbeat, daemon=True)
    beat.start()

    def report(stage: str, percent: int) -> None:
        store.update(job_id, stage=stage, progress=percent)
        if progress is not None:
            progress(stage, percent)

    job_token = bind_job(job_id)
    try:
        try:
            store.update(job_id, options=options)
            job_settings = replace(
                settings,
                ocr_backend=options.get("ocr", settings.ocr_backend),
                extractor_backend=options.get("extractor", settings.extractor_backend),
                business_dictionary_path=(
                    options.get("dictionary_path")
                    or settings.business_dictionary_path
                ),
                business_dictionary_override_path=None,
                dictionary_category_mode=options.get(
                    "category_mode", settings.dictionary_category_mode
                ),
            )
            if settings.orchestrate:
                _run_orchestrated_job(store, job_id, state, job_settings, options)
                return None
            result = run_pipeline(
                state.doc_path,
                state.out_dir,
                settings=job_settings,
                coverage_template=options.get("template", "product_full"),
                job_id=job_id,
                progress=report,
            )
        except Exception as exc:  # noqa: BLE001 - persisted job failures are data
            logger.exception("job %s failed", job_id)
            store.update(
                job_id,
                status="failed",
                stage="error",
                error=str(exc)[:1000],
                failure_code=_failure_code(exc),
            )
            return None

        audit = result.result.quality
        result_status = audit.status if audit else "unknown"
        status = "succeeded" if result_status == "pass" else "review"
        tokens = int((result.trace.get("model_usage") or {}).get("total_tokens") or 0)
        _write_job_metrics(
            Path(state.out_dir), result.trace.get("elapsed_ms") or 0, tokens
        )
        summary = {
            "pages": result.result.document.page_count,
            "tables": len(result.result.tables),
            "records": len(result.result.records),
            "items": len(result.inventory.items) if result.inventory else 0,
            "evidence": len(result.evidence),
            "new_terms": len(result.alignment.new_terms) if result.alignment else 0,
            "errors": int(audit.stats.get("issue_errors", 0)) if audit else 0,
            "warnings": int(audit.stats.get("issue_warnings", 0)) if audit else 0,
            "model_tokens": tokens,
        }
        store.update(
            job_id,
            status=status,
            stage="done",
            progress=100,
            result_status=result_status,
            artifact_manifest="artifacts.json",
            summary=summary,
        )
        return result
    finally:
        stop_heartbeat.set()
        beat.join(timeout=1.0)
        store.release_claim(job_id)
        reset_job(job_token)


def resume_job(
    store: JobStore,
    job_id: str,
    settings: Settings,
    *,
    decision: str = "publish",
) -> JobState | None:
    """Resume an orchestrated job from its checkpoint (human hold or failure)."""
    state = store.get(job_id)
    if state is None:
        raise KeyError(f"job not found: {job_id}")
    claimed = store.claim(job_id)
    if claimed is None:
        return None
    try:
        from .orchestration import resume_orchestration

        m3 = resume_orchestration(state.out_dir, settings, decision=decision)
        _store_orchestrated_result(store, job_id, Path(state.out_dir), m3)
        return store.get(job_id)
    finally:
        store.release_claim(job_id)


def _run_orchestrated_job(
    store: JobStore,
    job_id: str,
    state: JobState,
    settings: Settings,
    options: dict[str, str],
) -> None:
    from .orchestration import run_orchestrated

    store.update(job_id, stage="orchestrating", progress=10)
    m3 = run_orchestrated(
        state.doc_path,
        state.out_dir,
        settings,
        job_id=job_id,
        options=options,
    )
    _store_orchestrated_result(store, job_id, Path(state.out_dir), m3)


def _store_orchestrated_result(store: JobStore, job_id: str, out_dir: Path, m3) -> None:
    status, result_status, stage = ORCHESTRATED_STATUS.get(
        m3.status, ("failed", "fail", "error")
    )
    trace_path = out_dir / "trace.json"
    if trace_path.exists():
        try:
            trace = json.loads(trace_path.read_text(encoding="utf-8"))
            tokens = int((trace.get("model_usage") or {}).get("total_tokens") or 0)
            _write_job_metrics(out_dir, float(trace.get("elapsed_ms") or 0), tokens)
        except ValueError:
            pass
    error_text: str | None = None
    failure_code: str | None = None
    if m3.errors:
        error_text = str(m3.errors[-1].message)[:1000]
        failure_code = _failure_code_text(error_text)
    elif (m3.context or {}).get("ocr_quality") == 0:
        error_text = "ocr quality 0.0"
        failure_code = "ocr_failed"
    if status == "failed" and not error_text:
        error_text = m3.terminal_reason
        failure_code = _failure_code_text(str(m3.terminal_reason or ""))
    changes: dict[str, object] = {
        "status": status,
        "stage": stage,
        "progress": 100,
        "result_status": result_status,
        "summary": _artifact_summary(out_dir, m3),
        "error": error_text,
        "failure_code": failure_code,
    }
    if (out_dir / "artifacts.json").exists():
        changes["artifact_manifest"] = "artifacts.json"
    store.update(job_id, **changes)


def _write_job_metrics(out_dir: Path, elapsed_ms: float, model_tokens: int = 0) -> None:
    try:
        (out_dir / "metrics.json").write_text(
            json.dumps(
                {
                    "pipeline_seconds": round(elapsed_ms / 1000, 3),
                    "model_tokens": int(model_tokens),
                }
            )
            + "\n",
            encoding="utf-8",
        )
    except OSError:
        logger.warning("job metrics write failed", exc_info=True)


def _artifact_summary(out_dir: Path, m3) -> dict:
    # JobState.summary is dict[str, int]; keep orchestration details numeric.
    summary = {
        "orchestrated": 1,
        "steps": m3.cost.steps,
        "extract_calls": m3.cost.extract_calls,
        "ocr_pages": m3.cost.ocr_pages,
        "model_tokens": m3.cost.model_tokens,
        "retries": m3.retries.extract + m3.retries.ocr,
    }
    path = out_dir / "result.json"
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            return summary
        summary.update(
            {
                "pages": (payload.get("document") or {}).get("page_count", 0),
                "tables": len(payload.get("tables") or []),
                "records": len(payload.get("records") or []),
            }
        )
    return summary
