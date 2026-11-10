"""Minimal secret scan for CI (M5.2-03).

Checks the repository for committed secrets: .env files, key material, cloud
tokens and obvious hardcoded API keys. Exit code 1 means findings.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP_DIRS = {".git", "node_modules", "dist", "__pycache__", "runs", "eval", "data", ".trae"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf", ".zip", ".whl", ".pyc"}
PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC )?PRIVATE KEY-----"),
    "aws_key": re.compile(r"AKIA[0-9A-Z]{16}"),
    "github_token": re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}"),
    "openai_key": re.compile(r"sk-[A-Za-z0-9]{32,}"),
    "slack_token": re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}"),
}
ALLOWED_FILES = {
    "infra/security/check_secrets.py",
}


def scan(root: Path) -> list[dict]:
    findings: list[dict] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in SKIP_SUFFIXES:
            continue
        if path.name == ".env" or path.name == "secret.key":
            findings.append({"file": relative, "rule": "committed_secret_file"})
            continue
        if relative in ALLOWED_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for rule, pattern in PATTERNS.items():
            if pattern.search(text):
                findings.append({"file": relative, "rule": rule})
    return findings


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    findings = scan(Path(args.root))
    report = {"findings": findings, "passed": not findings}
    if args.out:
        Path(args.out).write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print(json.dumps(report, ensure_ascii=False))
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
