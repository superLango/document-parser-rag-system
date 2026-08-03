"""v3 抽取 Prompt 模板模块。

提供 YAML 模板加载、变量渲染、字段描述注入能力。
"""

from app.services.extraction.prompts.prompt_manager import (
    PromptManager,
    get_prompt_manager,
    prompt_manager,
)

__all__ = ["PromptManager", "get_prompt_manager", "prompt_manager"]
