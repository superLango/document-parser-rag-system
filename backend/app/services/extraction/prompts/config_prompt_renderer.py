"""配置驱动 Prompt 渲染器。

从抽取配置中心（``kb_prompt_templates``）渲染所有抽取 Prompt，模板正文
使用 ``${variable}`` 占位符，由本渲染器替换。**不做任何回退**：类别未绑定
Prompt 模板时直接抛 ``BusinessException``（与 Schema 一致：有执行，没有就
报错），不读取任何 YAML 内置模板，也不回退到 simple 全局模板。

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

import json
import re
from typing import Any

from app.core.exceptions import BusinessException
from app.core.logging import get_logger
from app.services.extraction.rule_engine.term_base_loader import term_base_loader

logger = get_logger(__name__)


class ConfigPromptRenderer:
    """从 ``ExtractionDomainConfig`` 渲染抽取 Prompt。"""

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
            (system_prompt, user_prompt) 元组。

        Raises:
            BusinessException: 类别未绑定 Prompt 模板时抛错，不静默跳过、
                不回退到任何内置/全局模板（与 Schema 一致：有执行，没有就报错）。
        """
        resolved = cfg.prompt_for_category(target.template_id, target.category_id) if cfg is not None else None
        if resolved is None:
            raise BusinessException(
                f"未配置类别「{target.feature}」的 Prompt 模板，请配置（类别必须显式绑定 Prompt 模板，不做回退）"
            )
        system, user = resolved

        # 字段名 -> 字段定义（供 ${字段名} / ${字段名.子属性} 替换）
        field_map: dict[str, dict[str, Any]] = {
            f.get("name"): f
            for f in (target.fields or [])
            if f.get("name")
        }
        schema_json = json.dumps(target.schema, ensure_ascii=False) if target.schema else ""

        # 系统参数（对齐前端 PromptEditor「测试组装」可替换的占位符）
        system_values: dict[str, Any] = {
            "feature": target.feature,
            "category_name": target.feature,
            "context": context,
            "field_defs": field_defs,
            "format_instruction": format_instruction,
            "whitelist_section": whitelist,
            "prev_brands_section": prev_brands,
            "query_terms": "、".join(target.query_terms or []),
            "feature_descript": target.description,
            "return_type": target.return_type or "array",
            "prev_brands": prev_brands,
            "schema": schema_json,
        }

        def _sub(match: re.Match) -> str:
            raw = match.group(1).strip()
            # 术语集 / 字段子属性：${xxx.yyy}
            if "." in raw:
                label, attr = raw.split(".", 1)
                # 术语集字段：${术语集label.字段}
                if label in (target.term_data or {}):
                    vals = term_base_loader.get_group_values(target.term_data[label], attr)
                    if vals:
                        return f"[{', '.join(vals)}]"
                    return match.group(0)
                # 字段子属性
                if label in field_map:
                    f = field_map[label]
                    attr_val = {
                        "类型": f.get("type", ""),
                        "必填": "是" if f.get("required") else "否",
                        "描述": f.get("description", ""),
                        "示例": f.get("example", "") or "",
                        "枚举": "",
                        "术语集": "",
                    }.get(attr)
                    if attr_val is not None:
                        return str(attr_val)
                return match.group(0)
            # 字段名：仅代入字段名称
            if raw in field_map:
                return raw
            # 系统参数
            if raw in system_values:
                return str(system_values[raw])
            return match.group(0)

        def _render(text: str) -> str:
            if not text:
                return text
            return re.sub(r"\$\{([^{}]+)\}", _sub, text)

        rendered_system = _render(system)
        rendered_user = _render(user)

        # 【调试】打印渲染出的完整 system/user prompt（Prompt 获取结果）
        logger.info(
            "【Prompt 渲染输出】类别抽取 Prompt（system + user 完整内容）",
            extra={
                "feature": target.feature,
                "template_id": target.template_id,
                "category_id": target.category_id,
                "field_defs": field_defs,
                "format_instruction": format_instruction,
                "system_prompt": rendered_system,
                "user_prompt": rendered_user,
            },
        )
        return rendered_system, rendered_user

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