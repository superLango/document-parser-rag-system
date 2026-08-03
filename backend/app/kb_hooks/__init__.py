"""知识库 Hook 机制包。

Hook 机制为「无法通用化的特殊领域逻辑」提供可配置的扩展点。每个知识库
可携带一个独立的 Hook 脚本（``app/kb_hooks/{kb_id_hex}/hooks.py``），
覆盖默认行为。

标准 Hook 接口（均为可选，缺失则回退到默认逻辑）：
- ``extract_candidates``：候选项目提取（替代硬编码正则）
- ``build_category_schema``：构造类别 output_schema
- ``validate_record``：单条记录校验
- ``post_process``：抽取结果后处理
- ``category_match``：项目名-类别匹配校验
- ``build_doc_info_prompt``：文档信息抽取提示词构造

设计原则：
1. Hook 脚本按 KB 独立存放，物理隔离（合规要求）
2. 通过 importlib 动态加载，按文件 mtime 缓存
3. Hook 函数可选，缺失回退默认，加载失败不阻断主流程
4. Hook 函数可为同步或异步（async），加载器统一处理

模块结构：
- ``base``：Hook 接口定义与默认实现
- ``registry``：Hook 加载器与注册表
- ``default_hook``：默认 Hook 脚本模板（用户参考与回退）

使用示例::

    from app.kb_hooks.registry import load_kb_hook
    hook = await load_kb_hook(kb_id)
    if hook and hook.has("post_process"):
        records = await hook.call("post_process", records, category="化学成分")
"""

from app.kb_hooks.base import DefaultKbHook, KbHook, KbHookBase
from app.kb_hooks.registry import (
    clear_hook_cache,
    load_kb_hook,
    reload_kb_hook,
    write_kb_hook_script,
)

__all__ = [
    "DefaultKbHook",
    "KbHook",
    "KbHookBase",
    "clear_hook_cache",
    "load_kb_hook",
    "reload_kb_hook",
    "write_kb_hook_script",
]
