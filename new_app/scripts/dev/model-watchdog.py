#!/usr/bin/env python3
"""Model-server memory watchdog CLI.

Examples:
    # During model loading: kill the just-started model process on low memory.
    python scripts/dev/model-watchdog.py --mode load --floor-mb 8192 \
        --target-pid 12345 --ready-url http://192.168.1.35:9988/v1/models \
        --timeout 600

    # During a test: abort the local benchmark client on low memory.
    python scripts/dev/model-watchdog.py --mode test --floor-mb 2048 \
        --local-pid 23456
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import signal
import subprocess
import sys
import time
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

NEW_APP = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(NEW_APP))

from services.agent.watchdog import MemoryWatchdog, WatchdogConfig, WatchdogTripped  # noqa: E402


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def append_log(path: str, payload: dict) -> None:
    if not path:
        return
    target = Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    except OSError:
        pass


def ssh_command(args: argparse.Namespace) -> list[str]:
    command = [
        "ssh",
        "-o",
        "BatchMode=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        f"ConnectTimeout={args.ssh_timeout:g}",
    ]
    if args.ssh_key:
        command += ["-i", args.ssh_key]
    command.append(f"{args.ssh_user}@{args.host}")
    return command


def local_meminfo_mb(path: str = "/proc/meminfo") -> int:
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.startswith("MemAvailable:"):
            return int(line.split()[1]) // 1024
    raise RuntimeError(f"MemAvailable not found in {path}")


def available_mb(args: argparse.Namespace) -> int:
    if args.host in {"local", "localhost", "127.0.0.1"}:
        return local_meminfo_mb()
    command = ssh_command(args) + ["awk '/MemAvailable/{print $2}' /proc/meminfo"]
    completed = subprocess.run(
        command,
        capture_output=True,
        text=True,
        timeout=args.ssh_timeout,
        check=True,
    )
    parts = completed.stdout.strip().split()
    if not parts:
        raise RuntimeError("empty MemAvailable response")
    return int(parts[0]) // 1024


def is_ready(url: str) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            return 200 <= response.status < 300
    except Exception:  # noqa: BLE001 - readiness is best effort
        return False


def kill_local(pid: int, grace: float) -> None:
    try:
        os.kill(pid, signal.SIGTERM)
    except OSError:
        return
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except OSError:
            return
        time.sleep(0.2)
    try:
        os.kill(pid, signal.SIGKILL)
    except OSError:
        pass


def kill_remote(args: argparse.Namespace, reason: str) -> None:
    if args.mode != "load":
        return
    if not args.target_pid and not args.target_pattern:
        return
    if args.target_pattern:
        remote = f"pkill -9 -f {shlex.quote(args.target_pattern)}"
    else:
        remote = f"kill -9 {int(args.target_pid)}"
    try:
        subprocess.run(
            ssh_command(args) + [remote],
            capture_output=True,
            text=True,
            timeout=args.ssh_timeout,
            check=False,
        )
        append_log(
            args.log,
            {"ts": now_iso(), "event": "killed_remote", "reason": reason, "remote": remote},
        )
    except Exception as exc:  # noqa: BLE001 - log and keep the trip
        append_log(
            args.log,
            {"ts": now_iso(), "event": "kill_remote_failed", "error": str(exc)},
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="Model-server memory watchdog")
    parser.add_argument("--host", default="192.168.1.35")
    parser.add_argument("--ssh-user", default="grainuser")
    parser.add_argument("--ssh-key", default="")
    parser.add_argument("--ssh-timeout", type=float, default=10.0)
    parser.add_argument("--mode", choices=("load", "test"), default="test")
    parser.add_argument("--floor-mb", type=int, default=2048)
    parser.add_argument("--interval", type=float, default=2.0)
    parser.add_argument("--grace", type=float, default=3.0)
    parser.add_argument("--timeout", type=float, default=0.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--ready-url", default="")
    parser.add_argument("--target-pid", type=int, default=0)
    parser.add_argument("--target-pattern", default="")
    parser.add_argument("--local-pid", type=int, default=0)
    parser.add_argument("--log", default="logs/model-watchdog.jsonl")
    args = parser.parse_args()

    def on_trip(error: WatchdogTripped) -> None:
        append_log(
            args.log,
            {
                "ts": now_iso(),
                "event": "tripped",
                "mode": args.mode,
                "host": args.host,
                "available_mb": error.available_mb,
                "floor_mb": error.floor_mb,
                "reason": error.reason,
                "detail": error.detail,
            },
        )
        kill_remote(args, error.reason)
        if args.local_pid:
            kill_local(args.local_pid, args.grace)

    watchdog = MemoryWatchdog(
        lambda: available_mb(args),
        WatchdogConfig(
            floor_mb=args.floor_mb,
            interval_seconds=args.interval,
            grace_seconds=args.grace,
        ),
        on_trip=on_trip,
    )

    started = time.monotonic()
    samples = 0
    while True:
        samples += 1
        try:
            current = watchdog.check()
        except WatchdogTripped as exc:
            print(f"WATCHDOG TRIPPED: {exc}", file=sys.stderr)
            return 2
        print(
            f"[{samples}] available={current}MiB floor={args.floor_mb}MiB "
            f"host={args.host}",
            flush=True,
        )
        if args.once:
            return 0
        if args.ready_url and is_ready(args.ready_url):
            append_log(
                args.log,
                {"ts": now_iso(), "event": "ready", "host": args.host, "url": args.ready_url},
            )
            print("READY", flush=True)
            return 0
        if args.timeout and time.monotonic() - started >= args.timeout:
            append_log(
                args.log,
                {"ts": now_iso(), "event": "timeout", "host": args.host},
            )
            print("WATCHDOG TIMEOUT", file=sys.stderr)
            return 3
        time.sleep(args.interval)


if __name__ == "__main__":
    raise SystemExit(main())
