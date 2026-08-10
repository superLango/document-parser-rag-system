"""L2 集成链路：Phase 2 文档解析管线（M18）。"""

import asyncio
import time
import uuid
from pathlib import Path

TEST_DOC = Path(__file__).resolve().parents[2] / "test_doc"

SAMPLES = [
    "462a2e2857face94b2c800d3a8492740.pdf",
    "GB-T1220-2007 不锈钢棒.pdf",
    "GJB3325A-2019.pdf",
    "LSAM-JD01-0016  优质GH4169合金锻制棒材.pdf",
    "a62820a10c1c33f40ede554498d7bdf1.pdf",
    "c8f1e134282d41dcc40b5243f4e9a98d.pdf",
]


async def _unique(prefix: str) -> str:
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


async def _upload(client, token, kb_id, name, data):
    resp = await client.post(
        f"/api/v1/kb/{kb_id}/documents",
        headers={"Authorization": f"Bearer {token}"},
        files={"file": (name, data, "application/pdf")},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["data"]


async def _wait_status(client, token, kb_id, doc_id, target="completed", timeout=60.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        resp = await client.get(
            f"/api/v1/kb/{kb_id}/documents/{doc_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200, resp.text
        last = resp.json()["data"]
        if last["process_status"] == target or last["status"] == target:
            return last
        await asyncio.sleep(0.3)
    raise AssertionError(f"文档未在 {timeout}s 内达到 {target}，最后状态={last}")


async def _sample_data(name: str) -> bytes:
    return (TEST_DOC / name).read_bytes()


# ---------- L2M18-01 六份样本全链路产物 ----------
async def test_six_samples_produce_artifacts(client, super_token):
    kb = await _create_kb(client, super_token, "Phase2六样本")
    h = {"Authorization": f"Bearer {super_token}"}
    for name in SAMPLES:
        data = await _sample_data(name)
        uploaded = await _upload(client, super_token, kb["id"], name, data)
        doc = uploaded["document"]
        detail = await _wait_status(client, super_token, kb["id"], doc["id"])
        assert detail["status"] == "completed", (name, detail)
        assert detail["page_count"] > 0, name
        assert detail["markdown_path"], name
        assert detail["layout_path"], name

        md = await client.get(
            f"/api/v1/kb/{kb['id']}/documents/{doc['id']}/markdown", headers=h
        )
        assert md.status_code == 200, (name, md.text[:200])
        assert "<!-- page: 1 -->" in md.text
        assert len(md.text) > 20

        layout = await client.get(
            f"/api/v1/kb/{kb['id']}/documents/{doc['id']}/layout", headers=h
        )
        assert layout.status_code == 200
        body = layout.json()["data"]
        assert body["schema_version"] == "1.0"
        assert body["page_count"] == detail["page_count"]
        assert len(body["pages"]) == detail["page_count"]


# ---------- L2M18-02 产物接口权限（viewer 可读/外部人拒绝） ----------
async def test_markdown_layout_permissions(client, super_token):
    from app.core.config import settings

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
    viewer_token = await _invite_accept(client, owner_token, (kb := await _create_kb(client, owner_token, "Phase2权限"))["id"], viewer_name)
    outsider_token = await _login(client, outsider_name)

    uploaded = await _upload(client, owner_token, kb["id"], "perm.pdf", await _sample_data(SAMPLES[3]))
    doc = uploaded["document"]
    detail = await _wait_status(client, owner_token, kb["id"], doc["id"])
    assert detail["status"] == "completed"

    vh = {"Authorization": f"Bearer {viewer_token}"}
    assert (
        await client.get(f"/api/v1/kb/{kb['id']}/documents/{doc['id']}/markdown", headers=vh)
    ).status_code == 200
    assert (
        await client.get(f"/api/v1/kb/{kb['id']}/documents/{doc['id']}/layout", headers=vh)
    ).status_code == 200

    oh = {"Authorization": f"Bearer {outsider_token}"}
    assert (
        await client.get(f"/api/v1/kb/{kb['id']}/documents/{doc['id']}/markdown", headers=oh)
    ).status_code == 403
    assert (
        await client.get(f"/api/v1/kb/{kb['id']}/documents/{doc['id']}/layout", headers=oh)
    ).status_code == 403


# ---------- L2M18-03 重解析闭环（editor 允许 / viewer 拒绝） ----------
async def test_reparse_flow(client, super_token):
    owner_name = await _unique("owner")
    editor_name = await _unique("editor")
    viewer_name = await _unique("viewer")
    for name in (owner_name, editor_name, viewer_name):
        resp = await client.post(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {super_token}"},
            json={"username": name, "password": "Test@1234", "role_codes": ["member"]},
        )
        assert resp.status_code == 200, resp.text
    owner_token = await _login(client, owner_name)
    kb = await _create_kb(client, owner_token, "Phase2重解析")
    editor_token = await _invite_accept(client, owner_token, kb["id"], editor_name, role="editor")
    viewer_token = await _invite_accept(client, owner_token, kb["id"], viewer_name, role="viewer")

    uploaded = await _upload(client, owner_token, kb["id"], "reparse.pdf", await _sample_data(SAMPLES[0]))
    doc = uploaded["document"]
    detail = await _wait_status(client, owner_token, kb["id"], doc["id"])
    assert detail["status"] == "completed"
    first_md = (
        await client.get(f"/api/v1/kb/{kb['id']}/documents/{doc['id']}/markdown", headers={"Authorization": f"Bearer {owner_token}"})
    ).text

    vh = {"Authorization": f"Bearer {viewer_token}"}
    rej = await client.post(
        f"/api/v1/kb/{kb['id']}/documents/{doc['id']}/reparse", headers=vh
    )
    assert rej.status_code == 403

    eh = {"Authorization": f"Bearer {editor_token}"}
    ok = await client.post(
        f"/api/v1/kb/{kb['id']}/documents/{doc['id']}/reparse", headers=eh
    )
    assert ok.status_code == 200, ok.text
    new_task = ok.json()["data"]["task"]
    assert new_task["task_id"] != uploaded["task"]["task_id"]

    detail2 = await _wait_status(client, editor_token, kb["id"], doc["id"])
    assert detail2["status"] == "completed"
    second_md = (
        await client.get(f"/api/v1/kb/{kb['id']}/documents/{doc['id']}/markdown", headers={"Authorization": f"Bearer {owner_token}"})
    ).text
    assert second_md == first_md  # 同源重解析产物一致


# ---------- L2M18-04 损坏 PDF → failed + 死信 ----------
async def test_corrupt_pdf_failed_with_dead_letter(client, super_token, db_session):
    from sqlalchemy import select

    from app.models.document import TaskDeadLetter

    kb = await _create_kb(client, super_token, "Phase2损坏PDF")
    uploaded = await _upload(client, super_token, kb["id"], "broken.pdf", b"%PDF-1.4 garbage")
    doc = uploaded["document"]
    detail = await _wait_status(client, super_token, kb["id"], doc["id"], target="failed")
    assert detail["status"] == "failed"
    assert detail["error"]["message"]
    rows = (
        await db_session.execute(
            select(TaskDeadLetter).where(TaskDeadLetter.task_id == uploaded["task"]["task_id"])
        )
    ).scalars().all()
    assert rows, "failed 任务应写入死信表"


# ---------- L2M18-05 扫描版 PDF → 图片占位 ----------
async def test_scanned_pdf_image_placeholder(client, super_token):
    kb = await _create_kb(client, super_token, "Phase2扫描版")
    h = {"Authorization": f"Bearer {super_token}"}
    uploaded = await _upload(client, super_token, kb["id"], SAMPLES[2], await _sample_data(SAMPLES[2]))
    doc = uploaded["document"]
    detail = await _wait_status(client, super_token, kb["id"], doc["id"])
    assert detail["status"] == "completed"
    md = (
        await client.get(f"/api/v1/kb/{kb['id']}/documents/{doc['id']}/markdown", headers=h)
    ).text
    assert "<!-- image:" in md
    layout = (
        await client.get(f"/api/v1/kb/{kb['id']}/documents/{doc['id']}/layout", headers=h)
    ).json()["data"]
    all_types = {b["type"] for page in layout["pages"] for b in page["blocks"]}
    assert "image" in all_types


# ---------- L2M18-06 页眉页脚不进入 Markdown ----------
async def test_header_footer_excluded_from_markdown(client, super_token):
    kb = await _create_kb(client, super_token, "Phase2页眉页脚")
    h = {"Authorization": f"Bearer {super_token}"}
    uploaded = await _upload(client, super_token, kb["id"], SAMPLES[3], await _sample_data(SAMPLES[3]))
    doc = uploaded["document"]
    detail = await _wait_status(client, super_token, kb["id"], doc["id"])
    assert detail["status"] == "completed"
    md = (
        await client.get(f"/api/v1/kb/{kb['id']}/documents/{doc['id']}/markdown", headers=h)
    ).text
    assert "Page 1 of 10" not in md
    assert "Page 2 of 10" not in md


# ---------- L2M18-07 存储产物落盘（本地驱动） ----------
async def test_storage_artifacts_exist(client, super_token):
    from app.core.config import settings

    kb = await _create_kb(client, super_token, "Phase2产物落盘")
    uploaded = await _upload(client, super_token, kb["id"], SAMPLES[3], await _sample_data(SAMPLES[3]))
    doc = uploaded["document"]
    detail = await _wait_status(client, super_token, kb["id"], doc["id"])
    assert detail["status"] == "completed"
    root = Path(settings.LOCAL_STORAGE_DIR)
    md_path = root / detail["markdown_path"]
    layout_path = root / detail["layout_path"]
    assert md_path.exists(), md_path
    assert layout_path.exists(), layout_path
    assert md_path.read_text(encoding="utf-8").startswith("<!-- page: 1 -->")
    import json

    layout = json.loads(layout_path.read_text(encoding="utf-8"))
    assert layout["page_count"] == detail["page_count"]
    pages_dir = root / detail["markdown_path"].rsplit("/", 1)[0] / "pages"
    assert pages_dir.exists()
    assert len(list(pages_dir.glob("*.png"))) == detail["page_count"]
