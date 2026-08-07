"""配置驱动 Prompt 渲染器。

替代原先 ``prompts/*.yaml`` 内置模板，从抽取配置中心（``kb_prompt_templates``）
渲染所有抽取 Prompt。模板正文使用 ``${variable}`` 占位符，由本渲染器替换。

与内置 ``prompt_manager`` 的区别：
- 模板来源：配置中心（全局配置 / Prompt 模板），不读取任何 YAML 文件。
- 字段定义：从 ``ExtractionTarget.fields``（Schema 模板字段）构建，不再读取
  ``field_descriptions.yaml``。

占位符变量（渲染时可用）：
- ${feature} / ${category_name}：类别名
- ${context}：文档检索上下文
- ${field_defs}：字段定义文本
- ${format_instruction}：输出格式说明
- ${whitelist_section}：白名单约束段
- ${prev_brands_section}：前批牌号提示段
- ${query_terms}：检索查询词组
- ${features_list}：类别列表（热处理用）

使用示例::

    from app.services.extraction.prompts.config_prompt_renderer import config_prompt_renderer

    system, user = config_prompt_renderer.render_category(target, cfg, context, ...)
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


class ConfigPromptRenderer:
    """从 ``ExtractionDomainConfig`` 渲染抽取 Prompt。"""

    # ------------------------------------------------------------------
    # 变量替换
    # ------------------------------------------------------------------
    @staticmethod
    def _render(text: str, variables: dict[str, Any]) -> str:
        """替换 ``${var}`` 占位符。"""
        if not text:
            return text
        for key, val in variables.items():
            text = text.replace(f"${{{key}}}", str(val))
        return text

    # ------------------------------------------------------------------
    # 类别抽取 Prompt
    # ------------------------------------------------------------------
    def render_category(
        self,
        target: Any,
        cfg: Any,
        context: str,
        field_defs: str,
        format_instruction: str,
        whitelist: str = "",
        prev_brands: str = "",
    ) -> tuple[str, str]:
        """渲染类别抽取 Prompt（glmocr / langextract 共用）。

        Args:
            target: ExtractionTarget（含 category_id / template_id / feature）。
            cfg: ExtractionDomainConfig。
            context: 文档上下文。
            field_defs: 字段定义文本。
            format_instruction: 输出格式说明。
            whitelist: 白名单约束段。
            prev_brands: 前批牌号提示段。

        Returns:
            (system_prompt, user_prompt) 元组；未配置模板时返回 ("", user)。
        """
        resolved = cfg.prompt_for_category(target.template_id, target.category_id) if cfg is not None else None
        if resolved is None:
            logger.warning(
                "未找到类别绑定的 Prompt 模板，跳过该类别抽取（不降级到内置 prompt）",
                extra={
                    "feature": target.feature,
                    "template_id": target.template_id,
                    "category_id": target.category_id,
                },
            )
            # 无模板时返回空，由调用方跳过类别（prompt 全程走配置，不降级到硬编码）
            system = ""
            user = ""
        else:
            system, user = resolved

        variables = {
            "feature": target.feature,
            "category_name": target.feature,
            "context": context,
            "field_defs": field_defs,
            "format_instruction": format_instruction,
            "whitelist_section": whitelist,
            "prev_brands_section": prev_brands,
            "query_terms": "、".join(target.query_terms or []),
        }
        return self._render(system, variables), self._render(user, variables)

    # ------------------------------------------------------------------
    # 字段定义文本（从 target.fields 构建，不读 YAML）
    # ------------------------------------------------------------------
    @staticmethod
    def build_field_defs(target: Any) -> str:
        """从 Schema 模板字段构建字段定义文本。

        Returns:
            str: 多行字段定义文本。
        """
        lines: list[str] = []
        for f in target.fields or []:
            name = f.get("name", "")
            desc = f.get("description") or name
            required = f.get("required", False)
            line = f"- {name}: {desc}"
            if required:
                line += "（必填）"
            lines.append(line)
        return "\n".join(lines)


# 模块级单例
config_prompt_renderer = ConfigPromptRenderer()