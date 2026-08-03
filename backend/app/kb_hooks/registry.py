"""Hook 注册表与加载器。

提供 Hook 脚本的加载、缓存、写入与重载能力。

Hook 脚本路径约定：``app/kb_hooks/{kb_id_hex}/hooks.py``
- 每个知识库独立一个目录，物理隔离
- 目录名使用 kb_id 的 hex 形式（无连字符），避免路径问题
- 脚本文件名固定为 ``hooks.py``

加载策略：
1. 按文件 mtime 缓存已加载的 Hook 模块，mtime 变化时重新加载
2. 脚本不存在时返回 ``DefaultKbHook``（不抛异常）
3. 脚本加载失败时记录日志并返回 ``DefaultKbHook``（不阻断主流程）
4. 使用 importlib.util 从文件路径加载，避免污染 sys.modules

并发安全：
- 缓存读写未加锁，最坏情况下同一 KB 并发加载多次（幂等，无数据竞争）
- 重载时清缓存即可，不强制同步
"""

from __future__ import annotations

import importlib.util
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from app.core.logging import get_logger
from app.kb_hooks.base import DefaultKbHook, KbHook, KbHookBase

logger = get_logger(__name__)

# Hook 脚本根目录（app/kb_hooks/）
_HOOKS_ROOT = Path(__file__).resolve().parent

# 缓存：kb_id_hex → (mtime, KbHookBase 实例)
# mtime 用于检测文件变更触发重载
_hook_cache: dict[str, tuple[float, KbHookBase]] = {}

# 缓存锁（仅保护字典读写，不保护模块加载）
_cache_lock = threading.Lock()


def _kb_hook_dir(kb_id: uuid.UUID | str) -> Path:
    """获取 KB 专属 Hook 脚本目录路径。

    Args:
        kb_id: 知识库 ID（UUID 或 hex 字符串）。

    Returns:
        Path: ``app/kb_hooks/{kb_id_hex}/``
    """
    kb_hex = kb_id.hex if isinstance(kb_id, uuid.UUID) else str(kb_id).replace("-", "")
    return _HOOKS_ROOT / kb_hex


def _kb_hook_file(kb_id: uuid.UUID | str) -> Path:
    """获取 KB 专属 Hook 脚本文件路径。"""
    return _kb_hook_dir(kb_id) / "hooks.py"


def _kb_id_hex(kb_id: uuid.UUID | str) -> str:
    """统一转 hex 形式。"""
    return kb_id.hex if isinstance(kb_id, uuid.UUID) else str(kb_id).replace("-", "")


# ============================================================
# Hook 加载
# ============================================================
async def load_kb_hook(kb_id: uuid.UUID | str) -> KbHookBase:
    """加载知识库的 Hook 实例。

    加载顺序：
    1. 检查缓存（命中且 mtime 未变则直接返回）
    2. 检查 Hook 脚本是否存在（不存在返回 DefaultKbHook）
    3. 从文件加载模块，构造 KbHook
    4. 加载失败返回 DefaultKbHook（不阻断主流程）

    Args:
        kb_id: 知识库 ID。

    Returns:
        KbHookBase: Hook 实例（KbHook 或 DefaultKbHook）。
    """
    kb_hex = _kb_id_hex(kb_id)
    hook_file = _kb_hook_file(kb_hex)

    # 脚本不存在：返回默认 Hook
    if not hook_file.exists():
        return DefaultKbHook()

    try:
        mtime = hook_file.stat().st_mtime
    except OSError:
        return DefaultKbHook()

    # 检查缓存
    with _cache_lock:
        cached = _hook_cache.get(kb_hex)
        if cached is not None and cached[0] == mtime:
            return cached[1]

    # 加载脚本
    hook = _load_hook_from_file(kb_hex, hook_file, mtime)
    return hook


def _load_hook_from_file(
    kb_hex: str, hook_file: Path, mtime: float
) -> KbHookBase:
    """从文件加载 Hook 模块并构造 KbHook。

    Args:
        kb_hex: KB ID 的 hex 形式。
        hook_file: Hook 脚本文件路径。
        mtime: 文件修改时间（用于缓存）。

    Returns:
        KbHookBase: 加载成功返回 KbHook，失败返回 DefaultKbHook。
    """
    try:
        # 使用唯一模块名避免冲突
        module_name = f"app.kb_hooks.{kb_hex}.hooks"
        spec = importlib.util.spec_from_file_location(module_name, hook_file)
        if spec is None or spec.loader is None:
            raise ImportError(f"无法创建 Hook 模块 spec: {hook_file}")

        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        hook = KbHook(kb_id=kb_hex, module=module)
        with _cache_lock:
            _hook_cache[kb_hex] = (mtime, hook)

        logger.info(
            "Hook 脚本已加载",
            kb_id=kb_hex,
            hook_file=str(hook_file),
            overrides=sorted(hook.overrides),
        )
        return hook

    except Exception as err:  # noqa: BLE001
        logger.error(
            "Hook 脚本加载失败，回退默认 Hook",
            kb_id=kb_hex,
            hook_file=str(hook_file),
            error=str(err),
            exc_info=True,
        )
        return DefaultKbHook()


