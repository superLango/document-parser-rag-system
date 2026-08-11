"""L5 安全渗透：Phase 3 GLM-OCR 拦截层（M19）。"""

import asyncio
import time
import uuid

import httpx


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


async def _upload_wait(client, token, kb_id, name="p3.pdf", data=None):
    import pymupdf

    if data is None:
        doc = pymupdf.open()
        page = doc.new_page(width=400, height=600)
        page.insert_text((72, 100), "security ocr", fontsize=12)
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
    raise AssertionError("文档未在 30s 内完成")


# ---------- L5M19-01 OCR 请求不含敏感字段/凭据 ----------
async def test_ocr_payload_contains_no_secrets():
    from app.services.ocr_backend.glmocr import GLMOCRBackend

    captured = {}

    class CaptureClient:
        def post(self, url, json=None, **kwargs):
            captured["url"] = url
            captured["json"] = json
            resp = httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
            resp.request = httpx.Request("POST", url)
            return resp

    backend = GLMOCRBackend(
        server_url="http://internal-glm:9977/v1/chat/completions",
        model="GLM-OCR",
        retries=0,
        client=CaptureClient(),
    )
    from PIL import Image
    import io

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), 0).save(buf, format="PNG")
    backend.ocr_block_sync(buf.getvalue(), "text")
    payload = captured["json"]
    assert set(payload.keys()) == {"model", "messages", "max_tokens", "temperature"}
    assert "Authorization" not in payload
    assert "password" not in str(payload).lower()
    assert "api_key" not in str(payload).lower()
    assert "@" not in captured["url"]  # 不含用户名/凭据


# ---------- L5M19-02 失败信息不泄漏图片内容 ----------
async def test_ocr_failure_does_not_leak_image():
    from app.services.ocr_backend.glmocr import GLMOCRBackend, OcrBlockError

    class FailClient:
        def post(self, url, json=None, **kwargs):
            resp = httpx.Response(502)
            resp.request = httpx.Request("POST", url)
            return resp

    backend = GLMOCRBackend(retries=0, client=FailClient())
    from PIL import Image
    import io

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), 0).save(buf, format="PNG")
    try:
        backend.ocr_block_sync(buf.getvalue(), "text")
        raise AssertionError("应抛 OcrBlockError")
    except OcrBlockError as exc:
        message = str(exc)
        assert "data:image" not in message
        assert "base64" not in message


# ---------- L5M19-03 viewer 不能触发 OCR 解析（reparse 403） ----------
async def test_viewer_cannot_trigger_ocr_reparse(client, super_token):
    owner_name = await _unique("owner")
    viewer_name = await _unique("viewer")
    for name in (owner_name, viewer_name):
        resp = await client.post(
            "/api/v1/users",
            headers={"Authorization": f"Bearer {super_token}"},
            json={"username": name, "password": "Test@1234", "role_codes": ["member"]},
        )
        assert resp.status_code == 200, resp.text
    owner_token = await _login(client, owner_name)
    kb = await _create_kb(client, owner_token, "P3-安全-viewer")
    viewer_token = await _invite_accept(client, owner_token, kb["id"], viewer_name)
    detail = await _upload_wait(client, owner_token, kb["id"])
    vh = {"Authorization": f"Bearer {viewer_token}"}
    resp = await client.post(
        f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/reparse", headers=vh
    )
    assert resp.status_code == 403


# ---------- L5M19-04 外部人不能读取 OCR 产物 ----------
async def test_outsider_cannot_read_ocr_artifacts(client, super_token):
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
    kb = await _create_kb(client, owner_token, "P3-安全-outsider")
    detail = await _upload_wait(client, owner_token, kb["id"])
    outsider_token = await _login(client, outsider_name)
    oh = {"Authorization": f"Bearer {outsider_token}"}
    assert (
        await client.get(f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/markdown", headers=oh)
    ).status_code == 403
    assert (
        await client.get(f"/api/v1/kb/{kb['id']}/documents/{detail['id']}/layout", headers=oh)
    ).status_code == 403


# ---------- L5M19-05 OCR 文本含 HTML/脚本时按纯文本展示 ----------
async def test_ocr_html_content_rendered_as_text():
    from app.services.parsekit.assemble import assemble_markdown
    from app.services.parsekit.types import BBox, LayoutBlock

    md = assemble_markdown(
        [
            LayoutBlock(
                type="text",
                bbox=BBox(0.1, 0.1, 0.5, 0.2),
                page_index=1,
                content='<script>alert("xss")</script>',
            )
        ]
    )
    assert "<script>" in md  # 原样进入产物（纯文本管道）
    # 前端文档内页使用 <pre> 纯文本展示（Markdown/JSON），不渲染 HTML
    source = (
        "/home/grainuser/hansonDoc_RAG/frontend/src/views/kb/KbDocumentViewerPage.tsx"
    )
    text = open(source, encoding="utf-8").read()
    assert "<pre" in text
