"""L2 集成链路：Phase 5 任务列表接口与权限（M21）。"""

import asyncio
import time
import uuid


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


async def _upload_wait(client, token, kb_id, name="p5.pdf"):
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=400, height=600)
    page.insert_text((72, 100), "phase5", fontsize=12)
    data = doc.tobytes()
    doc.close()
    resp = await client.post(
        f"/api/v1/kb/{kb_id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (name, data, "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    doc_id = resp.json()["data"]["document"]["id"]
    await client.post(
        f"/api/v1/kb/{kb_id}/documents/{doc_id}/start",
        headers={"Authorization": f"Bearer {token}"},
    )
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


# ---------- L2M21-01 任务列表返回文件名 ----------
async def test_tasks_api_includes_filename(client, super_token):
    kb = await _create_kb(client, super_token, "P5-任务文件名")
    detail = await _upload_wait(client, super_token, kb["id"], "任务文档.pdf")
    h = {"Authorization": f"Bearer {super_token}"}
    tasks = await client.get(
        f"/api/v1/kb/{kb['id']}/documents/tasks?page=1&page_size=20", headers=h
    )
    assert tasks.status_code == 200
    items = tasks.json()["data"]["items"]
    assert len(items) >= 1
    row = next(t for t in items if t["document_id"] == detail["id"])
    assert row["filename"] == "任务文档.pdf"


# ---------- L2M21-02 任务列表权限（viewer 200 / outsider 403） ----------
async def test_tasks_permissions(client, super_token):
    owner_name = await _unique("owner")
    viewer_name = await _unique("viewer")
    outsider_name = await _unique("outsider")
    for name in (owner_name, viewer_name, outsider_name):
        resp = await client.post(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {super_token}"},
            json={"username": name, "password": "Test@1234", "role_codes": ["member"]},
        )
        assert resp.status_code == 200, resp.text
    owner_token = await _login(client, owner_name)
    kb = await _create_kb(client, owner_token, "P5-任务权限")
    viewer_token = await _invite_accept(client, owner_token, kb["id"], viewer_name)
    outsider_token = await _login(client, outsider_name)
    await _upload_wait(client, owner_token, kb["id"])
    assert (
        await client.get(
            f"/api/v1/kb/{kb['id']}/documents/tasks",
            headers={"Authorization": f"Bearer {viewer_token}"},
        )
    ).status_code == 200
    assert (
        await client.get(
            f"/api/v1/kb/{kb['id']}/documents/tasks",
            headers={"Authorization": f"Bearer {outsider_token}"},
        )
    ).status_code == 403
