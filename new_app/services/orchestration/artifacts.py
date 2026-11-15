"""Run artifact helpers shared by feedback, shadow and run-diff code."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select

from .db import SessionLocal
from .models import Artifact
from .workflow import get_store


async def artifact_json(run_id: str, role: str) -> dict[str, Any] | None:
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
    payload = json.loads(data)
    return payload if isinstance(payload, dict) else None
