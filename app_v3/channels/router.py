"""S13 通道路由：按"覆盖代理（记录数/唯一键）"选择 S9 或全链路重绑定结果。

原则：不使用金标；仅用文档自身的记录覆盖与验证器状态做路由。
"""
from __future__ import annotations

import json
from typing import Any

from app_v3.verify.pipeline import verify_records


def record_keys(records: list[dict[str, Any]]) -> set[tuple]:
    keys: set[tuple] = set()
    for record in records:
        keys.add((
            str(record.get("category") or ""),
            str(record.get("item") or ""),
            str(record.get("grade") or ""),
            json.dumps(record.get("conditions") or {}, sort_keys=True, ensure_ascii=False),
        ))
    return keys


def verification_score(records: list[dict[str, Any]], ocr: dict[str, Any] | None) -> dict[str, Any]:
    result = verify_records(records, ocr)
    total = result["summary"]["total"] or 1
    status = result["summary"]["status"]
    ok = status.get("ok", 0)
    warn = status.get("warn", 0)
    unresolved = status.get("unresolved", 0)
    score = round(ok / total - 0.5 * unresolved / total - 0.1 * warn / total, 4)
    return {"score": score, "ok": ok, "warn": warn, "unresolved": unresolved, "total": total}


def choose_channel(s9_records: list[dict[str, Any]], full_records: list[dict[str, Any]],
                   ocr: dict[str, Any] | None, min_gain: float = 1.05) -> dict[str, Any]:
    """覆盖代理：全链路唯一键数显著多于 S9 时选全链路；否则 S9。

    约定：更完整的记录集合优先；验证器分数仅记录，不作为否决条件（避免漏掉有效覆盖）。
    """
    s9_keys = record_keys(s9_records)
    full_keys = record_keys(full_records)
    gain = round(len(full_keys) / len(s9_keys), 3) if s9_keys else 99.0
    s9 = verification_score(s9_records, ocr)
    full = verification_score(full_records, ocr)
    if gain >= min_gain:
        channel = "full_rebind"
        records = full_records
    else:
        channel = "s9"
        records = s9_records
    return {
        "channel": channel,
        "coverage_gain": gain,
        "s9_keys": len(s9_keys),
        "full_keys": len(full_keys),
        "s9_score": s9,
        "full_score": full,
        "records": records,
    }


def filter_recovery_unresolved(records: list[dict[str, Any]], ocr: dict[str, Any] | None) -> list[dict[str, Any]]:
    """仅丢弃 recovered/rebind 通道中验证为 unresolved 的记录；保留原始 v2 记录。"""
    result = verify_records(records, ocr)
    kept: list[dict[str, Any]] = []
    for record in result["records"]:
        channel = str(record.get("channel") or "")
        status = str((record.get("verification") or {}).get("status") or "")
        if channel in {"recovered", "rebind"} and status == "unresolved":
            continue
        kept.append(record)
    return kept
