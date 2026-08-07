"""配置驱动 Prompt 渲染模块。

Prompt 模板完全取自抽取配置中心（``kb_prompt_templates``），由
``config_prompt_renderer`` 渲染，类别未绑定模板时直接报错（无任何内置
YAML / simple 全局模板回退）。已移除遗留的 ``prompt_manager``（YAML
内置模板）与 ``prompt_renderer``。
"""

from app.services.extraction.prompts.config_prompt_renderer import (
    ConfigPromptRenderer,
    config_prompt_renderer,
)

__all__ = ["ConfigPromptRenderer", "config_prompt_renderer"]
