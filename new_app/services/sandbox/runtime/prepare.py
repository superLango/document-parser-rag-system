"""Materialise a sandbox workspace from a compact JSON envelope.

Used as the init container for the Kubernetes Job executor, where inputs are
shipped in a ConfigMap instead of a Docker volume.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

WORK_DIR = Path(os.environ.get("HANSON_WORK_DIR", "/work"))
CONFIG_PATH = Path(os.environ.get("HANSON_CONFIG", "/config/envelope.json"))


def safe_target(relative: str) -> Path:
    if not relative or relative.startswith("/") or "\\" in relative:
        raise ValueError(f"invalid workspace path: {relative}")
    parts = relative.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"invalid workspace path: {relative}")
    target = (WORK_DIR / relative).resolve()
    if not target.is_relative_to(WORK_DIR.resolve()):
        raise ValueError(f"workspace path escapes root: {relative}")
    return target


def main() -> int:
    payload = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    files = payload.get("files") or {}
    directories = payload.get("dirs") or ["input", "recipes", "templates"]

    for name in directories:
        safe_target(name).mkdir(parents=True, exist_ok=True)
    (WORK_DIR / "output").mkdir(parents=True, exist_ok=True)

    for relative, encoded in files.items():
        target = safe_target(relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(base64.b64decode(encoded))
        os.chmod(target, 0o444)

    # Inputs are root-owned and read-only for the unprivileged engine user.
    for name in directories:
        os.chmod(safe_target(name), 0o555)
    os.chmod(WORK_DIR / "output", 0o777)
    return 0


if __name__ == "__main__":
    sys.exit(main())
