"""L2 集成链路：Phase 1 文档解析任务骨架（M17）。"""

import asyncio
import time
import uuid

from sqlalchemy import text



def _pdf(text: str = "hello") -> bytes:
    """生成真实最小 PDF（Phase 2 起解析管线要求真实 PDF）。"""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=12)
    data = doc.tobytes()
    doc.close()
    return data

async def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _make_user(client, super_token, role_codes=("member",)):
    username = await _unique("docu")
    resp = await client.post(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {super_token}"},
        json={
            "username": username,
            "password": "Test@1234",
            "role_codes": list(role_codes),
        },
    )
    assert resp.status_code == 200, resp.text
    return username, resp.json()["data"]["id"]


async def _login(client, username):
    resp = await client.post(
        "/api/v1/auth/login", json={"username": username, "password": "Test@1234"}
    )
    return resp.json()["data"]["access_token"]


async def _create_kb(client, token, name):
    resp = await client.post(
        "/api/v1/kb",
        headers={"Authorization": f"Bearer {token}"},
        json={"name": name, "domain_code": "general"},
    )
    return resp.json()["data"]


async def _invite_accept(client, owner_token, kb_id, username):
    inv = (
        await client.post(
            f"/api/v1/kb/{kb_id}/invitations",
            headers={"Authorization": f"Bearer {owner_token}"},
            json={"username": username, "role": "viewer"},
        )
    ).json()["data"]
    token = await _login(client, username)
    await client.post(
        f"/api/v1/kb/invitations/{inv['token']}/accept",
        headers={"Authorization": f"Bearer {token}"},
    )
    return token


