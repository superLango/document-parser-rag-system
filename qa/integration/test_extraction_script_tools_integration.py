"""L2/L3 集成：E3 真实 kb_tools（get_term_records / semantic_search / match_record / embed）。

覆盖：多字段术语集读取、方法年代号补全、项目名称归一化（语义/精确）、
跨类校验（语义阈值剔除）、嵌入服务不可用时的回退/失败、并发脚本执行。
"""

from __future__ import annotations

import asyncio
import hashlib
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from app.core.exceptions import BusinessException
from app.models.extraction import KbScript
from app.models.glossary import TERM_STATUS_ACTIVE, Term, TermBase
from app.services.extraction import script_processor, script_tools

from qa.fixtures.indexing_helpers import create_kb_via_api

H = "Authorization"


class _MockEmbedHandler(BaseHTTPRequestHandler):
    """按 sha256 生成 256 维 one-hot 向量：相同文本余弦=1，不同文本≈0。"""

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        import json

        payload = json.loads(body.decode("utf-8"))
        vectors = []
        for text in payload.get("texts", []):
            vec = [0.0] * 256
            vec[int(hashlib.sha256(text.encode()).hexdigest(), 16) % 256] = 1.0
            vectors.append(vec)
        out = json.dumps({"vectors": vectors}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *args):
        pass


@pytest.fixture
def mock_embed_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _MockEmbedHandler)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_port}/script-embed"
    srv.shutdown()
    thread.join(timeout=2)


async def _setup_kb(client, super_token, db_session, name):
    kb = await create_kb_via_api(client, super_token, name)
    kb_id = uuid.UUID(kb["id"])

    tb_items = TermBase(kb_id=kb_id, name="检测项目", source_type="manual",
                        columns=[], column_aliases={}, status="active")
    tb_methods = TermBase(kb_id=kb_id, name="试验方法", source_type="manual",
                          columns=[], column_aliases={}, status="active")
    db_session.add_all([tb_items, tb_methods])
    await db_session.flush()
    db_session.add_all([
        Term(kb_id=kb_id, term_base_id=tb_items.id, term_name="抗拉强度(Rm)", status=TERM_STATUS_ACTIVE,
             extras={"NAME": "抗拉强度(Rm)", "FEATURE": "室温拉伸", "UNIT": "MPa"}),
        Term(kb_id=kb_id, term_base_id=tb_items.id, term_name="断后伸长率(δ5)", status=TERM_STATUS_ACTIVE,
             extras={"NAME": "断后伸长率(δ5)", "FEATURE": "室温拉伸", "UNIT": "%"}),
        Term(kb_id=kb_id, term_base_id=tb_methods.id, term_name="GB/T 228.1-2021", status=TERM_STATUS_ACTIVE,
             extras={"METHOD_CODE": "GB/T 228.1-2021", "FEATURE": "室温拉伸"}),
        Term(kb_id=kb_id, term_base_id=tb_methods.id, term_name="GB/T 228.1-2010", status=TERM_STATUS_ACTIVE,
             extras={"METHOD_CODE": "GB/T 228.1-2010", "FEATURE": "室温拉伸"}),
    ])
    code_method = r"""
import re

async def run(args):
    records = args.get("records", [])
    feature = args.get("category", "")
    methods = await kb_tools.get_term_records("试验方法", "METHOD_CODE", "FEATURE")
    methods = [m for m in methods if m.get("FEATURE") == feature]
    codes = [str(m.get("METHOD_CODE", "")).strip() for m in methods]

    def _latest(method):
        prefix = re.sub(r"[-:]\d{4}$", "", method).strip()
        cands = [c for c in codes if re.sub(r"[-:]\d{4}$", "", c).strip() == prefix]
        if not cands:
            return None
        def year(s):
            m = re.search(r"[-:](\d{4})$", s)
            return int(m.group(1)) if m else 0
        return sorted(cands, key=year, reverse=True)[0]

    for r in records:
        method = str(r.get("试验方法", "")).strip()
        if not method or re.search(r"[-:](\d{4})$", method):
            continue
        best = _latest(method)
        if best:
            r["试验方法"] = best
    return {"records": records}
"""
    code_norm = """
async def run(args):
    records = args.get("records", [])
    feature = args.get("category", "")
    items = await kb_tools.get_term_records("检测项目", "NAME", "FEATURE")
    items = [i for i in items if i.get("FEATURE") == feature]
    for r in records:
        name = str(r.get("项目名称", "")).strip()
        if not name:
            continue
        hit = await kb_tools.match_record(name, items, ["NAME"], threshold=0.90)
        if hit["type"] != "unverified":
            r["项目名称"] = hit["canonical"]
    return {"records": records}
"""
    code_valid = """
async def run(args):
    records = args.get("records", [])
    feature = args.get("category", "")
    items = await kb_tools.get_term_records("检测项目", "NAME", "FEATURE")
    items = [i for i in items if i.get("FEATURE") == feature]
    kept, rejected = [], []
    for r in records:
        name = str(r.get("项目名称", "")).strip()
        if not name:
            kept.append(r)
            continue
        top = await kb_tools.semantic_search(items, name, ["NAME"], top_k=1)
        if top and top[0]["score"] >= 0.90:
            kept.append(r)
        else:
            rejected.append(r)
    return {"records": kept, "rejected": rejected}
"""
    sc_method = KbScript(kb_id=kb_id, folder="post", name="方法年代号补全", code=code_method)
    sc_norm = KbScript(kb_id=kb_id, folder="post", name="项目名称归一化", code=code_norm)
    sc_valid = KbScript(kb_id=kb_id, folder="validation", name="跨类校验", code=code_valid)
    db_session.add_all([sc_method, sc_norm, sc_valid])
    await db_session.commit()
    return kb_id, [
        {"script_id": str(sc_method.id), "script_name": "post/方法年代号补全", "sort_order": 1},
        {"script_id": str(sc_norm.id), "script_name": "post/项目名称归一化", "sort_order": 2},
        {"script_id": str(sc_valid.id), "script_name": "validation/跨类校验", "sort_order": 3},
    ]


