#!/usr/bin/env python3
"""Hansight 性能压测脚本。

使用 httpx 异步并发测试关键接口，输出延迟分布（P50/P95/P99）、
吞吐量（QPS）、成功率与错误分布。

测试接口：
    - GET  /api/v1/documents/  （列表查询）
    - GET  /api/v1/schemas/    （列表查询）
    - GET  /api/v1/terms/      （列表查询）
    - POST /api/v1/qa/query    （智能问答）

并发级别默认 10 / 50 / 100，可通过 --concurrency 自定义。

运行方式：
    python scripts/perf_test.py
    python scripts/perf_test.py --base-url http://localhost:8000 \
        --username admin --password admin
    python scripts/perf_test.py --concurrency 20 50 --total 200

依赖：httpx（已包含在 backend/requirements.txt 中）。
"""

from __future__ import annotations

import argparse
import asyncio
import math
import time
from collections import Counter
from typing import Any

import httpx


# 业务状态码：0 表示成功（见 app.core.response.success）
BIZ_SUCCESS_CODE = 0


def _percentile(samples: list[float], pct: float) -> float:
    """计算给定百分位数的延迟值。

    Args:
        samples: 延迟样本列表（秒）。
        pct: 百分位数（0-100），例如 95 表示 P95。

    Returns:
        float: 对应百分位的延迟值（秒），样本为空时返回 0.0。
    """
    if not samples:
        return 0.0
    sorted_samples = sorted(samples)
    # 采用 nearest-rank 方法，索引从 1 开始计数
    rank = (pct / 100.0) * (len(sorted_samples) - 1)
    lower = int(math.floor(rank))
    upper = int(math.ceil(rank))
    if lower == upper:
        return sorted_samples[lower]
    # 线性插值
    weight = rank - lower
    return sorted_samples[lower] * (1 - weight) + sorted_samples[upper] * weight


async def _do_request(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    headers: dict[str, str],
    json_body: dict | None,
) -> tuple[int, float, str | None]:
    """执行单次请求并返回状态码、耗时与可能的错误信息。

    Args:
        client: httpx 异步客户端。
        method: HTTP 方法。
        path: 相对 base_url 的路径。
        headers: 请求头（含鉴权 token）。
        json_body: JSON 请求体，None 表示无请求体。

    Returns:
        tuple[int, float, str | None]: (HTTP 状态码, 耗时秒数, 错误信息)。
        请求异常时状态码为 0。
    """
    start = time.perf_counter()
    try:
        kwargs: dict[str, Any] = {"headers": headers}
        if json_body is not None:
            kwargs["json"] = json_body
        resp = await client.request(method, path, **kwargs)
        elapsed = time.perf_counter() - start
        return resp.status_code, elapsed, None
    except httpx.HTTPError as exc:
        elapsed = time.perf_counter() - start
        return 0, elapsed, str(exc)


