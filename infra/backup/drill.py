"""Local backup/restore drill with encryption (M5.1-05 / C9).

Simulates the drill without a K8s/Postgres environment: SQLite platform DB +
engine data volume, tar backup, Fernet encryption, checksum verification,
decrypt-and-restore into a fresh directory, plus a tamper-detection check.

The limitation ("no Postgres/object storage/K8s") stays explicit in the report.

Usage:
    python infra/backup/drill.py --out eval/backup-drill.json --md eval/backup-drill.md
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import sqlite3
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

ROOT = Path(__file__).resolve().parents[2]
DOCS = 25
SALT = b"metal-doc-backup-drill"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(ROOT / "metal-doc-agent" / "eval" / "backup-drill.json"))
    parser.add_argument("--md", default=str(ROOT / "metal-doc-agent" / "eval" / "backup-drill.md"))
    args = parser.parse_args(argv)

    steps: list[dict] = []
    with tempfile.TemporaryDirectory(prefix="m5-drill-") as tmp:
        base = Path(tmp)
        prod = base / "prod"
        backup = base / "backup"
        restored = base / "restored"
        _seed_environment(prod)
        key = _derive_key("drill-passphrase")
        started = time.perf_counter()
        steps.append(_step("seed", _count_documents(prod)))
        steps.append(_step("backup_db", _backup_sqlite(prod / "platform.db", backup / "platform.db")))
        steps.append(_step("backup_engine", _tar(prod / "engine", backup / "engine-data.tgz")))
        steps.append(_step("encrypt", _encrypt_tree(backup, key)))

        checksums = {
            path.name: _sha256(path)
            for path in sorted(backup.glob("*.enc"))
            if path.is_file()
        }
        (backup / "SHA256SUMS").write_text(
            "\n".join(f"{digest}  {name}" for name, digest in checksums.items()) + "\n",
            encoding="utf-8",
        )
        steps.append(_step("checksum", {"files": len(checksums)}))

        restored.mkdir(parents=True, exist_ok=True)
        decrypt_detail = _decrypt_tree(backup, restored, key)
        with tarfile.open(restored / "engine-data.tgz", "r:gz") as archive:
            archive.extractall(restored, filter="data")
        steps.append(_step("decrypt", decrypt_detail))
        steps.append(_step("restore_db", _count_documents(restored)))
        steps.append(_step("restore_engine", _engine_inventory(restored / "engine")))

        tampered = base / "tampered.enc"
        source = sorted(backup.glob("*.enc"))[0]
        payload = bytearray(source.read_bytes())
        payload[10] ^= 0xFF
        tampered.write_bytes(bytes(payload))
        tamper_ok = False
        try:
            Fernet(key).decrypt(bytes(payload))
        except InvalidToken:
            tamper_ok = True
        steps.append(_step("tamper_detected", {"detected": tamper_ok}))

        checks = {
            "documents_match": _count_documents(restored) == _count_documents(prod),
            "engine_files_match": _engine_inventory(restored / "engine")
            == _engine_inventory(prod / "engine"),
            "checksums_match": all(
                _sha256(backup / name) == digest for name, digest in checksums.items()
            ),
            "tamper_detected": tamper_ok,
        }
        steps.append(
            {
                "step": "verify",
                "ok": all(checks.values()),
                "detail": checks,
                "seconds": round(time.perf_counter() - started, 3),
            }
        )
        passed = all(step["ok"] for step in steps)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "local-sqlite+volume+fernet",
        "encryption": "fernet(fernet-key from scrypt)",
        "documents": DOCS,
        "steps": steps,
        "checks": checks,
        "passed": passed,
        "limitations": [
            "SQLite instead of Postgres/pg_dump",
            "local volume tar instead of PVC/object storage",
            "no K8s namespace restore (kubectl/docker unavailable in this environment)",
        ],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    Path(args.md).write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"passed": passed, "checks": checks}, ensure_ascii=False))
    print(f"out={out}")
    return 0 if passed else 1


def _derive_key(passphrase: str) -> bytes:
    derived = Scrypt(salt=SALT, length=32, n=2**14, r=8, p=1).derive(
        passphrase.encode("utf-8")
    )
    return base64.urlsafe_b64encode(derived)


def _encrypt_tree(root: Path, key: bytes) -> dict:
    fernet = Fernet(key)
    files = [path for path in sorted(root.iterdir()) if path.is_file()]
    total = 0
    for path in files:
        token = fernet.encrypt(path.read_bytes())
        target = path.with_name(path.name + ".enc")
        target.write_bytes(token)
        path.unlink()
        total += len(token)
    return {"files": len(files), "cipher_bytes": total}


def _decrypt_tree(backup: Path, restored: Path, key: bytes) -> dict:
    fernet = Fernet(key)
    files = sorted(backup.glob("*.enc"))
    for path in files:
        name = path.name[: -len(".enc")]
        (restored / name).write_bytes(fernet.decrypt(path.read_bytes()))
    return {"files": len(files)}


def _seed_environment(root: Path) -> None:
    (root / "engine" / "jobs" / "job-1" / "tablegrid").mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(root / "platform.db")
    connection.execute("CREATE TABLE documents (id TEXT PRIMARY KEY, review_status TEXT)")
    connection.executemany(
        "INSERT INTO documents VALUES (?, ?)",
        [(f"doc-{index}", "draft") for index in range(DOCS)],
    )
    connection.commit()
    connection.close()
    (root / "engine" / "jobs" / "job-1" / "result.json").write_text(
        json.dumps({"records": [{"record_id": "r1"}], "tables": []}), encoding="utf-8"
    )
    (root / "engine" / "jobs" / "job-1" / "tablegrid" / "T1.json").write_text(
        json.dumps({"table_id": "T1", "n_rows": 2, "n_cols": 2}), encoding="utf-8"
    )


def _backup_sqlite(source: Path, target: Path) -> dict:
    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(source)
    dst = sqlite3.connect(target)
    src.backup(dst)
    dst.close()
    src.close()
    return {"bytes": target.stat().st_size}


def _tar(source: Path, target: Path) -> dict:
    target.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(target, "w:gz") as archive:
        archive.add(source, arcname="engine")
    return {"bytes": target.stat().st_size}


def _count_documents(root: Path) -> int:
    connection = sqlite3.connect(root / "platform.db")
    try:
        return int(connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0])
    finally:
        connection.close()


def _engine_inventory(root: Path) -> int:
    return len(list(root.rglob("*"))) if root.exists() else 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _step(name: str, detail: dict | int) -> dict:
    return {"step": name, "ok": True, "detail": detail}


def render_markdown(report: dict) -> str:
    lines = [
        "# 备份恢复演练（本地模式 + 加密）",
        "",
        f"- 文档数：{report['documents']}",
        f"- 加密：{report['encryption']}",
        f"- 结果：{'PASS' if report['passed'] else 'FAIL'}",
        "",
        "| 步骤 | 结果 | 详情 |",
        "|---|---|---|",
    ]
    for step in report["steps"]:
        lines.append(f"| {step['step']} | {'OK' if step['ok'] else 'FAIL'} | `{step['detail']}` |")
    lines.extend(
        [
            "",
            "## 校验",
            "",
            f"`{report['checks']}`",
            "",
            "## 限制",
            "",
            *[f"- {item}" for item in report["limitations"]],
            "",
        ]
    )
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
