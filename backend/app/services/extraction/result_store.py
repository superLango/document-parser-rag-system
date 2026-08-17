"""抽取结果存储：最新结果 + 历史归档（E1）。

- 每文档最新一条 extraction_results；
- 完成时旧版本归档到 extraction_history（保留最近 50 条）；
- 删除时清空最新结果与历史并重置 documents.extraction_status。
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.document import Document
from app.models.extraction import ExtractionHistory, ExtractionResult

HISTORY_LIMIT = 50


def _now() -> datetime:
    return datetime.now(timezone.utc)


def to_simple_view(result: dict) -> dict:
    """完整抽取结果 → 简化视图：categories 仅保留 feature + result（记录数组）。"""
    return {
        "categories": [
            {"feature": cat.get("feature", ""), "result": cat.get("records") or []}
            for cat in (result.get("categories") or [])
        ]
    }


async def get_latest(db: AsyncSession, kb_id, document_id) -> ExtractionResult | None:
    return (
        await db.execute(
            select(ExtractionResult).where(
                ExtractionResult.kb_id == kb_id,
                ExtractionResult.document_id == document_id,
            )
        )
    ).scalar_one_or_none()


async def _archive_latest(db: AsyncSession, row: ExtractionResult | None) -> None:
    """将最新结果归档到历史（仅 completed 才归档），并裁剪超限历史。"""
    if row is None or row.status != "completed":
        return
    db.add(ExtractionHistory(
        kb_id=row.kb_id,
        document_id=row.document_id,
        schema_template_id=row.schema_template_id,
        schema_name=row.schema_name,
        categories=row.categories or [],
        summary=row.summary or {},
        timing=row.timing or {},
        version=row.version,
        extracted_at=row.updated_at or row.created_at or _now(),
        archived_at=_now(),
    ))
    # autoflush=False：先 flush 再统计，保证裁剪包含刚归档行
    await db.flush()
    # 保留最近 HISTORY_LIMIT 条
    stale_ids = (
        await db.execute(
            select(ExtractionHistory.id)
            .where(
                ExtractionHistory.kb_id == row.kb_id,
                ExtractionHistory.document_id == row.document_id,
            )
            .order_by(ExtractionHistory.archived_at.desc(), ExtractionHistory.id.desc())
            .offset(HISTORY_LIMIT)
        )
    ).scalars().all()
    if stale_ids:
        await db.execute(
            delete(ExtractionHistory).where(ExtractionHistory.id.in_(list(stale_ids)))
        )


async def save_result(
    db: AsyncSession,
    kb_id,
    document_id,
    *,
    schema_template_id=None,
    schema_name="",
    categories=None,
    summary=None,
    timing=None,
    error=None,
    status="completed",
    progress=100,
) -> ExtractionResult:
    """保存抽取结果：旧版本归档 → upsert 最新 → 更新文档抽取状态。"""
    old = await get_latest(db, kb_id, document_id)
    if status == "completed":
        await _archive_latest(db, old)
    new_version = (old.version if old else 0) + 1
    if old is None:
        row = ExtractionResult(
            kb_id=kb_id,
            document_id=document_id,
            schema_template_id=schema_template_id,
            schema_name=schema_name or "",
            status=status,
            progress=progress,
            categories=categories or [],
            summary=summary or {},
            timing=timing or {},
            error=error,
            version=new_version,
        )
        db.add(row)
    else:
        old.schema_template_id = schema_template_id
        old.schema_name = schema_name or old.schema_name
        old.status = status
        old.progress = progress
        old.categories = categories or []
        old.summary = summary or {}
        old.timing = timing or {}
        old.error = error
        old.version = new_version
        old.updated_at = _now()
        row = old
    doc = (
        await db.execute(
            select(Document).where(
                Document.id == document_id, Document.kb_id == kb_id
            )
        )
    ).scalar_one_or_none()
    if doc is not None:
        doc.extraction_status = status
    await db.commit()
    await db.refresh(row)
    return row


async def set_result_status(
    db: AsyncSession,
    kb_id,
    document_id,
    *,
    status: str,
    progress: int,
    error=None,
) -> ExtractionResult:
    """更新进行中/失败状态（不归档）。"""
    row = await get_latest(db, kb_id, document_id)
    if row is None:
        row = ExtractionResult(
            kb_id=kb_id,
            document_id=document_id,
            status=status,
            progress=progress,
            categories=[],
            summary={},
            timing={},
            error=error,
            version=1,
        )
        db.add(row)
    else:
        row.status = status
        row.progress = progress
        row.error = error
        row.updated_at = _now()
    doc = (
        await db.execute(
            select(Document).where(
                Document.id == document_id, Document.kb_id == kb_id
            )
        )
    ).scalar_one_or_none()
    if doc is not None:
        doc.extraction_status = status
    await db.commit()
    await db.refresh(row)
    return row


async def list_history(db: AsyncSession, kb_id, document_id) -> list[dict]:
    rows = (
        await db.execute(
            select(ExtractionHistory)
            .where(
                ExtractionHistory.kb_id == kb_id,
                ExtractionHistory.document_id == document_id,
            )
            .order_by(ExtractionHistory.archived_at.desc())
        )
    ).scalars().all()
    return [
        {
            "id": str(r.id),
            "schema_template_id": str(r.schema_template_id) if r.schema_template_id else None,
            "schema_name": r.schema_name,
            "categories": r.categories or [],
            "summary": r.summary or {},
            "timing": r.timing or {},
            "version": r.version,
            "extracted_at": r.extracted_at.isoformat(),
            "archived_at": r.archived_at.isoformat(),
        }
        for r in rows
    ]


async def delete_result_and_history(db: AsyncSession, kb_id, document_id) -> None:
    """删除最新结果与全部历史，并重置文档抽取状态。"""
    await db.execute(
        delete(ExtractionResult).where(
            ExtractionResult.kb_id == kb_id,
            ExtractionResult.document_id == document_id,
        )
    )
    await db.execute(
        delete(ExtractionHistory).where(
            ExtractionHistory.kb_id == kb_id,
            ExtractionHistory.document_id == document_id,
        )
    )
    doc = (
        await db.execute(
            select(Document).where(
                Document.id == document_id, Document.kb_id == kb_id
            )
        )
    ).scalar_one_or_none()
    if doc is not None:
        doc.extraction_status = None
    await db.commit()


async def history_count(db: AsyncSession, kb_id, document_id) -> int:
    return int(
        (
            await db.execute(
                select(func.count()).select_from(ExtractionHistory).where(
                    ExtractionHistory.kb_id == kb_id,
                    ExtractionHistory.document_id == document_id,
                )
            )
        ).scalar_one()
    )