async def _wait_status(client, token, kb_id, doc_id, target="completed", timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        resp = await client.get(
            f"/api/v1/kb/{kb_id}/documents/{doc_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        status = resp.json()["data"]["process_status"]
        if status == target:
            return resp.json()["data"]
        await asyncio.sleep(0.2)
    raise AssertionError(f"文档未在 {timeout}s 内达到 {target}")


async def test_upload_list_get_tasks_delete_flow(client, super_token):
    token = super_token
    kb = await _create_kb(client, token, "Phase1闭环")
    files = {"file": ("sample.pdf", _pdf("Phase1 flow"), "application/pdf")}
    uploaded = await client.post(
        f"/api/v1/kb/{kb['id']}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files=files,
    )
    assert uploaded.status_code == 200, uploaded.text
    doc = uploaded.json()["data"]["document"]
    task = uploaded.json()["data"]["task"]
    assert doc["status"] == "queued"
    assert task["status"] == "queued"

    detail = await _wait_status(client, token, kb["id"], doc["id"])
    assert detail["status"] == "completed"
    assert detail["process_status"] == "completed"

    listed = await client.get(
        f"/api/v1/kb/{kb['id']}/documents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert listed.status_code == 200
    assert listed.json()["data"]["total"] >= 1
    assert any(i["id"] == doc["id"] for i in listed.json()["data"]["items"])

    tasks = await client.get(
        f"/api/v1/kb/{kb['id']}/documents/tasks?page=1&page_size=5",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert tasks.status_code == 200
    item = next(t for t in tasks.json()["data"]["items"] if t["task_id"] == task["task_id"])
    assert item["status"] == "completed"
    assert item["checkpoint"]["stages"] == ["rendering", "layout", "ocr", "rebuild"]

    deleted = await client.delete(
        f"/api/v1/kb/{kb['id']}/documents/{doc['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert deleted.status_code == 200
    gone = await client.get(
        f"/api/v1/kb/{kb['id']}/documents/{doc['id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert gone.status_code == 400


async def test_document_permissions(client, super_token):
    owner_name, _ = await _make_user(client, super_token)
    viewer_name, _ = await _make_user(client, super_token)
    outsider_name, _ = await _make_user(client, super_token)
    owner_token = await _login(client, owner_name)
    kb = await _create_kb(client, owner_token, "Phase1权限")
    viewer_token = await _invite_accept(client, owner_token, kb["id"], viewer_name)
    outsider_token = await _login(client, outsider_name)

    vh = {"Authorization": f"Bearer {viewer_token}"}
    oh = {"Authorization": f"Bearer {owner_token}"}
    files = {"file": ("v.pdf", _pdf("viewer"), "application/pdf")}
    assert (
        await client.post(f"/api/v1/kb/{kb['id']}/documents", headers=vh, files=files)
    ).status_code == 403
    listed = await client.get(f"/api/v1/kb/{kb['id']}/documents", headers=vh)
    assert listed.status_code == 200  # viewer 可查看

    out_h = {"Authorization": f"Bearer {outsider_token}"}
    assert (
        await client.get(f"/api/v1/kb/{kb['id']}/documents", headers=out_h)
    ).status_code == 403

    up = await client.post(
        f"/api/v1/kb/{kb['id']}/documents", headers=oh, files=files
    )
    assert up.status_code == 200
    doc_id = up.json()["data"]["document"]["id"]
    assert (
        await client.delete(
            f"/api/v1/kb/{kb['id']}/documents/{doc_id}", headers=vh
        )
    ).status_code == 403


async def test_upload_invalid_inputs(client, super_token):
    from app.core.config import settings

    kb = await _create_kb(client, super_token, "Phase1边界")
    h = {"Authorization": f"Bearer {super_token}"}
    bad_type = await client.post(
        f"/api/v1/kb/{kb['id']}/documents",
        headers=h,
        files={"file": ("evil.exe", b"MZ...", "application/octet-stream")},
    )
    assert bad_type.status_code == 400
    empty = await client.post(
        f"/api/v1/kb/{kb['id']}/documents",
        headers=h,
        files={"file": ("empty.pdf", b"", "application/pdf")},
    )
    assert empty.status_code == 400

    original = settings.DOCUMENT_MAX_SIZE_MB
    settings.DOCUMENT_MAX_SIZE_MB = 0
    try:
        big = await client.post(
            f"/api/v1/kb/{kb['id']}/documents",
            headers=h,
            files={"file": ("big.pdf", b"%PDF x", "application/pdf")},
        )
        assert big.status_code == 400
        assert "MB" in big.json()["message"]
    finally:
        settings.DOCUMENT_MAX_SIZE_MB = original


async def test_rls_enforced_for_non_superuser_role(client, super_token, db_session):
    """RLS：连接为 postgres 超管时 RLS 天然绕过；用非超管角色验证 FORCE RLS 强制执行。"""
    import pytest
    from sqlalchemy import insert, text as sa_text
    from sqlalchemy.exc import DBAPIError, ProgrammingError

    from app.models.document import Document

    kb = await _create_kb(client, super_token, "Phase1RLS")
    kb_id = uuid.UUID(kb["id"])
    stmt = insert(Document).values(
        kb_id=kb_id,
        filename="rls.pdf",
        object_key="kb-x/originals/rls.pdf",
        sha256="0" * 64,
    )

    # 幂等创建非超管测试角色
    try:
        await db_session.execute(
            sa_text("CREATE ROLE hansondoc_rls_test NOSUPERUSER LOGIN")
        )
        await db_session.commit()
    except ProgrammingError:
        await db_session.rollback()
    await db_session.execute(sa_text("GRANT USAGE ON SCHEMA public TO hansondoc_rls_test"))
    await db_session.execute(sa_text("GRANT SELECT, INSERT ON documents TO hansondoc_rls_test"))
    await db_session.execute(
        sa_text(
            "GRANT SELECT ON knowledge_bases, kb_members, kb_group_access, group_members "
            "TO hansondoc_rls_test"
        )
    )
    await db_session.commit()

    # 无上下文 + 非超管角色：RLS 拒绝插入
    await db_session.execute(sa_text("SET ROLE hansondoc_rls_test"))
    with pytest.raises(DBAPIError):
        await db_session.execute(stmt)
        await db_session.commit()
    await db_session.rollback()

    # 超管上下文（app.is_superuser=true）：允许
    await db_session.execute(sa_text("RESET ROLE"))
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', 'true', true)"))
    await db_session.execute(
        sa_text("SELECT set_config('app.current_kb', :kb, true)"), {"kb": str(kb_id)}
    )
    await db_session.execute(stmt)
    await db_session.commit()

    # 策略函数：无上下文时有效角色为 NULL
    await db_session.execute(sa_text("RESET ROLE"))
    await db_session.execute(sa_text("SELECT set_config('app.is_superuser', '', true)"))
    await db_session.execute(sa_text("SELECT set_config('app.current_kb', '', true)"))
    role = (
        await db_session.execute(
            sa_text(
                "SELECT hansondoc_kb_effective_role(CAST(:kb AS uuid), CAST(:uid AS uuid))"
            ).bindparams(kb=str(kb_id), uid=str(uuid.uuid4()))
        )
    ).scalar()
    assert role is None


async def test_outbox_claim_and_sync_executor(client, super_token, db_session):
    """Outbox 落库 + sync 执行器闭环；并发 claim 不重复。"""
    from sqlalchemy import delete, select

    from app.core.database import AsyncSessionLocal
    from app.models.document import Document, TaskOutbox
    from app.services import document_service, storage

    await db_session.execute(delete(TaskOutbox).where(TaskOutbox.status == "pending"))
    await db_session.commit()

    kb = await _create_kb(client, super_token, "Phase1队列")
    async with AsyncSessionLocal() as db:
        await db.execute(text("SELECT set_config('app.is_superuser', 'true', true)"))
        await db.execute(
            text("SELECT set_config('app.current_kb', :kb, true)"), {"kb": kb["id"]}
        )
        object_key = await storage.put_original(
            uuid.UUID(kb["id"]), str(uuid.uuid4()), "q.pdf", _pdf("queue")
        )
        doc, task = await document_service.create_document(
            db,
            uuid.UUID(kb["id"]),
            filename="q.pdf",
            file_type="pdf",
            file_size=6,
            sha256="1" * 64,
            object_key=object_key,
        )
        outbox_id = (
            await db.execute(
                select(TaskOutbox).where(TaskOutbox.task_id == task.task_id)
            )
        ).scalar_one()

        # 并发 claim：5 条 outbox，两个 claimer 不重复
        extra = []
        for i in range(4):
            t = str(uuid.uuid4())
            db.add(
                TaskOutbox(
                    task_id=t,
                    type="document_parse",
                    payload={"document_id": str(uuid.uuid4()), "kb_id": kb["id"]},
                    status="pending",
                )
            )
            extra.append(t)
        await db.commit()

        async def _claim():
            async with AsyncSessionLocal() as d:
                return [r.task_id for r in await document_service.claim_outbox(d, limit=10)]

        a, b = await asyncio.gather(_claim(), _claim())
        combined = a + b
        assert len(combined) == len(set(combined)) == 5
        assert task.task_id in combined

        # sync 执行器：完成后 outbox done
        from app.tasks.sync_executor import execute_sync_task

        await execute_sync_task(str(doc.id), kb["id"])
        await db.refresh(doc)
        assert doc.process_status == "completed"
        outbox_done = (
            await db.execute(
                select(TaskOutbox).where(TaskOutbox.id == outbox_id.id)
            )
        ).scalar_one()
        await db.refresh(outbox_done)
        assert outbox_done.status == "done"


async def test_minio_driver(client, super_token):
    """MinIO 驱动集成（真实 MinIO 可用时执行，不可用则跳过）。"""
    import pytest
    from minio.error import S3Error

    from app.services.storage import MinioDriver

    driver = MinioDriver()
    bucket = f"kb-{uuid.uuid4().hex}"
    try:
        driver.put(f"{bucket}/a.txt", b"hello", "text/plain")
        assert driver.get(f"{bucket}/a.txt") == b"hello"
        driver.delete(f"{bucket}/a.txt")
        try:
            driver.get(f"{bucket}/a.txt")
            raise AssertionError("删除后不应存在")
        except S3Error:
            pass
    finally:
        try:
            driver.delete_prefix(f"{bucket}/")
            from minio import Minio

            raw = Minio(
                "127.0.0.1:9000",
                access_key="minioadmin",
                secret_key="minioadmin",
                secure=False,
            )
            raw.remove_bucket(bucket)
        except Exception:
            pass