# ============================================================
# Hook 写入与重载
# ============================================================
def write_kb_hook_script(kb_id: uuid.UUID | str, content: str) -> Path:
    """写入 KB 专属 Hook 脚本文件。

    用于领域模板初始化（``hook_template``）与配置中心在线编辑 Hook。

    Args:
        kb_id: 知识库 ID。
        content: Hook 脚本内容。

    Returns:
        Path: 写入的脚本文件路径。
    """
    kb_hex = _kb_id_hex(kb_id)
    hook_dir = _kb_hook_dir(kb_hex)
    hook_file = _kb_hook_file(kb_hex)

    # 确保目录存在（含 __init__.py 使其成为可导入包）
    hook_dir.mkdir(parents=True, exist_ok=True)
    init_file = hook_dir / "__init__.py"
    if not init_file.exists():
        init_file.write_text('"""KB Hook 包（自动生成）。"""\n', encoding="utf-8")

    hook_file.write_text(content, encoding="utf-8")

    # 清缓存，下次加载会重新读取
    clear_hook_cache(kb_hex)

    logger.info("Hook 脚本已写入", kb_id=kb_hex, hook_file=str(hook_file), size=len(content))
    return hook_file


def reload_kb_hook(kb_id: uuid.UUID | str) -> bool:
    """强制重载 KB Hook 脚本（清缓存，下次 load 重新读取）。

    用于 Hook 脚本在线编辑后立即生效。

    Args:
        kb_id: 知识库 ID。

    Returns:
        bool: 是否存在可重载的 Hook 脚本。
    """
    kb_hex = _kb_id_hex(kb_id)
    clear_hook_cache(kb_hex)
    hook_file = _kb_hook_file(kb_hex)
    exists = hook_file.exists()
    logger.info("Hook 缓存已清除，等待重新加载", kb_id=kb_hex, has_script=exists)
    return exists


def clear_hook_cache(kb_id: uuid.UUID | str | None = None) -> None:
    """清除 Hook 缓存。

    Args:
        kb_id: 指定 KB 则只清该 KB 缓存；None 清全部。
    """
    with _cache_lock:
        if kb_id is None:
            _hook_cache.clear()
        else:
            kb_hex = _kb_id_hex(kb_id)
            _hook_cache.pop(kb_hex, None)


def delete_kb_hook_script(kb_id: uuid.UUID | str) -> bool:
    """删除 KB 专属 Hook 脚本（删除整个目录）。

    用于知识库销毁时清理 Hook 文件，或配置中心「禁用 Hook」操作。

    Args:
        kb_id: 知识库 ID。

    Returns:
        bool: 是否删除了文件（False=脚本本就不存在）。
    """
    import shutil

    kb_hex = _kb_id_hex(kb_id)
    hook_dir = _kb_hook_dir(kb_hex)
    clear_hook_cache(kb_hex)

    if not hook_dir.exists():
        return False

    try:
        shutil.rmtree(hook_dir)
        logger.info("Hook 脚本目录已删除", kb_id=kb_hex, hook_dir=str(hook_dir))
        return True
    except OSError as err:
        logger.warning("Hook 脚本目录删除失败", kb_id=kb_hex, error=str(err))
        return False


def get_kb_hook_info(kb_id: uuid.UUID | str) -> dict[str, Any]:
    """获取 KB Hook 脚本信息（用于配置中心展示）。

    Args:
        kb_id: 知识库 ID。

    Returns:
        dict: 含 exists/path/size/overridden_interfaces 等字段。
    """
    kb_hex = _kb_id_hex(kb_id)
    hook_file = _kb_hook_file(kb_hex)

    info: dict[str, Any] = {
        "kb_id": kb_hex,
        "has_hook": False,
        "path": str(hook_file),
        "overridden_interfaces": [],
    }

    if not hook_file.exists():
        return info

    stat = hook_file.stat()
    info["has_hook"] = True
    info["size"] = stat.st_size
    info["mtime"] = stat.st_mtime

    # 尝试读取覆盖的接口（不实际执行，仅静态分析）
    try:
        content = hook_file.read_text(encoding="utf-8")
        from app.kb_hooks.base import STANDARD_HOOK_NAMES

        overridden = [
            name
            for name in STANDARD_HOOK_NAMES
            if f"def {name}" in content or f"async def {name}" in content
        ]
        info["overridden_interfaces"] = sorted(overridden)
    except OSError:
        pass

    return info
