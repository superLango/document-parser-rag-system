"""L4 边界异常补充：M2 改密、M5 趋势、M9 迁移幂等。"""

import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text


async def test_change_password_empty_new_rejected(client, member_user):
    token, _, _ = member_user
    resp = await client.post(
        "/api/v1/auth/change-password",
        headers={"Authorization": f"Bearer {token}"},
        json={"old_password": "Test@1234", "new_password": ""},
    )
    assert resp.status_code == 400


async def test_trends_days_out_of_range(client, super_token):
    resp = await client.get(
        "/api/v1/dashboard/trends?days=0",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp.status_code == 400
    resp2 = await client.get(
        "/api/v1/dashboard/trends?days=91",
        headers={"Authorization": f"Bearer {super_token}"},
    )
    assert resp2.status_code == 400


async def test_migration_reapply_idempotent(db_session):
    """M9：迁移脚本重复执行必须幂等（数据库层断言）。"""
    backend = Path(__file__).resolve().parents[2] / "backend"
    venv_python = backend / ".venv" / "bin" / "python"
    env = os.environ.copy()
    env["DATABASE_URL"] = "postgresql+asyncpg://postgres@localhost:5432/hanson_doc_rag_test"
    env["PYTHONPATH"] = str(backend)
    for _ in range(2):
        result = subprocess.run(
            [str(venv_python), "-m", "alembic", "upgrade", "head"],
            cwd=str(backend),
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
        assert result.returncode == 0, result.stderr
    # 迁移后系统角色数量保持稳定
    count = (
        await db_session.execute(
            text("SELECT count(*) FROM roles WHERE is_system = true")
        )
    ).scalar_one()
    assert count == 4
