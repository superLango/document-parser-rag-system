"""默认 Hook 脚本模板。

本文件作为新建 Hook 脚本的参考模板，由领域模板服务或配置中心写入到
``app/kb_hooks/{kb_id_hex}/hooks.py``。用户可在此基础上修改，覆盖默认逻辑。

标准 Hook 接口（全部可选，仅实现需要的即可）：

    async def extract_candidates(text, regex_rules, **ctx) -> list[str]:
        '''候选项目提取（替代硬编码正则）'''

    def build_category_schema(category, **ctx) -> dict | None:
        '''构造类别 output_schema，返回 None 用默认'''

    async def validate_record(record, category, **ctx) -> tuple[bool, str]:
        '''单条记录校验，返回 (是否合法, 拒绝原因)'''

    async def post_process(records, category, **ctx) -> list[dict]:
        '''抽取结果后处理（去重、排序、补全等）'''

    def category_match(item_name, category, **ctx) -> bool:
        '''项目名-类别匹配校验'''

    def build_doc_info_prompt(doc_info_fields, **ctx) -> str:
        '''文档信息抽取提示词构造'''

ctx 关键字参数约定（调用方传入）：
    kb_id: 当前知识库 ID
    kb_config: KBConfig 对象（含 categories/field_templates 等）
    db: 异步数据库会话（RLS 已激活）
    其他领域上下文（如 recalled_chunks、embedding 等）
"""

from __future__ import annotations

from typing import Any


# ============================================================
# 示例：候选项目提取
# ============================================================
async def extract_candidates(
    text: str,
    regex_rules: list[dict] | None = None,
    **ctx: Any,
) -> list[str]:
    """候选项目提取。

    默认实现：按 regex_rules 逐条正则匹配去重。
    如需自定义（如基于 NER 模型、领域词典），可覆盖本方法。

    Args:
        text: 待提取的文本。
        regex_rules: 正则规则列表，每项含 pattern/name。
        **ctx: 上下文（kb_id/kb_config/db 等）。

    Returns:
        list[str]: 候选项目名列表（去重）。
    """
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
        except re.error:
            continue
    return candidates


# ============================================================
# 示例：记录后处理
# ============================================================
async def post_process(
    records: list[dict],
    category: str,
    **ctx: Any,
) -> list[dict]:
    """抽取结果后处理。

    默认实现：按 (牌号, 项目) 去重。
    可在此添加领域特定逻辑，如：
    - 单位标准化（MPa→兆帕）
    - 数值范围解析（"≥345"→下限 345）
    - 跨记录关联（同牌号合并）

    Args:
        records: 抽取出的记录列表。
        category: 当前类别名。
        **ctx: 上下文。

    Returns:
        list[dict]: 处理后的记录列表。
    """
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for r in records:
        key = (r.get("牌号", ""), r.get("项目", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    return deduped


# ============================================================
# 示例：记录校验
# ============================================================
async def validate_record(
    record: dict,
    category: str,
    **ctx: Any,
) -> tuple[bool, str]:
    """单条记录校验。

    默认实现：仅校验必填字段（牌号、项目非空）。
    可在此添加领域校验，如：
    - 项目名是否在该类别的 enum 取值范围内
    - 数值是否在合理范围
    - 调用向量检索校验跨类混入

    Args:
        record: 待校验记录。
        category: 当前类别名。
        **ctx: 上下文。

    Returns:
        tuple[bool, str]: (是否合法, 拒绝原因，合法时为空)。
    """
    if not record.get("牌号"):
        return False, "牌号为空"
    if not record.get("项目"):
        return False, "项目为空"
    return True, ""


# 以下接口未实现，将回退到默认逻辑：
# - build_category_schema
# - category_match
# - build_doc_info_prompt
