"""One-stop integration compatibility layer.

The external system depends on the hansonDoc_RAG contract:

* ``POST /api/v1/integration/upload``
* ``GET  /api/v1/integration/tasks/{task_id}/status``
* ``GET  /api/v1/integration/tasks/{task_id}/result``
* ``POST /api/v1/integration/tasks/{task_id}/retrigger``
* ``GET  /api/v1/integration/tasks/{task_id}/session-token`` (used by the page)

The gateway exposes these paths unchanged; this module implements them on top
of the current document/run model.  ``kb_id``/``prompt_id`` are kept in the
response for compatibility but are only persisted for traceability because the
current platform has no knowledge base.
"""

# ruff: noqa: B008
from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Query, Request, UploadFile
from sqlalchemy import func, select

from .db import SessionLocal
from .idempotency import build_key
from .models import (
    Artifact,
    Document,
    DocumentVersion,
    IntegrationTask,
    Run,
    RunEvent,
    StandardIndex,
)
from .workflow import append_event, get_store, schedule

router = APIRouter(prefix="/internal/integration")

SCHEMA_TEMPLATE_ID = "6e2ad0d7-f92a-4663-b5cf-ae01c2378fa7"
SCHEMA_NAME = "产品标准抽取模板"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
SESSION_TOKEN_MINUTES = 60

SUCCESS_STATES = {
    "REVIEW_PASSED",
    "HUMAN_REVIEW",
    "HUMAN_APPROVED",
    "STRUCTURED_READY",
}
ACTIVE_STATES = {
    "RECEIVED",
    "OCR_RUNNING",
    "OCR_DONE",
    "ROUTING",
    "ROUTED",
    "SANDBOX_RUNNING",
    "PARSED",
    "REVIEWING",
    "REPAIRING",
    "REPARSING",
}
FAILED_STATES = {
    "UNROUTED",
    "REVIEW_FAILED",
    "HUMAN_REJECTED",
    "FAILED",
    "CANCELLED",
}

ITEM_COLUMNS = [
    "项目名称",
    "材料牌号",
    "标准要求",
    "单位",
    "试验方法",
    "试验温度",
    "位置",
    "方向",
    "尺寸厚度",
    "试样状态",
    "取样数量",
    "取样说明",
    "锻件类型",
]
ITEM_CONDITION_KEYS = {
    "试验方法": ["试验方法", "方法", "方法名称"],
    "试验温度": ["试验温度", "温度"],
    "位置": ["位置", "取样位置"],
    "方向": ["方向"],
    "尺寸厚度": ["尺寸厚度", "厚度", "规格"],
    "试样状态": ["试样状态", "状态", "交货状态"],
    "取样数量": ["取样数量", "取样数"],
    "取样说明": ["取样说明"],
    "锻件类型": ["锻件类型"],
}
HEAT_COLUMNS = [
    "工序名称",
    "工艺名称",
    "材料牌号",
    "项目大类",
    "保温温度",
    "保温时间",
    "升温速率",
    "降温速率",
    "装炉温度",
    "出炉温度",
    "冷却介质",
    "介质温度",
]
CATEGORY_ORDER = [
    "标准信息",
    "化学成分",
    "室温拉伸",
    "高温拉伸",
    "冲击试验",
    "硬度试验",
    "弯曲",
    "弯曲试验",
    "平面应变断裂韧度",
    "持久试验",
    "热处理制度",
    "正文/定性项目",
    "其他",
]
HEAT_PROFILE = "heat_treatment"


def _trace_id(request: Request) -> str:
    return request.headers.get("x-request-id") or uuid.uuid4().hex


def _envelope(request: Request, data: Any = None, message: str = "success") -> dict[str, Any]:
    return {
        "code": 0,
        "message": message,
        "data": data,
        "trace_id": _trace_id(request),
    }


def _canonical_uuid(value: str, field: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"{field} 不是合法 UUID") from exc


