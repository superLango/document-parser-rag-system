#!/usr/bin/env python3
"""Run a command under the model-server memory watchdog.

Usage:
    python scripts/dev/guarded-model-test.py --floor-mb 4096 -- \
        python scripts/dev/qwen-smoke.py
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

NEW_APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(NEW_APP))

from services.agent.watchdog import MemoryWatchdog, WatchdogConfig, WatchdogTripped  # noqa: E402


def available_mb(args: argparse.Namespace) -> int:
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        f"ConnectTimeout={args.ssh_timeout:g}",
        f"{args.ssh_user}@{args.host}",
        "awk '/MemAvailable/{print $2}' /proc/meminfo",
    ]
    completed = subprocess.run(
        command, capture_output=True, text=True, timeout=args.ssh_timeout, check=True
    )
    parts = completed.stdout.strip().split()
    if not parts:
        raise RuntimeError("empty MemAvailable response")
    return int(parts[0]) // 1024


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a test under the memory watchdog")
    parser.add_argument("--host", default="192.168.1.35")
    parser.add_argument("--ssh-user", default="grainuser")
    parser.add_argument("--ssh-timeout", type=float, default=10.0)
    parser.add_argument("--floor-mb", type=int, default=4096)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    command = args.command
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("a command is required after --")

    process = subprocess.Popen(command)
    watchdog = MemoryWatchdog(
        lambda: available_mb(args),
        WatchdogConfig(floor_mb=args.floor_mb, interval_seconds=args.interval),
    )

    def request_stop() -> None:
        if process.poll() is None:
            process.terminate()

    try:
        available = watchdog.check()
        print(f"watchdog floor={args.floor_mb}MiB available={available}MiB", flush=True)
        code = watchdog.guard(process)
        print(f"watchdog: test exited code={code}", flush=True)
        return code
    except WatchdogTripped as exc:
        request_stop()
        print(f"WATCHDOG TRIPPED: {exc}", file=sys.stderr)
        return 2
    except Exception:
        request_stop()
        raise


if __name__ == "__main__":
    raise SystemExit(main())
