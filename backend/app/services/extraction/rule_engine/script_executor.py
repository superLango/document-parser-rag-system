"""自定义处理脚本执行引擎（类似 magic-api 的脚本即函数）。

提供脚本的动态编译 / 执行 / 超时保护 / 失败回退，供抽取流水线各阶段
（post / validation）调用用户编写的 Python 处理逻辑。

脚本契约：
- 必须定义 ``def run(args)`` 函数（可同步或异步）。
- ``args``：本次调用时机注入的运行时入参（随时机不同而不同）。
- 出参（post / validation）：``{"records": [...], "rejected"?: [...], "meta"?: {...}}``，
  其中 ``rejected`` / ``meta`` 可选，缺省按空处理。

安全与健壮性：
- 脚本在独立命名空间 ``exec`` 执行，不污染进程全局。
- 统一超时保护（默认 10s），超时视为失败并按策略跳过 / 回退。
- 异常不向调用方抛出，记录日志并按 ``on_error`` 策略处理（默认跳过）。
"""

from __future__ import annotations

import asyncio
import inspect
import traceback
from typing import Any, Awaitable, Callable

from app.core.logging import get_logger

logger = get_logger(__name__)

# 默认超时（秒）
DEFAULT_SCRIPT_TIMEOUT = 10


class ScriptExecutionError(Exception):
    """脚本执行失败（编译错误 / 运行时错误 / 超时）。"""


def compile_script(
    code: str,
    inject: dict[str, Any] | None = None,
) -> Callable[..., Any]:
    """编译脚本源码，返回 ``run`` 函数。

    Args:
        code: Python 脚本源码。
        inject: 注入脚本命名空间的对象（如 ``kb_tools`` 工具句柄）。

    Returns:
        可调用对象（``run(args, params)``）。

    Raises:
        ScriptExecutionError: 编译失败或未定义 ``run`` 函数。
    """
    if not code or not code.strip():
        raise ScriptExecutionError("脚本为空")
    namespace: dict[str, Any] = {"__name__": "kb_script"}
    if inject:
        namespace.update(inject)
    try:
        exec(compile(code, "<kb_script>", "exec"), namespace)
    except Exception as err:  # noqa: BLE001
        raise ScriptExecutionError(f"脚本编译失败: {err}") from err
    run_fn = namespace.get("run")
    if not callable(run_fn):
        raise ScriptExecutionError("脚本必须定义 run(args, params) 函数")
    return run_fn


def _invoke_sync(func: Callable[..., Any], args: dict, params: dict) -> Any:
    """尝试以 (args, params) / (args) 两种签名调用同步函数。"""
    try:
        return func(args, params)
    except TypeError:
        return func(args)


async def _invoke_async(func: Callable[..., Awaitable[Any]], args: dict, params: dict) -> Any:
    """尝试以 (args, params) / (args) 两种签名调用异步函数。"""
    try:
        awaitable = func(args, params)
    except TypeError:
        awaitable = func(args)
    return await awaitable


async def execute_script(
    code: str,
    args: dict[str, Any],
    params: dict[str, Any] | None = None,
    timeout: float = DEFAULT_SCRIPT_TIMEOUT,
    inject: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """执行脚本并返回结果字典。

    Args:
        code: 脚本源码。
        args: 运行时入参（随时机不同而不同）。
        params: 脚本自定义参数。
        timeout: 超时秒数。
        inject: 注入脚本命名空间的对象（如 ``kb_tools`` 工具句柄）。

    Returns:
        dict: 脚本返回的 dict 结果；脚本返回非 dict 时包装为
        ``{"data": <原值>}``。

    Raises:
        ScriptExecutionError: 编译 / 执行失败或超时。
    """
    run_fn = compile_script(code, inject=inject)
    params = params or {}
    loop = asyncio.get_running_loop()

    async def _dispatch() -> Any:
        if inspect.iscoroutinefunction(run_fn):
            return await _invoke_async(run_fn, args, params)
        return await loop.run_in_executor(None, _invoke_sync, run_fn, args, params)

    try:
        result = await asyncio.wait_for(_dispatch(), timeout=timeout)
    except asyncio.TimeoutError as err:
        raise ScriptExecutionError(f"脚本执行超时（>{timeout}s）") from err
    except Exception as err:  # noqa: BLE001
        logger.error(
            "脚本执行失败",
            error=str(err),
            traceback=traceback.format_exc(),
            exc_info=True,
        )
        raise ScriptExecutionError(f"脚本执行失败: {err}") from err

    if isinstance(result, dict):
        return result
    return {"data": result}


async def run_script(
    code: str,
    args: dict[str, Any],
    params: dict[str, Any] | None = None,
    timeout: float = DEFAULT_SCRIPT_TIMEOUT,
    on_error: str = "skip",
    inject: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """安全执行脚本：失败/超时按策略处理，不抛出。

    Args:
        code: 脚本源码。
        args: 运行时入参。
        params: 脚本自定义参数。
        timeout: 超时秒数。
        on_error: 失败处理策略（skip 跳过并返回 None；raise 抛出）。
        inject: 注入脚本命名空间的对象（如 ``kb_tools`` 工具句柄）。

    Returns:
        dict | None: 脚本结果；失败且 on_error=skip 时返回 None。
    """
    try:
        return await execute_script(code, args, params, timeout=timeout, inject=inject)
    except ScriptExecutionError as err:
        logger.warning("脚本执行失败，按策略处理", on_error=on_error, error=str(err))
        if on_error == "raise":
            raise
        return None


# 模块级脚本执行器实例
script_executor = type("ScriptExecutor", (), {
    "execute": staticmethod(execute_script),
    "run": staticmethod(run_script),
    "compile": staticmethod(compile_script),
})()