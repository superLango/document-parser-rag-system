"""批量上传 test_doc 到 KB=25e7d8ef(航天航空检测知识库)并启动解析。

用法: .venv/bin/python scripts/bulk_upload_test_doc.py [--limit N] [--skip-existing]
登录(admin/admin123) → 上传未入库文件 → start_parse → arq 消费解析+索引。
"""

import asyncio
import json
import sys
import time
import urllib.parse
import uuid
from pathlib import Path

import aiohttp


async def _post_retry(sess, url, headers, *, data=None, json=None, retries=8):
    for attempt in range(retries):
        resp = await sess.post(url, headers=headers, data=data, json=json)
        body = await resp.text()
        if "Rate limit exceeded" in body or "rate limit" in body.lower():
            wait = 65
            print(f"  限流,等待 {wait}s (attempt {attempt+1})", flush=True)
            await asyncio.sleep(wait)
            continue
        if resp.status >= 400:
            raise RuntimeError(f"HTTP {resp.status}: {body[:150]}")
        return resp, body
    raise RuntimeError("rate limit retries exhausted")

BASE = "http://127.0.0.1:8000/api/v1"
KB = "25e7d8ef-6268-42d7-ba0c-62516ffc93f9"
TEST_DOC = Path("/home/grainuser/hansonDoc_RAG/test_doc")
USERNAME = "admin"
PASSWORD = "admin123"


async def main():
    parser_kwargs = {}
    if "--limit" in sys.argv:
        idx = sys.argv.index("--limit")
        parser_kwargs["limit"] = int(sys.argv[idx + 1])
    limit = parser_kwargs.get("limit") or 200

    async with aiohttp.ClientSession() as sess:
        # 登录
        r = await sess.post(
            f"{BASE}/auth/login",
            json={"username": USERNAME, "password": PASSWORD},
        )
        data = await r.json()
        token = (data.get("data") or {}).get("access_token")
        if not token:
            print("登录失败:", data)
            return
        headers = {"Authorization": f"Bearer {token}"}
        print("登录成功", flush=True)

        # 现有文档
        r = await sess.get(f"{BASE}/kb/{KB}/documents", headers=headers, params={"page": 1, "page_size": 500})
        existing = set()
        try:
            items = ((await r.json()).get("data") or {}).get("items") or []
            existing = {item.get("filename") for item in items}
        except Exception:
            pass
        print(f"现有文档: {len(existing)}", flush=True)

        files = [p for p in sorted(TEST_DOC.glob("*.pdf")) if p.name not in existing]
        print(f"待上传: {len(files)}", flush=True)

        uploaded = 0
        failed = []
        for idx, p in enumerate(files[:limit]):
            try:
                fd = open(p, "rb")
                form = aiohttp.FormData()
                form.add_field("file", fd, filename=p.name, content_type="application/pdf")
                resp, body = await _post_retry(
                    sess, f"{BASE}/kb/{KB}/documents", headers, data=form,
                )
                j = json.loads(body)
                if resp.status >= 400:
                    msg = j.get("detail") or j.get("message") or str(j)
                    raise RuntimeError(str(msg))
                doc_id = ((j.get("data") or {}).get("document") or {}).get("id")
                # start parse
                r2, body2 = await _post_retry(
                    sess, f"{BASE}/kb/{KB}/documents/{doc_id}/start", headers,
                )
                j2 = json.loads(body2)
                if r2.status >= 400:
                    raise RuntimeError(f"start: {j2}")
                uploaded += 1
                print(f"[{idx+1}/{len(files[:limit])}] {p.name[:60]} -> {doc_id} parsing", flush=True)
            except Exception as exc:
                failed.append((p.name, str(exc)[:150]))
                print(f"[{idx+1}/{len(files[:limit])}] FAIL {p.name[:60]}: {str(exc)[:120]}", flush=True)
            await asyncio.sleep(6)

        print(f"\n上传完成: {uploaded}/{len(files[:limit])}, 失败: {len(failed)}", flush=True)
        for n, e in failed:
            print(f"  FAIL {n}: {e}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
