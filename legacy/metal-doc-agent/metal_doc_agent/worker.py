"""Single-job worker entry point.

Two modes:

* ``--job-id``: consume a persisted job from ``JobStore`` (same state as the API);
* ``--job/--out``: run an ad-hoc file without a job record.

The production plan replaces this with Redis + Dramatiq/Arq; the job contract
stays the same.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from .jobs import LANES, JobStore
from .logging_setup import configure_logging
from .pipeline import run_pipeline
from .runner import run_job
from .sandbox_exec import run_job_sandbox, sandbox_enabled
from .settings import Settings

logger = logging.getLogger(__name__)


def run_queued(
    store: JobStore, settings: Settings, *, limit: int = 5, pool: str | None = None
) -> list[str]:
    """Run up to ``limit`` queued jobs (oldest first) and return their ids.

    ``pool`` limits the worker to one lane (production/explore/human) so
    exploratory jobs cannot starve production work.

    With ``METAL_DOC_SANDBOX=1`` (default) each job runs in a fresh interpreter
    that imports the current source tree, so a self-heal patch is picked up by
    the next job without restarting this worker.
    """

    recovered = store.recover_stale_running()
    if recovered:
        logger.warning("recovered stale running jobs: %s", recovered)

    queued = [
        state
        for state in store.list(limit=500, lane=pool)
        if state.status == "queued"
    ]
    queued.sort(key=lambda state: state.created_at or "")
    ran: list[str] = []
    for state in queued[:limit]:
        if sandbox_enabled(settings):
            ok, detail = run_job_sandbox(settings, store.root, state.job_id)
            if not ok:
                logger.warning("sandboxed job %s failed: %s", state.job_id, detail)
                _mark_failed(store, state.job_id, detail)
                continue
        else:
            try:
                run_job(store, state.job_id, settings)
            except (KeyError, RuntimeError) as exc:
                logger.warning("skip job %s: %s", state.job_id, exc)
                continue
        ran.append(state.job_id)
    return ran


def _mark_failed(store: JobStore, job_id: str, detail: str) -> None:
    """A hard child-process failure must not leave the job stuck in running."""

    try:
        state = store.get(job_id)
        if state is None:
            return
        if state.status == "queued":
            claimed = store.claim(job_id)
            if claimed is None:
                # Another worker owns it; leave the job to that worker.
                return
            state = claimed
        if state.status == "running":
            store.update(
                job_id,
                status="failed",
                stage="error",
                error=detail[:1000],
                failure_code="engine_failed",
            )
        store.release_claim(job_id)
    except Exception:  # noqa: BLE001 - the queue must keep moving
        logger.exception("failed to mark job %s as failed", job_id)


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="Run one extraction job")
    parser.add_argument("--job", help="OCR markdown or PDF file")
    parser.add_argument("--out", help="output directory for ad-hoc mode")
    parser.add_argument("--job-id", help="persisted job id from the JobStore")
    parser.add_argument("--store", help="jobs root (default: METAL_DOC_DATA/jobs)")
    parser.add_argument("--template", default="product_full")
    parser.add_argument(
        "--watch", action="store_true", help="poll the store and run queued jobs"
    )
    parser.add_argument(
        "--once", action="store_true", help="run queued jobs once and exit"
    )
    parser.add_argument("--poll", type=float, default=2.0, help="watch poll seconds")
    parser.add_argument("--limit", type=int, default=5, help="jobs per batch")
    parser.add_argument(
        "--pool",
        choices=LANES,
        default=None,
        help="only consume this lane (default: WORKER_POOL env or all lanes)",
    )
    parser.add_argument(
        "--stale-seconds",
        type=float,
        default=300.0,
        help="requeue running jobs whose heartbeat is older than this",
    )
    args = parser.parse_args(argv)

    settings = Settings.from_env()
    pool = args.pool or os.environ.get("WORKER_POOL") or None
    if pool and pool not in LANES:
        parser.error(f"invalid pool: {pool}")
    if args.watch or args.once:
        store = JobStore(
            args.store or settings.data_dir / "jobs",
            stale_seconds=args.stale_seconds,
        )
        logger.info(
            "worker watching pool=%s limit=%s poll=%.1fs store=%s",
            pool or "all",
            args.limit,
            args.poll,
            store.root,
        )
        try:
            while True:
                ran = run_queued(store, settings, limit=args.limit, pool=pool)
                if ran:
                    print(json.dumps({"ran": ran}, ensure_ascii=False))
                if args.once:
                    return 0
                if not ran:
                    time.sleep(max(0.2, args.poll))
        except KeyboardInterrupt:
            return 0

    if args.job_id:
        store = JobStore(
            args.store or settings.data_dir / "jobs",
            stale_seconds=args.stale_seconds,
        )
        try:
            result = run_job(store, args.job_id, settings)
        except (KeyError, RuntimeError) as exc:
            print(
                json.dumps(
                    {"job_id": args.job_id, "error": str(exc)},
                    ensure_ascii=False,
                )
            )
            return 1
        state = store.get(args.job_id)
        print(
            json.dumps(
                {
                    "job_id": args.job_id,
                    "status": state.status if state else "missing",
                    "stage": state.stage if state else "missing",
                    "result_status": state.result_status if state else None,
                    "summary": state.summary if state else {},
                    "error": state.error if state else None,
                    "out": state.out_dir if state else None,
                },
                ensure_ascii=False,
            )
        )
        return 0 if result is not None and state and state.status != "failed" else 1

    if not args.job or not args.out:
        parser.error("either --job-id or both --job and --out are required")
    result = run_pipeline(args.job, Path(args.out), coverage_template=args.template)
    print(
        json.dumps(
            {
                "doc": result.result.document.standard_no,
                "records": len(result.result.records),
                "status": result.result.quality.status if result.result.quality else "unknown",
                "out": str(Path(args.out).resolve()),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