async def run_load_test(
    client: httpx.AsyncClient,
    method: str,
    path: str,
    headers: dict[str, str],
    json_body: dict | None,
    concurrency: int,
    total: int,
) -> dict[str, Any]:
    """对指定接口执行并发压测。

    使用 asyncio.Semaphore 限制并发度，收集每次请求的延迟与状态码，
    最终聚合为统计指标。

    Args:
        client: httpx 异步客户端。
        method: HTTP 方法。
        path: 相对 base_url 的路径。
        headers: 请求头。
        json_body: JSON 请求体。
        concurrency: 并发度。
        total: 总请求数。

    Returns:
        dict[str, Any]: 包含延迟、吞吐量、成功率、错误分布等指标的字典。
    """
    semaphore = asyncio.Semaphore(concurrency)
    latencies: list[float] = []
    status_codes: list[int] = []
    errors: list[str] = []

    async def _worker():
        async with semaphore:
            status, elapsed, err = await _do_request(
                client, method, path, headers, json_body
            )
            latencies.append(elapsed)
            status_codes.append(status)
            if err is not None:
                errors.append(err)

    wall_start = time.perf_counter()
    await asyncio.gather(*(_worker() for _ in range(total)))
    wall_elapsed = time.perf_counter() - wall_start

    # 聚合统计：成功 = HTTP 2xx
    success_count = sum(1 for c in status_codes if 200 <= c < 300)
    success_rate = (success_count / total) * 100 if total else 0.0
    qps = total / wall_elapsed if wall_elapsed > 0 else 0.0

    # 延迟统计（单位转换为毫秒便于阅读）
    latencies_ms = [d * 1000 for d in latencies]
    avg_ms = sum(latencies_ms) / len(latencies_ms) if latencies_ms else 0.0
    p50 = _percentile(latencies_ms, 50)
    p95 = _percentile(latencies_ms, 95)
    p99 = _percentile(latencies_ms, 99)
    min_ms = min(latencies_ms) if latencies_ms else 0.0
    max_ms = max(latencies_ms) if latencies_ms else 0.0

    # 错误分布：按状态码（含 0 表示连接错误）计数
    status_counter = Counter(status_codes)
    error_counter = Counter(errors) if errors else Counter()

    return {
        "concurrency": concurrency,
        "total": total,
        "wall_elapsed": wall_elapsed,
        "qps": qps,
        "success_count": success_count,
        "success_rate": success_rate,
        "latency_avg_ms": avg_ms,
        "latency_p50_ms": p50,
        "latency_p95_ms": p95,
        "latency_p99_ms": p99,
        "latency_min_ms": min_ms,
        "latency_max_ms": max_ms,
        "status_counter": status_counter,
        "error_counter": error_counter,
    }


def _print_report(
    endpoint_name: str,
    method: str,
    path: str,
    results: list[dict[str, Any]],
) -> None:
    """打印单个接口在不同并发级别下的压测报告。

    Args:
        endpoint_name: 接口名称（用于标题）。
        method: HTTP 方法。
        path: 请求路径。
        results: 各并发级别的统计结果列表。
    """
    print(f"\n---------- {endpoint_name}: {method} {path} ----------")
    header = (
        f"{'并发':>4}  {'总数':>5}  {'QPS':>8}  "
        f"{'成功率':>7}  {'平均':>8}  {'P50':>8}  {'P95':>8}  "
        f"{'P99':>8}  {'最小':>8}  {'最大':>8}  {'墙钟':>7}"
    )
    print(header)
    print("-" * len(header))
    for r in results:
        print(
            f"{r['concurrency']:>4}  "
            f"{r['total']:>5}  "
            f"{r['qps']:>8.1f}  "
            f"{r['success_rate']:>6.1f}%  "
            f"{r['latency_avg_ms']:>7.1f}ms  "
            f"{r['latency_p50_ms']:>7.1f}ms  "
            f"{r['latency_p95_ms']:>7.1f}ms  "
            f"{r['latency_p99_ms']:>7.1f}ms  "
            f"{r['latency_min_ms']:>7.1f}ms  "
            f"{r['latency_max_ms']:>7.1f}ms  "
            f"{r['wall_elapsed']:>6.2f}s"
        )

    # 错误分布（仅展示非 2xx 状态码与异常信息）
    for r in results:
        non_success = {
            code: cnt for code, cnt in r["status_counter"].items() if not (200 <= code < 300)
        }
        if non_success or r["error_counter"]:
            print(f"  [并发 {r['concurrency']}] 错误分布:")
            for code, cnt in sorted(non_success.items()):
                label = "连接错误" if code == 0 else f"HTTP {code}"
                print(f"    {label}: {cnt} 次")
            for msg, cnt in r["error_counter"].most_common(5):
                preview = msg if len(msg) <= 80 else msg[:80] + "..."
                print(f"    异常: {preview} × {cnt}")


async def _login(
    client: httpx.AsyncClient, username: str, password: str
) -> str | None:
    """登录并返回 JWT token。

    Args:
        client: httpx 异步客户端。
        username: 用户名。
        password: 密码。

    Returns:
        str | None: 成功返回 token，失败返回 None。
    """
    try:
        resp = await client.post(
            "/api/v1/auth/login",
            json={"username": username, "password": password},
        )
        if resp.status_code != 200:
            print(f"登录失败: HTTP {resp.status_code} - {resp.text[:200]}")
            return None
        body = resp.json()
        token = body.get("data", {}).get("access_token")
        if not token:
            print(f"登录响应缺少 access_token: {body}")
        return token
    except httpx.HTTPError as exc:
        print(f"登录请求异常: {exc}")
        return None


