"""``${variable}`` 参数渲染器（替代 YAML 硬编码 prompt）。

根据用户配置的 Prompt 模板（system_prompt / user_prompt），将 ``${xxx}``
占位符替换为对应参数的实际值，实现 Prompt 完全配置化。

占位符语法：
- 系统参数：``${feature}``、``${feature_descript}``、``${schema}``、
  ``${context}``、``${return_type}``、``${prev_brands}``
- 字段引用：``${字段名}`` → 该字段的完整定义文本（含类型/必填/描述/示例/枚举/术语集）
- 字段子属性：``${字段名.类型}``、``${字段名.必填}``、``${字段名.描述}``、
  ``${字段名.示例}``、``${字段名.枚举}``、``${字段名.术语集}``

未匹配的 ``${xxx}`` 保留原样，避免误替换。
"""

from __future__ import annotations

import re
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

# 匹配 ${xxx} 或 ${xxx.yyy}
_VAR_RE = re.compile(r"\$\{([^{}]+)\}")

# 字段子属性键
_FIELD_ATTRS = ("类型", "必填", "描述", "示例", "枚举", "术语集")


class PromptRenderer:
    """通用 ``${xxx}`` 参数渲染器。

    在渲染前通常需先构建 ``fields`` 上下文（当前类别的字段定义），
    以及 ``context`` 字典（系统参数 / Schema 模板信息）。
    """

    def render(
        self,
        template: str,
        context: dict[str, Any] | None = None,
        fields: list[dict[str, Any]] | None = None,
    ) -> str:
        """渲染模板中的 ``${xxx}`` 占位符。

        Args:
            template: 含 ``${xxx}`` 占位符的模板文本。
            context: 系统参数与 Schema 信息字典（变量名 → 实际值）。
            fields: 当前类别的字段定义列表。每项含
                name / type / description / example / required / enum / term_base。

        Returns:
            str: 渲染后的文本，未匹配占位符保留原样。
        """
        if not template:
            return template

        context = context or {}
        fields = fields or []
        field_map = {f.get("name", ""): f for f in fields if f.get("name")}

        def _replace(match: re.Match) -> str:
            key = match.group(1).strip()

            # 字段子属性：${字段名.属性}
            if "." in key:
                field_name, attr = key.split(".", 1)
                field = field_map.get(field_name)
                if field is not None and attr in _FIELD_ATTRS:
                    return self._field_attr(field, attr)
                return match.group(0)  # 未匹配保留

            # 直接字段名：${字段名}
            if key in field_map:
                return self._field_def_text(field_map[key])

            # 系统参数 / Schema 信息
            if key in context:
                return str(context[key])

            return match.group(0)  # 未匹配保留

        return _VAR_RE.sub(_replace, template)

    # ------------------------------------------------------------------
    # 内部方法
    # ------------------------------------------------------------------

    @staticmethod
    def _field_attr(field: dict[str, Any], attr: str) -> str:
        """返回字段的单个子属性实际值。"""
        if attr == "类型":
            return str(field.get("type") or "string")
        if attr == "必填":
            return "是" if field.get("required") else "否"
        if attr == "描述":
            return str(field.get("description") or "")
        if attr == "示例":
            example = field.get("example")
            return str(example) if example else ""
        if attr == "枚举":
            enum = field.get("enum")
            return "、".join(str(e) for e in enum) if enum else ""
        if attr == "术语集":
            return str(field.get("term_base") or "")
        return ""

    @staticmethod
    def _field_def_text(field: dict[str, Any]) -> str:
        """构建字段的完整定义文本（供 ${字段名} 替换）。"""
        parts: list[str] = []
        name = str(field.get("name") or "")
        type_ = str(field.get("type") or "string")
        desc = str(field.get("description") or "")
        required = bool(field.get("required"))
        example = field.get("example")
        enum = field.get("enum")
        term_base = field.get("term_base")

        line = f"- {name}（{type_}）"
        if required:
            line += "，必填"
        parts.append(line)
        if desc:
            parts.append(f"  {name}说明: {desc}")
        if example:
            parts.append(f"  示例: {example}")
        if enum:
            parts.append(f"  可选值: {'、'.join(str(e) for e in enum)}")
        if term_base:
            parts.append(f"  术语集: {term_base}")
        return "\n".join(parts)


# 模块级单例
prompt_renderer = PromptRenderer()