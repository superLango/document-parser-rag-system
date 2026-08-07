"""Hook 接口定义与默认实现。

定义知识库 Hook 的标准接口（抽象基类 ``KbHookBase``）、默认实现
（``DefaultKbHook``）与动态加载实现（``KbHook``）。

标准 Hook 接口（全部可选，缺失回退默认）：

    async def extract_candidates(text: str, regex_rules: list[dict], **ctx) -> list[str]:
        '''从文本提取候选项目名（由配置的 regex_rules 驱动）。'''

    def build_category_schema(category: dict, **ctx) -> dict | None:
        '''构造类别的 output_schema。返回 None 用默认 schema 生成逻辑。'''

    async def validate_record(record: dict, category: str, **ctx) -> tuple[bool, str]:
        '''校验单条记录。返回 (是否合法, 拒绝原因)。'''

    async def post_process(records: list[dict], category: str, **ctx) -> list[dict]:
        '''抽取结果后处理（去重、排序、补全等）。'''

    def category_match(item_name: str, category: str, **ctx) -> bool:
        '''项目名与类别匹配校验。替代跨类混入检测的默认逻辑。'''

    def build_doc_info_prompt(doc_info_fields: list[dict], **ctx) -> str:
        '''构造文档信息抽取提示词。'''

接口约定：
1. 函数名与上述一致，参数按位置传前几个，关键字参数传 ctx
2. 函数可为同步或异步（async def），加载器统一 await
3. 返回值类型与上述一致
"""

from __future__ import annotations

import inspect
from typing import Any, Callable

from app.core.logging import get_logger

logger = get_logger(__name__)


# 标准 Hook 接口名集合
STANDARD_HOOK_NAMES: frozenset[str] = frozenset(
    {
        "extract_candidates",
        "build_category_schema",
        "validate_record",
        "post_process",
        "category_match",
        "build_doc_info_prompt",
    }
)


class KbHookBase:
    """Hook 抽象基类。

    子类应覆盖各 ``default_*`` 方法提供默认实现，并实现 ``has`` / ``call``
    以支持动态接口查询与调用。
    """

    def has(self, name: str) -> bool:
        """判断是否提供指定 Hook 接口。"""
        if name not in STANDARD_HOOK_NAMES:
            return False
        method = getattr(self, name, None)
        return callable(method)

    async def call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """调用指定 Hook 接口。

        若该接口未被覆盖（即回退到 ``default_*``），仍会调用默认实现。
        子类的 ``call`` 可区分「用户覆盖」与「默认实现」。
        """
        if name not in STANDARD_HOOK_NAMES:
            raise ValueError(f"非标准 Hook 接口: {name}")
        method = getattr(self, name, None)
        if method is None:
            raise AttributeError(f"Hook 接口 {name} 未实现")
        result = method(*args, **kwargs)
        if inspect.isawaitable(result):
            result = await result
        return result

    # ---------------------------------------------------------------
    # 默认实现（子类可覆盖）
    # ---------------------------------------------------------------
    async def extract_candidates(
        self, text: str, regex_rules: list[dict] | None = None, **ctx: Any
    ) -> list[str]:
        """默认候选项目提取：按 regex_rules 逐条正则匹配去重。"""
        import re

        if not regex_rules:
            return []
        candidates: list[str] = []
        seen: set[str] = set()
        for rule in regex_rules:
            pattern = rule.get("pattern") if isinstance(rule, dict) else None
            if not pattern:
                continue
            try:
                for m in re.finditer(pattern, text):
                    val = m.group(0)
                    if val not in seen:
                        seen.add(val)
                        candidates.append(val)
            except re.error as err:
                logger.warning("Hook 默认正则匹配失败", pattern=pattern, error=str(err))
        return candidates

    def build_category_schema(self, category: dict, **ctx: Any) -> dict | None:
        """默认 schema 构造：返回 None，交由 extraction_schemas 默认逻辑生成。"""
        return None

    async def validate_record(
        self, record: dict, category: str, **ctx: Any
    ) -> tuple[bool, str]:
        """默认记录校验：仅校验必填字段（牌号、项目非空）。"""
        if not record.get("牌号"):
            return False, "牌号为空"
        if not record.get("项目"):
            return False, "项目为空"
        return True, ""

    async def post_process(
        self, records: list[dict], category: str, **ctx: Any
    ) -> list[dict]:
        """默认后处理：按牌号+项目去重。"""
        seen: set[tuple] = set()
        deduped: list[dict] = []
        for r in records:
            key = (r.get("牌号", ""), r.get("项目", ""))
            if key in seen:
                continue
            seen.add(key)
            deduped.append(r)
        return deduped

    def category_match(self, item_name: str, category: str, **ctx: Any) -> bool:
        """默认类别匹配：返回 True（由术语集/规则负责精确校验）。"""
        return True

    def build_doc_info_prompt(self, doc_info_fields: list[dict], **ctx: Any) -> str:
        """默认文档信息提示词：列出字段名与描述。"""
        if not doc_info_fields:
            return "提取文档的基本信息。"
        lines = ["请提取以下文档基本信息字段："]
        for f in doc_info_fields:
            name = f.get("name", "")
            desc = f.get("description", "")
            lines.append(f"- {name}：{desc}")
        return "\n".join(lines)


