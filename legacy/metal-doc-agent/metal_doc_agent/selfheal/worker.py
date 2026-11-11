"""Self-heal worker: process open feedback from the isolated queue."""

from __future__ import annotations

import argparse
import time

from .config import SelfHealSettings
from .pipeline import SelfHealPipeline
from .storage import SelfHealStore


def run_once(settings: SelfHealSettings | None = None, limit: int = 20) -> int:
    settings = settings or SelfHealSettings.from_env()
    if not settings.enabled:
        print("SELFHEAL_ENABLED=0; worker idle")
        return 0
    settings.ensure_dirs()
    store = SelfHealStore(settings.db_path)
    pipeline = SelfHealPipeline(store, settings)
    outcomes = pipeline.process_open(limit=limit)
    for outcome in outcomes:
        print(
            f"{outcome.feedback_id} status={outcome.status.value} "
            f"level={outcome.level.value if outcome.level else '-'} "
            f"decision={outcome.decision.value if outcome.decision else '-'}"
        )
    return len(outcomes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="process the queue once")
    parser.add_argument("--interval", type=float, default=15.0)
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args(argv)
    if args.once:
        run_once(limit=args.limit)
        return 0
    while True:
        try:
            run_once(limit=args.limit)
        except Exception as exc:  # noqa: BLE001 - keep the worker alive
            print(f"worker error: {exc}")
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
