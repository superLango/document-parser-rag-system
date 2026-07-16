#!/usr/bin/env python3
"""Hansight 端到端测试脚本。

覆盖登录→文档→解析→索引→问答全流程，依次调用后端关键 API 并校验状态码，
最终输出汇总报告。某一步失败不会中断后续步骤的执行。

运行方式：
    python scripts/e2e_test.py
    python scripts/e2e_test.py --base-url http://localhost:8000 \
        --username admin --password admin

依赖：httpx（已包含在 backend/requirements.txt 中）。
"""

from __future__ import annotations

import argparse
import sys
import time
from typing import Any

import httpx


# 业务状态码：0 表示成功（见 app.core.response.success）
BIZ_SUCCESS_CODE = 0


def _format_data(data: Any, limit: int = 200) -> str:
    """将响应 data 字段格式化为单行预览字符串，便于在报告中打印。

    Args:
        data: 响应体中的 data 字段。
        limit: 预览字符串最大长度，超出部分以 "..." 截断。

    Returns:
        str: 格式化后的预览文本。
    """
    if data is None:
        return "<空>"
    text = str(data)
    if len(text) > limit:
        text = text[:limit] + "..."
    return text


def _request(
    client: httpx.Client,
    method: str,
    path: str,
    *,
    name: str,
    expected_status: int = 200,
    results: list[tuple[str, bool, float, str]],
    **kwargs: Any,
) -> dict | None:
    """执行一次 HTTP 请求并记录结果。

    自动计时与状态码断言，失败时打印错误信息并返回 None，
    不会抛出异常导致主流程中断。

    Args:
        client: httpx 同步客户端。
        method: HTTP 方法（GET/POST 等）。
        path: 相对 base_url 的路径。
        name: 步骤名称，用于汇总报告。
        expected_status: 期望的 HTTP 状态码。
        results: 结果收集列表，每项为 (名称, 是否成功, 耗时, 详情)。
        **kwargs: 透传给 httpx.Client.request 的额外参数（json、headers 等）。

    Returns:
        dict | None: 成功时返回响应 JSON 字典，失败时返回 None。
    """
    start = time.perf_counter()
    try:
        resp = client.request(method, path, **kwargs)
    except httpx.HTTPError as exc:
        elapsed = time.perf_counter() - start
        detail = f"请求异常: {exc}"
        print(f"[{name}] ✗ {detail} ({elapsed:.2f}s)")
        results.append((name, False, elapsed, detail))
        return None

    elapsed = time.perf_counter() - start

    if resp.status_code != expected_status:
        detail = (
            f"状态码不符: 期望 {expected_status}, 实际 {resp.status_code}; "
            f"响应={resp.text[:300]}"
        )
        print(f"[{name}] ✗ {detail} ({elapsed:.2f}s)")
        results.append((name, False, elapsed, detail))
        return None

    # 解析 JSON 响应体，校验业务状态码
    try:
        body = resp.json()
    except Exception as exc:  # noqa: BLE001
        detail = f"响应非 JSON: {exc}; 原文={resp.text[:300]}"
        print(f"[{name}] ✗ {detail} ({elapsed:.2f}s)")
        results.append((name, False, elapsed, detail))
        return None

    biz_code = body.get("code") if isinstance(body, dict) else None
    if biz_code is not None and biz_code != BIZ_SUCCESS_CODE:
        detail = (
            f"业务码错误: code={biz_code}, message={body.get('message')}; "
            f"data={_format_data(body.get('data'))}"
        )
        print(f"[{name}] ✗ {detail} ({elapsed:.2f}s)")
        results.append((name, False, elapsed, detail))
        return body

    data = body.get("data") if isinstance(body, dict) else body
    print(f"[{name}] ✓ 状态码={resp.status_code} ({elapsed:.2f}s)")
    print(f"         data={_format_data(data)}")
    results.append((name, True, elapsed, f"HTTP {resp.status_code}"))
    return body


def main(base_url: str, username: str, password: str) -> int:
    """执行端到端测试主流程。

    Args:
        base_url: 后端 API 基地址（如 http://localhost:8000）。
        username: 登录用户名。
        password: 登录密码。

    Returns:
        int: 退出码，0 表示全部步骤成功，1 表示存在失败步骤。
    """
    results: list[tuple[str, bool, float, str]] = []
    headers: dict[str, str] = {}

    print(f"========== Hansight E2E 测试开始 ==========")
    print(f"目标地址: {base_url}")
    print(f"登录用户: {username}")
    print()

    with httpx.Client(base_url=base_url, timeout=30.0) as client:
        # 1. 登录，获取 JWT token
        login_body = _request(
            client,
            "POST",
            "/api/v1/auth/login",
            name="1. 登录(login)",
            json={"username": username, "password": password},
            results=results,
        )
        token = None
        if login_body and isinstance(login_body.get("data"), dict):
            token = login_body["data"].get("access_token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
            print(f"         获取到 token: {token[:20]}...")
        else:
            print("         ⚠ 未获取到 token，后续需鉴权接口可能失败")

        # 2. 获取当前用户信息
        _request(
            client,
            "GET",
            "/api/v1/auth/me",
            name="2. 当前用户(me)",
            headers=headers,
            results=results,
        )

        # 3. 文档列表
        _request(
            client,
            "GET",
            "/api/v1/documents/",
            name="3. 文档列表(documents)",
            headers=headers,
            results=results,
        )

        # 4. Schema 列表
        _request(
            client,
            "GET",
            "/api/v1/schemas/",
            name="4. Schema 列表(schemas)",
            headers=headers,
            results=results,
        )

        # 5. 术语列表
        _request(
            client,
            "GET",
            "/api/v1/terms/",
            name="5. 术语列表(terms)",
            headers=headers,
            results=results,
        )

        # 6. 任务列表
        _request(
            client,
            "GET",
            "/api/v1/tasks/",
            name="6. 任务列表(tasks)",
            headers=headers,
            results=results,
        )

        # 7. 智能问答（POST，需要请求体）
        _request(
            client,
            "POST",
            "/api/v1/qa/query",
            name="7. 智能问答(qa/query)",
            headers=headers,
            json={
                "question": "请概述当前知识库的主要内容",
                "top_k": 3,
                "use_graph": True,
                "use_reranker": True,
            },
            results=results,
        )

        # 8. 知识库统计
        _request(
            client,
            "GET",
            "/api/v1/kb/stats",
            name="8. 知识库统计(kb/stats)",
            headers=headers,
            results=results,
        )

        # 9. 知识图谱统计
        _request(
            client,
            "GET",
            "/api/v1/kg/stats",
            name="9. 知识图谱统计(kg/stats)",
            headers=headers,
            results=results,
        )

    # ---------- 汇总报告 ----------
    total = len(results)
    passed = sum(1 for _, ok, _, _ in results if ok)
    failed = total - passed
    total_time = sum(d for _, _, d, _ in results)

    print()
    print("========== E2E 测试报告 ==========")
    for name, ok, duration, detail in results:
        status = "✓ PASS" if ok else "✗ FAIL"
        print(f"{status}  {name:<28} {duration:6.2f}s  {detail}")

    print("-" * 60)
    print(f"总计: {total}  通过: {passed}  失败: {failed}  累计耗时: {total_time:.2f}s")
    print("=" * 60)

    return 0 if failed == 0 else 1


def _parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="Hansight 端到端测试脚本，覆盖登录→文档→解析→问答全流程。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="后端 API 基地址",
    )
    parser.add_argument("--username", default="admin", help="登录用户名")
    parser.add_argument("--password", default="admin", help="登录密码")
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(main(args.base_url, args.username, args.password))
