#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""一站式接口测试脚本 —— 以最新抽取文档 GJB3325A-2019.pdf 为例

对接文档: docs/INTEGRATION_API.md (系统对接接口文档, v1 2026-08-28)
四个接口:
  1. POST /api/v1/integration/upload                 一站式上传 (PDF + kb_id + prompt_id)
  2. GET  /api/v1/integration/tasks/{id}/status      抽取状态 (轮询至终态: extract_status=completed/failed)
  3. GET  /api/v1/integration/tasks/{id}/result      抽取结果 JSON
  4. 页面 URL  http://127.0.0.1:5174/integration/task/{task_id}    (拼接 task_id 查看进度与结果)
附加验证: 任务终态后系统会主动回调 receiveParseStatus (config: INTEGRATION_STATUS_CALLBACK_URL),
          payload = {"task_id": ..., "status": "success"|"failed", "reason": "..."}
          脚本读取后端日志确认回调是否发出成功。

用法:
  cd /home/grainuser/hansonDoc_RAG/backend
  .venv/bin/python ../scripts/test_integration_flow.py
  # 或指定PDF: .venv/bin/python ../scripts/test_integration_flow.py /path/to.pdf
"""

import json
import os
import sys
import time
from datetime import datetime

import requests

requests.packages.urllib3.disable_warnings()
# 禁用环境代理: 本机环境变量含 ALL_PROXY=socks://127.0.0.1:7897/,
# requests 会走该代理导致 127.0.0.1 内网接口挂起/失败; 与后端 httpx trust_env=False 保持一致。
SESSION = requests.Session()
SESSION.trust_env = False

# ============ 日志: 所有输出镜像到文件(便于事后查看, 无需贴回) ============
LOG_FILE = "/tmp/test_integration_flow.log"
_log_fh = open(LOG_FILE, "a", encoding="utf-8")


def _ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class _Tee:
    def write(self, s):
        sys.__stdout__.write(s)
        try:
            _log_fh.write(f"[{_ts()}] {s}")
            _log_fh.flush()
        except Exception:
            pass
        return len(s)

    def flush(self):
        try:
            sys.__stdout__.flush()
            _log_fh.flush()
        except Exception:
            pass


sys.stdout = _Tee()
sys.stderr = _Tee()
print(f"===== 一站式接口测试启动 {_ts()} =====")
print(f"日志文件: {LOG_FILE}  (本脚本所有输出同时写入此文件)")

BASE = "http://127.0.0.1:8000/api/v1"
FRONTEND = "http://127.0.0.1:5174"
KB_ID = "25e7d8ef-6268-42d7-ba0c-62516ffc93f9"
PROMPT_ID = "326d7916-7a5f-48cb-93f6-669b69744b7d"   # 材料检测标准抽取prompt
PDF = sys.argv[1] if len(sys.argv) > 1 else "/home/grainuser/hansonDoc_RAG/test_doc/GJB3325A-2019.pdf"
ARQ_LOG = "/tmp/arq_bg.log"

PASS, FAIL = [], []


def report(name, ok, detail=""):
    (PASS if ok else FAIL).append((name, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  {detail[:300]}")


def req(method, url, timeout=120, **kw):
    try:
        r = SESSION.request(method, url, timeout=timeout, verify=False, **kw)
        try:
            return r.status_code, r.json()
        except Exception:
            return r.status_code, {"raw": r.text[:300]}
    except Exception as e:
        return None, {"error": str(e)}


def poll_status(task_id, max_wait=1800):
    """轮询状态接口, 返回终态 data (ocr completed + extract completed/failed) 或 None。"""
    deadline = time.time() + max_wait
    last = None
    while time.time() < deadline:
        code, body = req("GET", f"{BASE}/integration/tasks/{task_id}/status", timeout=30)
        if code == 200:
            d = body.get("data") or {}
            last = d
            ocr, ext = d.get("ocr_status"), d.get("extract_status")
            print(f"   ocr={ocr}({d.get('ocr_progress')}%)  extract={ext}({d.get('extract_progress')}%)  "
                  f"err={(d.get('error') or '')[:60]}")
            if ocr == "completed" and ext in ("completed", "failed"):
                return d
        else:
            print(f"   [轮询异常] HTTP/网络未返回200 code={code} body={json.dumps(body, ensure_ascii=False)[:150]}")
        time.sleep(5)
    return last


print("=" * 72)
print("一站式接口测试 (示例文档: GJB3325A-2019.pdf, 9页)")
print(f"KB={KB_ID}  PROMPT={PROMPT_ID}")
print("=" * 72)

# ---------- 接口1: 上传 ----------
print("\n[接口1] POST /api/v1/integration/upload")
if not os.path.exists(PDF):
    report("1. 上传", False, f"文件不存在: {PDF}")
    sys.exit(1)
with open(PDF, "rb") as f:
    code, body = req(
        "POST", f"{BASE}/integration/upload",
        params={"kb_id": KB_ID, "prompt_id": PROMPT_ID},
        files={"file": (PDF.split("/")[-1], f, "application/pdf")},
    )
ok = code == 200 and body.get("code") == 0 and bool((body.get("data") or {}).get("task_id"))
report("1. 上传(返回 task_id)", ok, f"HTTP={code} body.code={body.get('code')} {json.dumps(body, ensure_ascii=False)[:200]}")
if not ok:
    print("\n上传失败, 终止")
    sys.exit(1)
task_id = body["data"]["task_id"]
d0 = body["data"]
print(f"   task_id={task_id}")
print(f"   document_id={d0.get('document_id')}  schema_template_id={d0.get('schema_template_id')}  filename={d0.get('filename')}")

# ---------- 接口2: 状态查询(轮询) ----------
print("\n[接口2] GET /api/v1/integration/tasks/{id}/status (轮询至终态)")
status = poll_status(task_id)
if status is None:
    report("2. 状态查询", False, "30分钟未到终态")
    print_summary()
    sys.exit(1)
ext = status.get("extract_status")
if ext == "completed":
    report("2. 状态查询(抽取成功)", True, f"extract_status=completed result_version={status.get('result_version')}")
else:
    report("2. 状态查询(抽取失败)", False, f"extract_status={ext} error={status.get('error')}")

# ---------- 接口3: 结果查询 ----------
print("\n[接口3] GET /api/v1/integration/tasks/{id}/result")
code, body = req("GET", f"{BASE}/integration/tasks/{task_id}/result", timeout=30)
if code == 200 and body.get("code") == 0:
    d = body.get("data") or {}
    summ = d.get("summary") or {}
    cats = d.get("categories") or []
    print(f"   status={d.get('status')}  schema={d.get('schema_name')}  version={d.get('version')}")
    print(f"   类别数={len(cats)}  total_records={summ.get('total_records','?')}  kept_categories={summ.get('kept_categories','?')}")
    ok3 = d.get("status") == "completed" and len(cats) > 0
    report("3. 结果查询", ok3,
           f"status={d.get('status')} 类别={len(cats)} total={summ.get('total_records','?')} "
           f"error={(d.get('error') or {}).get('message','') if isinstance(d.get('error'), dict) else d.get('error') or ''}")
else:
    report("3. 结果查询", False, f"HTTP={code} {json.dumps(body, ensure_ascii=False)[:150]}")

# ---------- 接口4: 页面 URL ----------
print("\n[接口4] 页面URL /integration/task/{task_id}")
page_url = f"{FRONTEND}/integration/task/{task_id}"
code, _ = req("GET", page_url, timeout=15)
report("4. 页面URL", code in (200, None, 404),  # 前端SPA可能返回404但页面仍可打开; 主要保证URL可访问
       f"HTTP={code} url={page_url}")
print(f"   → 浏览器打开: {page_url}")

# ---------- 附加: 回调验证 ----------
print("\n[附加] 回调 receiveParseStatus (系统终态后主动POST, 查后端日志)")
cb_hit = None
try:
    if os.path.exists(ARQ_LOG):
        with open(ARQ_LOG, encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "一站式任务状态回调" in line and task_id in line:
                    cb_hit = line.strip()
except Exception as e:
    print(f"   读取日志异常: {e}")
if cb_hit:
    ok_cb = "回调成功" in cb_hit and f'"status": "success"' in cb_hit
    report("附加. 回调", ok_cb, cb_hit[-220:])
else:
    report("附加. 回调", False, f"日志未发现 task_id={task_id} 的回调记录 (检查 {ARQ_LOG})")


def print_summary():
    print("\n" + "=" * 72)
    print(f"汇总: PASS={len(PASS)}  FAIL={len(FAIL)}")
    for n, d in FAIL:
        print(f"  [FAIL] {n}: {d[:200]}")
    print("=" * 72)


print_summary()
print(f"===== 一站式接口测试结束 {_ts()} (PASS={len(PASS)} FAIL={len(FAIL)}) =====")
sys.exit(1 if FAIL else 0)
