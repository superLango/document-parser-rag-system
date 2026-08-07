"""配置驱动 Prompt 渲染模块。

Prompt 模板取自抽取配置中心（``kb_prompt_templates``），由
``config_prompt_renderer`` 渲染，类别未绑定模板时直接报错（无内置回退）。
"""

from app.services.extraction.prompts.config_prompt_renderer import (
    ConfigPromptRenderer,
    config_prompt_renderer,
)

__all__ = ["ConfigPromptRenderer", "config_prompt_renderer"]
