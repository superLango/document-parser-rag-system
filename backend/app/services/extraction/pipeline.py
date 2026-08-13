"""结构化抽取主流水线（E3 实现，E1 仅占位）。"""

from app.core.exceptions import BusinessException


async def run(*, kb_id, document_id, progress_cb=None) -> dict:
    """抽取流水线入口。

    E1 阶段仅占位：E3 将实现 类别构建 → 检索上下文 → Prompt 渲染 → LLM 抽取
    → 后处理/校验 → 结果返回。当前显式报错，避免产生伪成功结果。
    """
    raise BusinessException(message="结构化抽取流水线尚未实现（E3 阶段）")