async def main(
    base_url: str,
    username: str,
    password: str,
    concurrency_levels: list[int],
    total: int,
    endpoints: list[str],
) -> int:
    """执行性能压测主流程。

    先登录获取 token，再依次对指定接口在多个并发级别下压测，
    最后输出各接口的延迟分布与吞吐量报告。

    Args:
        base_url: 后端 API 基地址。
        username: 登录用户名。
        password: 登录密码。
        concurrency_levels: 并发级别列表。
        total: 每个并发级别的总请求数。
        endpoints: 待测试的接口名称列表，可选值: documents, schemas, terms, qa。

    Returns:
        int: 退出码，0 表示全部完成，1 表示登录失败。
    """
    print("========== Hansight 性能压测开始 ==========")
    print(f"目标地址: {base_url}")
    print(f"并发级别: {concurrency_levels}")
    print(f"每级请求数: {total}")
    print(f"测试接口: {endpoints}")
    print()

    # 接口定义表：名称 -> (method, path, json_body)
    endpoint_table: dict[str, tuple[str, str, dict | None]] = {
        "documents": ("GET", "/api/v1/documents/", None),
        "schemas": ("GET", "/api/v1/schemas/", None),
        "terms": ("GET", "/api/v1/terms/", None),
        "qa": (
            "POST",
            "/api/v1/qa/query",
            {
                "question": "请概述当前知识库的主要内容",
                "top_k": 3,
                "use_graph": True,
                "use_reranker": True,
            },
        ),
    }

    async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as client:
        # 1. 登录获取 token
        token = await _login(client, username, password)
        if not token:
            print("登录失败，无法继续压测需要鉴权的接口。")
            return 1
        print(f"登录成功，token: {token[:20]}...")
        headers = {"Authorization": f"Bearer {token}"}
        print()

        # 2. 依次对每个接口执行各并发级别的压测
        for name in endpoints:
            if name not in endpoint_table:
                print(f"未知接口: {name}，跳过")
                continue
            method, path, json_body = endpoint_table[name]
            level_results: list[dict[str, Any]] = []
            for concurrency in concurrency_levels:
                # 针对当前并发级别调整总请求数，避免并发大于总数
                actual_total = max(total, concurrency)
                print(f"压测中: {name} 并发={concurrency} 总数={actual_total} ...")
                result = await run_load_test(
                    client,
                    method,
                    path,
                    headers,
                    json_body,
                    concurrency,
                    actual_total,
                )
                level_results.append(result)
            _print_report(name, method, path, level_results)

    print("\n========== 压测结束 ==========")
    return 0


def _parse_args() -> argparse.Namespace:
    """解析命令行参数。"""
    parser = argparse.ArgumentParser(
        description="Hansight 性能压测脚本，基于 httpx 异步并发测试关键接口。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="后端 API 基地址",
    )
    parser.add_argument("--username", default="admin", help="登录用户名")
    parser.add_argument("--password", default="admin", help="登录密码")
    parser.add_argument(
        "--concurrency",
        type=int,
        nargs="+",
        default=[10, 50, 100],
        help="并发级别列表（空格分隔）",
    )
    parser.add_argument(
        "--total",
        type=int,
        default=100,
        help="每个并发级别的总请求数（小于并发度时自动取齐到并发度）",
    )
    parser.add_argument(
        "--endpoints",
        nargs="+",
        default=["documents", "schemas", "terms", "qa"],
        choices=["documents", "schemas", "terms", "qa"],
        help="待测试的接口列表",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    raise SystemExit(
        asyncio.run(
            main(
                args.base_url,
                args.username,
                args.password,
                args.concurrency,
                args.total,
                args.endpoints,
            )
        )
    )
