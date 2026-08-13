"""L4 边界：E4 端点异常与导出。"""

import uuid

from qa.fixtures.indexing_helpers import create_kb_via_api

H = "Authorization"


async def test_start_missing_doc_400(client, super_token):
    """L4E4-01：不存在的文档启动返回 400。"""
    kb = await create_kb_via_api(client, super_token, "E4缺文档")
    r = await client.post(f"/api/v1/kb/{kb['id']}/extraction/{uuid.uuid4()}", headers={H: f"Bearer {super_token}"})
    assert r.status_code == 400


async def test_export_empty_result_ok(client, super_token):
    """L4E4-02：无结果导出返回表头 CSV。"""
    kb = await create_kb_via_api(client, super_token, "E4空导出")
    doc_id = uuid.uuid4()
    r = await client.get(f"/api/v1/kb/{kb['id']}/extraction/export?document_id={doc_id}", headers={H: f"Bearer {super_token}"})
    assert r.status_code == 200 and "类别" in r.text


async def test_delete_without_result_ok(client, super_token):
    """L4E4-03：无结果删除幂等成功。"""
    kb = await create_kb_via_api(client, super_token, "E4空删除")
    doc_id = uuid.uuid4()
    r = await client.delete(f"/api/v1/kb/{kb['id']}/extraction/{doc_id}/result", headers={H: f"Bearer {super_token}"})
    assert r.status_code == 200
