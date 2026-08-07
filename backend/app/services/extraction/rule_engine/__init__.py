"""规则引擎（后处理 + 校验规则化）。

将 v3 硬编码的后处理 / 校验改造为可配置规则：
- registry：内置规则注册表（元数据 + 参数 schema）
- term_base_loader：术语集动态加载器
- script_manager：脚本执行管理（替代原 engine 硬编码后处理管道）
"""

from app.services.extraction.rule_engine.registry import (
    RULE_REGISTRY,
    default_enabled_map,
    get_builtin_rule,
)
from app.services.extraction.rule_engine.term_base_loader import (
    TermBaseValueLoader,
    term_base_loader,
)

__all__ = [
    "RULE_REGISTRY",
    "default_enabled_map",
    "get_builtin_rule",
    "TermBaseValueLoader",
    "term_base_loader",
]