async def test_apply_scripts_real_tools_full_path(client, super_token, db_session, monkeypatch, mock_embed_server):
    """L2E3-10：真实 kb_tools 全链路（术语读取→年代补全→归一化→语义校验）。"""
    monkeypatch.setattr(script_tools, "embed_endpoint_url", lambda kb: mock_embed_server)
    kb_id, rules = await _setup_kb(client, super_token, db_session, "E3真实工具")
    records = [{"材料牌号": "GH4169", "项目名称": "抗拉强度(Rm)", "试验方法": "GB/T 228.1", "温度": "500"}]
    kept, rejected = await script_processor.apply_scripts(
        db_session, kb_id, category_feature="室温拉伸", records=records,
        doc_id=str(uuid.uuid4()), rules=rules, script_timeout=15,
    )
    assert len(kept) == 1 and len(rejected) == 0
    assert kept[0]["试验方法"] == "GB/T 228.1-2021"
    assert kept[0]["项目名称"] == "抗拉强度(Rm)"


async def test_apply_scripts_validation_rejects_unknown(client, super_token, db_session, monkeypatch, mock_embed_server):
    """L2E3-11：语义校验对未知项目名执行剔除。"""
    monkeypatch.setattr(script_tools, "embed_endpoint_url", lambda kb: mock_embed_server)
    kb_id, rules = await _setup_kb(client, super_token, db_session, "E3真实工具剔除")
    records = [{"材料牌号": "GH4169", "项目名称": "完全不存在项目", "试验方法": "GB/T 228.1-2021", "温度": "500"}]
    kept, rejected = await script_processor.apply_scripts(
        db_session, kb_id, category_feature="室温拉伸", records=records,
        doc_id=str(uuid.uuid4()), rules=rules, script_timeout=15,
    )
    assert len(kept) == 0 and len(rejected) == 1
    assert rejected[0]["项目名称"] == "完全不存在项目"


async def test_apply_scripts_embed_down_fallback_and_fail(client, super_token, db_session, monkeypatch):
    """L2E3-12：嵌入服务不可用→归一化精确兜底可用；校验脚本明确失败。"""
    # 指向未监听端口，连接立即失败
    monkeypatch.setattr(script_tools, "embed_endpoint_url", lambda kb: "http://127.0.0.1:18999/embed")
    kb_id, rules = await _setup_kb(client, super_token, db_session, "E3嵌入不可用")
    records = [{"材料牌号": "GH4169", "项目名称": "抗拉强度(Rm)", "试验方法": "GB/T 228.1-2021", "温度": "500"}]
    # 只跑 post 两段：match_record 应精确兜底
    kept, _rejected = await script_processor.apply_scripts(
        db_session, kb_id, category_feature="室温拉伸", records=[dict(records[0])],
        doc_id=str(uuid.uuid4()), rules=rules[:2], script_timeout=15,
    )
    assert kept[0]["项目名称"] == "抗拉强度(Rm)"
    # 加上校验段：semantic_search 应抛错并整体失败
    with pytest.raises(BusinessException, match="脚本执行失败"):
        await script_processor.apply_scripts(
            db_session, kb_id, category_feature="室温拉伸", records=[dict(records[0])],
            doc_id=str(uuid.uuid4()), rules=rules, script_timeout=15,
        )


async def test_apply_scripts_concurrent_categories(client, super_token, db_session, monkeypatch, mock_embed_server):
    """L2E3-13：多类别并发执行脚本互不串扰（数据/代码预载，对齐流水线并发模式）。"""
    monkeypatch.setattr(script_tools, "embed_endpoint_url", lambda kb: mock_embed_server)
    kb_id, rules = await _setup_kb(client, super_token, db_session, "E3并发脚本")
    # 预载（流水线在 gather 前串行完成，避免共享会话并发查询）
    term_data = await script_tools.load_term_data(db_session, kb_id)
    preloaded_rules = []
    for rule in rules:
        sc = await db_session.get(KbScript, uuid.UUID(rule["script_id"]))
        preloaded_rules.append({**rule, "code": sc.code})
    async def run_one(feature, name):
        records = [{"材料牌号": "GH4169", "项目名称": name, "试验方法": "GB/T 228.1", "温度": "500"}]
        return await script_processor.apply_scripts(
            db_session, kb_id, category_feature=feature, records=records,
            doc_id=str(uuid.uuid4()), rules=preloaded_rules, script_timeout=30,
            term_data=term_data,
        )

    results = await asyncio.gather(
        run_one("室温拉伸", "抗拉强度(Rm)"),
        run_one("室温拉伸", "断后伸长率(δ5)"),
    )
    assert len(results) == 2
    for kept, rejected in results:
        assert len(kept) == 1 and len(rejected) == 0
        assert kept[0]["试验方法"] == "GB/T 228.1-2021"