class DefaultKbHook(KbHookBase):
    """默认 Hook 实现（无任何用户覆盖）。

    所有接口回退到 ``KbHookBase`` 的默认实现。当 KB 未配置 Hook 脚本时使用。
    """

    pass


class KbHook(KbHookBase):
    """动态加载的 KB Hook 实现。

    从用户 Hook 脚本（``hooks.py``）加载已定义的标准接口函数，覆盖默认实现。
    未定义的接口回退到 ``KbHookBase`` 的默认实现。

    Attributes:
        kb_id: 所属知识库 ID。
        module: 已加载的 Hook 模块对象。
        overrides: 该 Hook 脚本覆盖的接口名集合。
    """

    def __init__(self, kb_id: Any, module: Any) -> None:
        self.kb_id = kb_id
        self.module = module
        self.overrides: set[str] = {
            name
            for name in STANDARD_HOOK_NAMES
            if hasattr(module, name) and callable(getattr(module, name))
        }

    def has(self, name: str) -> bool:
        """判断是否提供指定接口（含默认实现）。"""
        return name in STANDARD_HOOK_NAMES

    def has_override(self, name: str) -> bool:
        """判断指定接口是否被用户脚本覆盖。"""
        return name in self.overrides

    async def call(self, name: str, *args: Any, **kwargs: Any) -> Any:
        """调用指定接口。

        优先调用用户脚本覆盖的实现；未覆盖则回退到默认实现。
        """
        if name not in STANDARD_HOOK_NAMES:
            raise ValueError(f"非标准 Hook 接口: {name}")

        func: Callable | None = None
        if name in self.overrides:
            func = getattr(self.module, name, None)
        if func is None:
            # 回退到默认实现
            func = getattr(self, name, None)
        if func is None:
            raise AttributeError(f"Hook 接口 {name} 未实现")

        try:
            result = func(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            return result
        except Exception as err:
            logger.error(
                "Hook 接口调用失败，回退默认",
                kb_id=str(self.kb_id),
                hook=name,
                error=str(err),
                exc_info=True,
            )
            # 调用失败时回退到默认实现
            default_func = getattr(self, name, None)
            if default_func is None:
                raise
            result = default_func(*args, **kwargs)
            if inspect.isawaitable(result):
                result = await result
            return result

    def describe(self) -> dict[str, Any]:
        """描述该 Hook 的覆盖情况（用于配置中心展示）。"""
        return {
            "kb_id": str(self.kb_id),
            "has_hook": True,
            "overridden_interfaces": sorted(self.overrides),
            "available_interfaces": sorted(STANDARD_HOOK_NAMES),
        }