def _format_id(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return value


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


async def _task_or_404(session, task_id: str) -> IntegrationTask:
    task = await session.get(IntegrationTask, _canonical_uuid(task_id, "task_id"))
    if task is None:
        raise IntegrationError(404, "对接任务不存在")
    return task


async def _row_for_task(
    session, task: IntegrationTask
) -> tuple[Document | None, Run | None, int | None]:
    document = await session.get(Document, task.document_id)
    if document is None:
        return None, None, None
    result = await session.execute(
        select(Run)
        .where(Run.document_id == document.id)
        .order_by(Run.created_at.desc(), Run.id.desc())
    )
    runs = list(result.scalars())
    run = runs[0] if runs else None
    if run is None:
        return document, None, None
    ascending = await session.execute(
        select(Run.id)
        .where(Run.document_id == document.id)
        .order_by(Run.created_at, Run.id)
    )
    ids = list(ascending.scalars())
    version = ids.index(run.id) + 1 if run.id in ids else None
    return document, run, version


def _state_values(run: Run | None) -> tuple[str, str, int, int, str]:
    """Map the current run state machine onto the legacy OCR/extract pair."""
    if run is None:
        return "pending", "pending", 0, 0, ""
    status = run.status
    progress = max(0, min(100, int(run.progress or 0)))
    if status in SUCCESS_STATES:
        return "completed", "completed", 100, 100, ""
    if status in FAILED_STATES:
        ocr_done = progress >= 25
        error = run.error_code or ("任务已取消" if status == "CANCELLED" else "解析失败")
        return (
            "completed" if ocr_done else "failed",
            "failed" if ocr_done else "pending",
            100 if ocr_done else progress,
            progress if ocr_done else 0,
            error,
        )
    if status == "RECEIVED":
        return "pending", "pending", 0, 0, ""
    if status == "OCR_RUNNING":
        ocr_progress = min(99, max(1, round(progress / 25 * 100)))
        return "processing", "pending", ocr_progress, 0, ""
    if status == "OCR_DONE":
        return "completed", "pending", 100, 0, ""
    if status in {"ROUTING", "ROUTED"}:
        return "completed", "pending", 100, 0, ""
    extract_progress = min(99, max(1, round((progress - 25) / 70 * 100)))
    return "completed", "running", 100, extract_progress, ""


def _task_view(
    task: IntegrationTask,
    document: Document | None,
    run: Run | None,
    version: int | None,
) -> dict[str, Any]:
    ocr_status, extract_status, ocr_progress, extract_progress, error = _state_values(run)
    updated = task.updated_at
    if run is not None:
        for value in (run.finished_at, run.started_at, run.created_at):
            if value and (updated is None or value > updated):
                updated = value
    return {
        "task_id": task.task_id,
        "kb_id": _format_id(task.kb_id),
        "document_id": _format_id(document.id if document else task.document_id),
        "prompt_id": task.prompt_id,
        "schema_template_id": task.schema_template_id,
        "filename": task.filename,
        "ocr_status": ocr_status,
        "ocr_progress": ocr_progress,
        "extract_status": extract_status,
        "extract_progress": extract_progress,
        "error": error,
        "result_version": version,
        "created_at": _iso(task.created_at),
        "updated_at": _iso(updated),
    }


def _display_requirement(prop: dict[str, Any]) -> str:
    raw = str(prop.get("raw") or ("" if prop.get("value") is None else prop.get("value")))
    operator = str(prop.get("operator") or "").strip()
    if not raw or not operator:
        return raw
    if operator in {"text", "~", "～", "range"}:
        return raw
    if re.search(r"[≥≤<>~～]", raw) or re.search(r"\d\s*[-–—]\s*\d", raw):
        return raw
    return f"{operator}{raw}"


def _category_of(record: dict[str, Any]) -> str:
    profile = str(record.get("profile") or "")
    if profile == "qualitative":
        return "正文/定性项目"
    if profile == "chemical_composition":
        return "化学成分"
    if profile == HEAT_PROFILE:
        return "热处理制度"
    if profile != "mechanical_properties":
        return "其他"
    keys = set((record.get("properties") or {}).keys())
    if keys & {"KV2", "KU2", "KV8", "KU8", "冲击吸收能量", "侧向膨胀值"}:
        return "冲击"
    if keys & {"HB", "HBW", "HBS"}:
        return "布氏硬度"
    if keys & {"HRC", "HRB"}:
        return "洛氏硬度"
    if "HV" in keys:
        return "维氏硬度"
    if keys & {"KIC", "断裂韧度"}:
        return "断裂韧度"
    if keys & {"持久应力", "初始应力", "持久时间", "持久强度"}:
        return "高温持久"
    if any("弯曲" in key or key.lower().startswith("bend") for key in keys):
        return "弯曲"
    conditions = record.get("conditions") or {}
    temperature = str(conditions.get("试验温度") or conditions.get("温度") or "")
    match = re.search(r"(\d{2,4})\s*(?:℃|°C)", temperature)
    if match and int(match.group(1)) >= 100:
        return "高温拉伸"
    return "室温拉伸"


def _property_category(record: dict[str, Any], prop: dict[str, Any]) -> str:
    category = str(prop.get("business_category") or "").strip()
    if category:
        return category
    feature = str(prop.get("feature") or "").strip()
    if feature and prop.get("feature_in_dictionary") is False:
        return feature
    return _category_of(record)


def _condition_value(fields: dict[str, Any], keys: list[str]) -> str:
    for key in keys:
        value = fields.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def _item_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows_by_category: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if str(record.get("profile") or "") == HEAT_PROFILE:
            continue
        conditions = record.get("conditions") or {}
        for measure, prop in (record.get("properties") or {}).items():
            if not isinstance(prop, dict):
                continue
            requirement = _display_requirement(prop)
            unit = str(prop.get("unit") or "")
            if not requirement and not unit:
                continue
            fields = {**conditions, **(prop.get("meta") or {})}
            category = _property_category(record, prop)
            row: dict[str, Any] = {
                "项目名称": str(prop.get("business_item") or measure),
                "材料牌号": str(record.get("grade") or ""),
                "标准要求": requirement,
                "单位": unit,
            }
            for column in ITEM_COLUMNS[4:]:
                row[column] = _condition_value(fields, ITEM_CONDITION_KEYS[column])
            rows_by_category.setdefault(category, []).append(row)
    return _as_categories(rows_by_category)


def _heat_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows_by_category: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if str(record.get("profile") or "") != HEAT_PROFILE:
            continue
        conditions = record.get("conditions") or {}
        properties = record.get("properties") or {}
        row: dict[str, Any] = {}
        for column in HEAT_COLUMNS:
            if column == "工序名称":
                row[column] = str(conditions.get("工序名称") or conditions.get("工序") or "")
            elif column == "工艺名称":
                craft = properties.get("工艺名称")
                if isinstance(craft, dict):
                    row[column] = str(craft.get("raw") or craft.get("value") or "")
                else:
                    row[column] = str(conditions.get("工艺名称") or "")
            elif column == "材料牌号":
                row[column] = str(record.get("grade") or "")
            elif column == "项目大类":
                row[column] = str(conditions.get("项目大类") or "热处理制度")
            else:
                prop = properties.get(column)
                if isinstance(prop, dict):
                    raw = prop.get("raw")
                    if raw in (None, ""):
                        raw = prop.get("value")
                    unit = str(prop.get("unit") or "")
                    value = raw if raw is not None else ""
                    row[column] = f"{value}{(' ' + unit) if unit else ''}".strip()
                else:
                    row[column] = str(conditions.get(column) or "")
        rows_by_category.setdefault("热处理制度", []).append(row)
    return _as_categories(rows_by_category)


def _as_categories(rows_by_category: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    categories = [
        {
            "feature": category,
            "records": rows,
            "rejected": [],
            "missing_fields": [],
            "hit_count": len(rows),
        }
        for category, rows in rows_by_category.items()
        if rows
    ]

    def rank(item: dict[str, Any]) -> int:
        try:
            return CATEGORY_ORDER.index(str(item["feature"]))
        except ValueError:
            return len(CATEGORY_ORDER)

    return sorted(categories, key=rank)


async def _load_artifact(run_id: str, role: str) -> dict[str, Any] | None:
    async with SessionLocal() as session:
        result = await session.execute(
            select(Artifact)
            .where(Artifact.run_id == run_id, Artifact.role == role)
            .order_by(Artifact.created_at.desc())
        )
        artifact = result.scalars().first()
    if artifact is None:
        return None
    data = await get_store().get_bytes(artifact.storage_key)
    payload = json.loads(data.decode("utf-8"))
    return payload if isinstance(payload, dict) else None


STANDARD_RE = re.compile(
    r"(GB\s*[/_-]?\s*T|GBT|GB|GJB|JB|HB|YS\s*[/_-]?\s*T|YST|YB|ASTM|ASME|AMS|ISO|EN|DIN|API|NB)"
    r"[\s_-]*([A-Z]{0,2})[\s_-]*(\d+(?:\.\d+)?)"
    r"(?:[\s_-]+(\d{4}|[A-Z]|\d{2})|([A-Z]))?",
    re.I,
)
PARTS_RE = re.compile(
    r"(ISO|EN|DIN)[\s_-]*(\d+(?:\.\d+)?)[\s_-]*-[\s_-]*(\d+)(?:[\s_-]+(\d{4}))?",
    re.I,
)


def _filename_standard(filename: str) -> tuple[str, str]:
    stem = re.sub(r"\.(pdf|md|markdown|txt)$", "", filename or "", flags=re.I)
    stem = re.sub(r"[-_—]?过期$", "", stem)
    parts = PARTS_RE.search(stem)
    if parts:
        prefix = parts.group(1).upper()
        edition = f"-{parts.group(4)}" if parts.group(4) else ""
        number = f"{prefix} {parts.group(2)}-{parts.group(3)}{edition}"
        rest = stem[parts.end() :]
        title = rest.lstrip(" -_—:：").strip()
        return number, title
    match = STANDARD_RE.search(stem)
    if not match:
        return "", stem
    prefix = re.sub(r"\s+", "", match.group(1)).upper()
    if prefix.startswith("GB") and prefix.endswith("T"):
        prefix = "GB/T"
    if prefix.startswith("YS") and prefix.endswith("T"):
        prefix = "YS/T"
    letter = (match.group(2) or "").upper()
    edition = f"-{match.group(4).upper()}" if match.group(4) else ""
    attached = (match.group(5) or "").upper()
    number = f"{prefix} {letter}{match.group(3)}{edition}{attached}".strip()
    rest = stem[match.end() :]
    title = rest.lstrip(" -_—:：").strip()
    return number, title


async def _standard_info(
    document_id: str, filename: str
) -> dict[str, str] | None:
    async with SessionLocal() as session:
        result = await session.execute(
            select(StandardIndex).where(StandardIndex.document_id == document_id)
        )
        row = result.scalars().first()
    number = (row.standard_no if row else "") or ""
    edition = (row.edition if row else "") or ""
    if number and edition and not number.endswith(edition):
        number = f"{number}-{edition}"
    title = (row.title if row else "") or ""
    # 索引标题偶尔只落到了年份（例如 "2018"），此时退回文件名。
    plausible = len(title) >= 4 and not re.fullmatch(r"[\d\s.\-—]+", title)
    fallback_number, fallback_title = _filename_standard(filename)
    if not number:
        number = fallback_number
    if not plausible:
        if fallback_number:
            number = fallback_number
        title = fallback_title or ""
    if not number and not title:
        return None
    return {"标准名称": title or number, "标准编号": number}


async def _effective_end(run: Run) -> datetime | None:
    if run.finished_at is not None:
        return run.finished_at
    async with SessionLocal() as session:
        result = await session.execute(
            select(func.max(RunEvent.occurred_at)).where(RunEvent.run_id == run.id)
        )
        return result.scalar()


async def _create_run(document_id: str, sha256: str, prefix: str) -> Run:
    key = build_key(
        prefix=prefix,
        document_id=document_id,
        sha256=sha256,
        channel="stable",
        parser_version=None,
    )
    async with SessionLocal() as session:
        run = Run(
            document_id=document_id,
            document_version=1,
            status="RECEIVED",
            stage="RECEIVED",
            trace_id=str(uuid.uuid4()),
            recipe_channel="stable",
            idempotency_key=key,
        )
        session.add(run)
        await session.flush()
        await append_event(
            session,
            run,
            "run.created",
            "RECEIVED",
            "created",
            {
                "document_id": document_id,
                "document_sha256": sha256,
                "recipe_channel": "stable",
                "parser_version": None,
                "source": "integration",
            },
        )
        await session.commit()
    schedule(run.id)
    return run


class IntegrationError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.message = message


@router.post("/upload")
async def integration_upload(
    request: Request,
    file: UploadFile = File(...),
    kb_id: str = Query(...),
    prompt_id: str = Query(...),
) -> dict[str, Any]:
    try:
        kb_value = _canonical_uuid(kb_id, "kb_id")
        prompt_value = _canonical_uuid(prompt_id, "prompt_id")
    except ValueError as exc:
        raise IntegrationError(400, str(exc)) from exc

    filename = Path(file.filename or "document.pdf").name
    if not filename.lower().endswith(".pdf"):
        raise IntegrationError(400, "仅支持 PDF 文件")
    if len(filename.encode("utf-8")) > 255:
        raise IntegrationError(400, "文件名过长")
    data = await file.read()
    if not data:
        raise IntegrationError(400, "文件为空")
    if len(data) > MAX_UPLOAD_BYTES:
        raise IntegrationError(413, "文件超过大小限制")

    sha256 = hashlib.sha256(data).hexdigest()
    content_type = file.content_type or "application/pdf"
    async with SessionLocal() as session:
        found = await session.execute(select(Document).where(Document.sha256 == sha256))
        document = found.scalars().first()
        if document is None:
            document_id = str(uuid.uuid4())
            storage_key = f"documents/{document_id}/{filename}"
            await get_store().put_bytes(storage_key, data, content_type)
            document = Document(
                id=document_id,
                filename=filename,
                content_type=content_type,
                size=len(data),
                sha256=sha256,
                storage_key=storage_key,
            )
            session.add(document)
            session.add(
                DocumentVersion(
                    document_id=document_id,
                    version=1,
                    storage_key=storage_key,
                    sha256=sha256,
                )
            )
            await session.flush()

        task = IntegrationTask(
            task_id=str(uuid.uuid4()),
            kb_id=kb_value,
            prompt_id=prompt_value,
            document_id=document.id,
            schema_template_id=SCHEMA_TEMPLATE_ID,
            filename=filename,
        )
        session.add(task)
        await session.commit()
        document_id = document.id
        task_id = task.task_id

    await _create_run(document_id, sha256, f"integration-upload-{task_id}")
    async with SessionLocal() as session:
        task = await session.get(IntegrationTask, task_id)
        document = await session.get(Document, document_id)
        _, run, version = await _row_for_task(session, task)
        view = _task_view(task, document, run, version)
    return _envelope(
        request,
        view,
        "任务已创建，正在异步执行 OCR 解析与结构化抽取",
    )


@router.get("/tasks/{task_id}/status")
async def integration_status(request: Request, task_id: str) -> dict[str, Any]:
    try:
        async with SessionLocal() as session:
            task = await _task_or_404(session, task_id)
            document, run, version = await _row_for_task(session, task)
            view = _task_view(task, document, run, version)
    except ValueError as exc:
        raise IntegrationError(400, str(exc)) from exc
    return _envelope(request, view)


@router.get("/tasks/{task_id}/result")
async def integration_result(request: Request, task_id: str) -> dict[str, Any]:
    try:
        async with SessionLocal() as session:
            task = await _task_or_404(session, task_id)
            document, run, version = await _row_for_task(session, task)
    except ValueError as exc:
        raise IntegrationError(400, str(exc)) from exc
    if document is None or run is None:
        return _envelope(request, None)

    status = "completed" if run.status in SUCCESS_STATES else (
        "failed" if run.status in FAILED_STATES else "running"
    )
    base: dict[str, Any] = {
        "schema_template_id": SCHEMA_TEMPLATE_ID,
        "schema_name": SCHEMA_NAME,
        "status": status,
        "progress": int(run.progress or 0),
        "categories": [],
        "summary": {},
        "timing": {},
        "version": version,
        "error": run.error_code if status == "failed" else None,
        "updated_at": _iso(run.finished_at or run.started_at or run.created_at),
    }
    if status != "completed":
        return _envelope(request, base)

    payload = await _load_artifact(run.id, "records")
    records = list((payload or {}).get("records") or [])
    categories = _item_rows(records) + _heat_rows(records)
    standard = await _standard_info(document.id, task.filename)
    if standard is not None:
        categories.insert(
            0,
            {
                "feature": "标准信息",
                "records": [standard],
                "rejected": [],
                "missing_fields": [],
                "hit_count": 1,
            },
        )
    total = sum(len(category["records"]) for category in categories)
    timing: dict[str, Any] = {}
    end = await _effective_end(run)
    if run.started_at and end:
        timing = {"total_sec": round((end - run.started_at).total_seconds(), 2)}
    base.update(
        {
            "status": "completed",
            "progress": 100,
            "categories": categories,
            "summary": {
                "total_records": total,
                "kept_categories": sum(1 for category in categories if category["records"]),
            },
            "timing": timing,
            "error": None,
        }
    )
    return _envelope(request, base)


@router.post("/tasks/{task_id}/retrigger")
async def integration_retrigger(request: Request, task_id: str) -> dict[str, Any]:
    try:
        async with SessionLocal() as session:
            task = await _task_or_404(session, task_id)
            document, run, _ = await _row_for_task(session, task)
    except ValueError as exc:
        raise IntegrationError(400, str(exc)) from exc
    if document is None:
        raise IntegrationError(400, "任务无关联文档，无法重触发")
    if run is not None and run.status in ACTIVE_STATES:
        raise IntegrationError(409, "任务正在解析中，请稍后再试")

    await _create_run(
        document.id,
        document.sha256,
        f"integration-retrigger-{task_id}-{uuid.uuid4().hex}",
    )
    async with SessionLocal() as session:
        task = await session.get(IntegrationTask, task.task_id)
        task.updated_at = datetime.now(UTC)
        await session.commit()
        document = await session.get(Document, document.id)
        _, latest, version = await _row_for_task(session, task)
        view = _task_view(task, document, latest, version)
    return _envelope(request, view, "任务已重新触发")


@router.get("/tasks/{task_id}/session-token")
async def integration_session_token(request: Request, task_id: str) -> dict[str, Any]:
    try:
        async with SessionLocal() as session:
            task = await _task_or_404(session, task_id)
            document, _, _ = await _row_for_task(session, task)
    except ValueError as exc:
        raise IntegrationError(400, str(exc)) from exc
    if document is None:
        raise IntegrationError(404, "任务无关联文档")
    token = hashlib.sha256(f"{task.task_id}:{document.sha256}".encode()).hexdigest()[:32]
    expires = datetime.now(UTC) + timedelta(minutes=SESSION_TOKEN_MINUTES)
    return _envelope(
        request,
        {
            "task_id": task.task_id,
            "token": token,
            "document_id": _format_id(document.id),
            "kb_id": _format_id(task.kb_id),
            "expires_at": expires.isoformat(),
            "path": f"/integration/task/{task.task_id}",
        },
        "会话令牌已签发",
    )
