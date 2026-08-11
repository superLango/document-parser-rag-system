"""L5 安全渗透：Phase 1-6 整体验收（M23）。"""

from pathlib import Path

import asyncio
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]


async def _unique(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _login(client, username, password="Test@1234"):
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]["access_token"]


async def _create_kb(client, token, name):
    resp = await client.post(
        "/api/v1/kb",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name, "domain_code": "general"},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def _invite_accept(client, owner_token, kb_id, username, role="viewer"):
    inv = (
        await client.post(
            f"/api/v1/kb/{kb_id}/invitations",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"username": username, "role": role},
        )
    ).json()["data"]
    token = await _login(client, username)
    await client.post(
        f"/api/v1/kb/invitations/{inv['token']}/accept",
        headers={"Authorization": f"Bearer {token}"},
    )
    return token


async def _upload_wait(client, token, kb_id, name="sec.pdf"):
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=400, height=600)
    page.insert_text((72, 100), "security overall", fontsize=12)
    data = doc.tobytes()
    doc.close()
    resp = await client.post(
        f"/api/v1/kb/{kb_id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (name, data, "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    doc_id = resp.json()["data"]["document"]["id"]
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        detail = (
            await client.get(
                f"/api/v1/kb/{kb_id}/documents/{doc_id}",
                headers={"Authorization": f"Bearer {token}"},
            )
        ).json()["data"]
        if detail["status"] in ("completed", "failed"):
            return detail
        await asyncio.sleep(0.2)
    raise AssertionError("未完成")


# ---------- L5M23-01 外部人访问全部产物端点 403 ----------
async def test_outsider_all_artifacts_forbidden(client, super_token):
    owner_name = await _unique("owner")
    outsider_name = await _unique("outsider")
    for name in (owner_name, outsider_name):
        resp = await client.post(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {super_token}"},
            json={"username": name, "password": "Test@1234", "role_codes": ["member"]},
        )
        assert resp.status_code == 200, resp.text
    owner_token = await _login(client, owner_name)
    kb = await _create_kb(client, owner_token, "M23-安全外部")
    detail = await _upload_wait(client, owner_token, kb["id"])
    outsider_token = await _login(client, outsider_name)
    oh = {"Authorization": f"Bearer {outsider_token}"}
    for suffix in ("markdown", "layout", "pages/1"):
        resp = await client.get(
            f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/{suffix}", headers=oh
        )
        assert resp.status_code == 403, suffix
    assert (
        await client.get(
            f"/api/v1/kb/{kb['id']}/documents/tasks", headers=oh
        )
    ).status_code == 403


# ---------- L5M23-02 pending 用户 403 ----------
async def test_pending_user_forbidden(client, super_token):
    from app.core.config import settings

    kb = await _create_kb(client, super_token, "M23-安全pending")
    detail = await _upload_wait(client, super_token, kb["id"])
    original = settings.REGISTRATION_DEFAULT_PENDING
    settings.REGISTRATION_DEFAULT_PENDING = True
    try:
        username = await _unique("pend")
        await client.post(
            "/api/v1/auth/register",
            json={"username": username, "password": "Test@1234"},
        )
        token = await _login(client, username)
        ph = {"Authorization": f"Bearer {token}"}
        for suffix in ("markdown", "layout", "pages/1"):
            resp = await client.get(
                f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/{suffix}", headers=ph
            )
            assert resp.status_code == 403, suffix
    finally:
        settings.REGISTRATION_DEFAULT_PENDING = original


# ---------- L5M23-03 RLS 直接查询拒绝 ----------
async def test_rls_direct_query_denied(client, super_token, db_session):
    from sqlalchemy import text as sa_text
    from sqlalchemy.exc import ProgrammingError

    kb = await _create_kb(client, super_token, "M23-RLS")
    await _upload_wait(client, super_token, kb["id"])
    try:
        await db_session.execute(
            sa_text("CREATE ROLE hansondoc_overall_rls NOSUPERUSER LOGIN")
        )
        await db_session.commit()
    except ProgrammingError:
        await db_session.rollback()
    await db_session.execute(sa_text("GRANT USAGE ON SCHEMA public TO hansondoc_overall_rls"))
    await db_session.execute(sa_text("GRANT SELECT ON documents TO hansondoc_overall_rls"))
    await db_session.execute(
        sa_text(
            "GRANT SELECT ON knowledge_bases, kb_members, kb_group_access, group_members "
            "TO hansondoc_overall_rls"
        )
    )
    await db_session.commit()
    await db_session.execute(sa_text("SET ROLE hansondoc_overall_rls"))
    rows = (await db_session.execute(sa_text("SELECT id FROM documents"))).all()
    assert rows == []
    await db_session.execute(sa_text("RESET ROLE"))


# ---------- L5M23-04 删除后产物/页面不可读且存储清理 ----------
async def test_delete_removes_all_artifacts(client, super_token):
    from pathlib import Path

    from app.core.config import settings

    kb = await _create_kb(client, super_token, "M23-删除清理")
    detail = await _upload_wait(client, super_token, kb["id"])
    h = {"Authorization": f"Bearer {super_token}"}
    base = detail["markdown_path"].rsplit("/result.md", 1)[0]
    pages_dir = Path(settings.LOCAL_STORAGE_DIR) / f"{base}/pages/"
    assert pages_dir.exists()
    resp = await client.delete(
        f"/api/v1/kb/{kb['id']}/documents/{detail['id']}", headers=h
    )
    assert resp.status_code == 200
    for suffix in ("markdown", "layout", "pages/1"):
        resp = await client.get(
            f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/{suffix}", headers=h
        )
        assert resp.status_code == 400, suffix
    assert not pages_dir.exists()


# ---------- L5M23-05 评测 CLI 越界拒绝与报告无泄露 ----------
async def test_evaluation_cli_safety():
    import shutil
    import tempfile

    from qa.evaluation import evaluate_phase6

    out_escape = tempfile.mkdtemp()
    try:
        rc = evaluate_phase6.main(
            ["--subset", "smoke", "--skip-ocr", "--output-dir", out_escape]
        )
        assert rc == 2
    finally:
        shutil.rmtree(out_escape, ignore_errors=True)

    out_dir = ROOT / "qa" / "evaluation" / "reports" / "pytest_sec_overall"
    try:
        rc = evaluate_phase6.main(
            ["--subset", "smoke", "--skip-ocr", "--output-dir", str(out_dir)]
        )
        assert rc == 0
        md = (out_dir / "phase6_report.md").read_text(encoding="utf-8")
        assert "/home/" not in md and "/tmp/" not in md
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)
