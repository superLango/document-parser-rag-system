"""Prompt 模板管理器（YAML 加载 + 渲染）。

从 ``services/extraction/prompts/*.yaml`` 加载 prompt 模板，
提供变量替换和字段描述注入能力。

支持的模板变量（使用 ``{variable}`` 占位符）：
- ``{feature}``：项目大类名
- ``{context}``：文档上下文
- ``{prompt}``：schema 定义的 prompt
- ``{field_defs}``：字段定义文本
- ``{format_instruction}``：输出格式说明
- ``{whitelist_section}``：动态白名单段
- ``{prev_brands_section}``：前批牌号提示段
- ``{features_list}``：feature 列表（热处理用）
- ``{items前20个}``：前 20 个项目名
- ``{method_codes}``：方法标准号列表

使用示例::

    from app.services.extraction.prompts.prompt_manager import prompt_manager

    # 加载类别抽取 prompt
    rendered = prompt_manager.render_category_prompt(
        feature="化学成分",
        context="...",
        field_defs="...",
        format_instruction="...",
        whitelist_section="...",
    )
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.logging import get_logger

logger = get_logger(__name__)

# prompts 目录路径
_PROMPTS_DIR = Path(__file__).parent


class PromptManager:
    """Prompt 模板管理器。

    加载并缓存 YAML 模板文件，提供变量替换接口。
    所有模板在首次访问时加载，后续从缓存读取。
    """

    def __init__(self) -> None:
        """初始化，模板懒加载。"""
        self._templates: dict[str, dict[str, Any]] = {}
        self._field_descriptions: dict[str, dict[str, Any]] | None = None

    def load_template(self, name: str) -> dict[str, Any]:
        """加载指定名称的 YAML 模板。

        Args:
            name: 模板名（不含 .yaml 后缀），如 "category_glmocr"。

        Returns:
            dict: 模板内容，含 system_prompt / user_template / fields 等键。
        """
        if name not in self._templates:
            yaml_path = _PROMPTS_DIR / f"{name}.yaml"
            if not yaml_path.exists():
                raise FileNotFoundError(f"Prompt 模板不存在: {yaml_path}")
            with open(yaml_path, encoding="utf-8") as f:
                self._templates[name] = yaml.safe_load(f) or {}
            logger.debug("Prompt 模板已加载", extra={"name": name, "path": str(yaml_path)})
        return self._templates[name]

    def load_field_descriptions(self) -> dict[str, dict[str, Any]]:
        """加载字段描述定义（field_descriptions.yaml）。

        Returns:
            dict: 字段名→描述字典，每项含 description / required / enum_source。
        """
        if self._field_descriptions is None:
            yaml_path = _PROMPTS_DIR / "field_descriptions.yaml"
            if not yaml_path.exists():
                logger.warning("field_descriptions.yaml 不存在，返回空字典")
                return {}
            with open(yaml_path, encoding="utf-8") as f:
                self._field_descriptions = yaml.safe_load(f) or {}
        return self._field_descriptions

    def render(
        self,
        template_text: str,
        variables: dict[str, str],
    ) -> str:
        """渲染模板文本（变量替换）。

        使用 ``str.format`` 进行变量替换，未提供的变量保留原样。
        注意：JSON 花括号需在模板中使用 ``{{ }}`` 转义。

        Args:
            template_text: 含 ``{variable}`` 占位符的模板文本。
            variables: 变量字典。

        Returns:
            str: 渲染后的文本。
        """
        try:
            return template_text.format(**variables)
        except KeyError as err:
            logger.warning(
                "Prompt 模板变量缺失，保留原样",
                extra={"missing_var": str(err)},
            )
            # 逐个替换已提供的变量
            result = template_text
            for key, val in variables.items():
                result = result.replace(f"{{{key}}}", str(val))
            return result

    def render_doc_info_prompt(
        self,
        context: str,
    ) -> tuple[str, str]:
        """渲染基础信息抽取 prompt（第一部分）。

        Args:
            context: 文档上下文文本。

        Returns:
            tuple: (system_prompt, user_prompt)
        """
        template = self.load_template("doc_info")
        system = template.get("system_prompt", "")
        user = self.render(template.get("user_template", ""), {"context": context})
        return system, user

    def render_category_prompt(
        self,
        feature: str,
        prompt: str | None,
        field_defs: str,
        format_instruction: str,
        context: str,
        whitelist_section: str = "",
        prev_brands_section: str = "",
    ) -> tuple[str, str]:
        """渲染类别抽取 prompt（第二部分，glmocr 线路）。

        Args:
            feature: 项目大类名。
            prompt: schema 定义的 prompt（为空用模板默认 default_prompt）。
            field_defs: 字段定义文本。
            format_instruction: 输出格式说明。
            context: 文档上下文。
            whitelist_section: 动态白名单段（可选）。
            prev_brands_section: 前批牌号提示段（可选）。

        Returns:
            tuple: (system_prompt, user_prompt)
        """
        template = self.load_template("category_glmocr")

        # 渲染 system prompt（含 feature）
        system = self.render(
            template.get("system_prompt", ""),
            {"feature": feature},
        )

        # 使用 schema prompt 或默认 prompt
        user_prompt = prompt or template.get("default_prompt", "")
        user_prompt = self.render(user_prompt, {"feature": feature})

        # 渲染 user template
        user = self.render(
            template.get("user_template", ""),
            {
                "feature": feature,
                "prompt": user_prompt,
                "field_defs": field_defs,
                "format_instruction": format_instruction,
                "whitelist_section": whitelist_section,
                "prev_brands_section": prev_brands_section,
                "context": context,
            },
        )
        return system, user

    def render_heat_treatment_prompt(
        self,
        context: str,
        features_list: str,
    ) -> tuple[str, str]:
        """渲染热处理制度抽取 prompt（第三部分）。

        Args:
            context: 文档上下文。
            features_list: feature 列表文本（逗号分隔）。

        Returns:
            tuple: (system_prompt, user_prompt)
        """
        template = self.load_template("heat_treatment")
        system = template.get("system_prompt", "")
        user = self.render(
            template.get("user_template", ""),
            {"context": context, "features_list": features_list},
        )
        return system, user

    def get_field_description(self, field_name: str) -> dict[str, Any]:
        """获取指定字段的描述定义。

        Args:
            field_name: 字段名（如 "项目名称"）。

        Returns:
            dict: 含 description / required / enum_source。
        """
        descriptions = self.load_field_descriptions()
        return descriptions.get(field_name, {"description": field_name})

    @staticmethod
    def get_temperature_rules() -> str:
        """获取温度区分规则文本（glmocr / langextract 两线路共享）。

        与 category_glmocr.yaml 的 [温度区分规则] 段保持一致，
        供 LangExtract 线路注入 prompt_description，确保两线路行为对齐。

        Returns:
            str: 温度区分规则多行文本。
        """
        return (
            "- 高温拉伸：只抽取试验温度明确为高温（如650℃、800℃等>100℃）的数据，不抽取室温数据\n"
            "- 低温拉伸：只抽取试验温度明确为低温（如-196℃、-70℃等<0℃）的数据，不抽取室温数据\n"
            "- 室温拉伸：抽取试验温度为室温、常温或20℃左右的数据\n"
            "- 试验温度字段必须从文档对应的温度列或表头中提取，不能凭空猜测\n"
            "- 如果文档中没有明确温度信息，默认按室温处理"
        )

    def build_field_defs_text(
        self,
        feature: str,
        field_names: list[str],
        items: list[str] | None = None,
        methods: list[str] | None = None,
    ) -> str:
        """构建字段定义文本（注入 prompt 帮助模型理解抽取目标）。

        Args:
            feature: 项目大类名。
            field_names: 字段名列表。
            items: 标准项目名列表（用于 "项目名称" 字段描述填充）。
            methods: 方法列表（用于 "试验方法" 字段描述填充）。

        Returns:
            str: 字段定义文本（多行）。
        """
        descriptions = self.load_field_descriptions()
        items_str = "、".join(items[:20]) if items else ""
        methods_str = "、".join(methods[:10]) if methods else ""

        lines: list[str] = []
        for name in field_names:
            desc_def = descriptions.get(name, {"description": name})
            desc = desc_def.get("description", name)
            # 替换描述中的占位符
            desc = desc.replace("{feature}", feature)
            desc = desc.replace("{items前20个}", items_str)
            desc = desc.replace("{method_codes}", methods_str)

            required = desc_def.get("required", False)
            enum_source = desc_def.get("enum_source")
            line = f"- {name}: {desc}"
            if required:
                line += "（必填）"
            if enum_source == "items" and items:
                line += f"\n  可选值: {items_str}"
            elif enum_source == "methods" and methods:
                line += f"\n  可选值: {methods_str}"
            lines.append(line)

        return "\n".join(lines)


@lru_cache(maxsize=1)
def get_prompt_manager() -> PromptManager:
    """返回全局 PromptManager 单例。"""
    return PromptManager()


# 模块级单例
prompt_manager = get_prompt_manager()
