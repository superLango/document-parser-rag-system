"""抽取配置完整性校验服务。

在抽取任务提交前对知识库的抽取配置做**全量显式校验**（用户要求最严格：
不回退、不静默补默认）。任何一项未显式配置或配置无效都会返回错误提示，
直到全部配置通过校验后才能成功提交任务。

校验范围：
1. 全局配置：``kb_extraction_config.content`` 中所有有效参数必须**显式填写**
   （不允许依赖内置默认值兜底）。
2. LLM 端点三元组：``kb.config.extraction``（api_base / model）必须有效。
3. Schema 模板：至少存在一个启用的 Schema 模板。
4. Prompt 模板：必须已配置（不回退内置）。
5. 重排模型：若 ``retrieval.reranker.enabled`` 开启，须能加载重排模型，
   否则在提交前阻止并提示（不做静默降级）。

对外接口：
- ``validate_extraction_config(db, kb_id) -> list[str]``：返回错误提示列表（空则通过）。
- ``ensure_extraction_config_valid(db, kb_id) -> None``：失败抛出 ``BusinessException``。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessException
from app.core.logging import get_logger
from app.models.extraction_config import KbExtractionConfig
from app.models.schema_model import SchemaTemplate
from app.services.extraction.retrieval.reranker import retrieval_reranker
from app.services.extraction_config.defaults import (
    DEFAULT_EXTRACTION_CONFIG,
    ENGINE_BASE_EXTRACT,
    ENGINE_LANG_EXTRACT,
)
from app.services.extraction_config.resolver import ExtractionConfigResolver

logger = get_logger(__name__)

_config_resolver = ExtractionConfigResolver()

# 合法引擎值
_VALID_ENGINES = (ENGINE_BASE_EXTRACT, ENGINE_LANG_EXTRACT)


def _collect_required_paths(node: dict, prefix: str = "") -> list[str]:
    """遍历默认结构，收集所有必须显式填写的叶子路径。

    规则（最严格）：
    - 字典节点递归下钻。
    - 叶子值为空字符串（如 ``reranker.model``）视为可选（由专项校验兜底）。
    - 其余叶子（数值 / 布尔 / 非空字符串）均为必填。
    """
    paths: list[str] = []
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            paths.extend(_collect_required_paths(value, path))
        elif value != "":
            paths.append(path)
    return paths


def _required_template(active_engine: str) -> dict:
    """构造校验用的"必填模板"：默认结构仅保留有效引擎分组。

    只校验当前启用引擎的参数，避免要求同时显式填写非活动引擎的配置。
    """
    import copy

    tpl = copy.deepcopy(DEFAULT_EXTRACTION_CONFIG)
    engines = tpl.get("llm", {}).get("engines", {})
    for name in list(engines.keys()):
        if name != active_engine:
            engines.pop(name, None)
    return tpl


def _lookup(raw: dict, path: str) -> Any:
    """按点分路径从原始配置取值，缺失返回 None。"""
    cur: Any = raw
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


async def validate_extraction_config(
    db: AsyncSession,
    kb_id: Any,
    *,
    check_rerank: bool = True,
) -> list[str]:
    """校验知识库抽取配置完整性，返回错误提示列表（空列表表示通过）。

    Args:
        db: 已激活 RLS 的会话（与任务提交同一会话）。
        kb_id: 知识库 ID。
        check_rerank: 是否执行重排模型加载校验（默认开启）。

    Returns:
        list[str]: 错误提示列表。
    """
    errors: list[str] = []
    raw: dict | None = None

    # 1) 全局配置：必须显式填写全部有效参数（仅校验当前启用引擎分组）
    row = (
        await db.execute(
            select(KbExtractionConfig).where(KbExtractionConfig.kb_id == kb_id)
        )
    ).scalar_one_or_none()
    if row is None or not row.enabled or not row.content:
        errors.append("抽取配置中心的全局配置未配置或未启用，请先在抽取配置中完成配置")
    else:
        raw = row.content
        active_engine = (raw.get("llm") or {}).get("engine") or ENGINE_BASE_EXTRACT
        required_paths = _collect_required_paths(_required_template(active_engine))
        missing = [
            p for p in required_paths if _lookup(raw, p) is None
        ]
        if missing:
            errors.append(
                "以下全局配置项未显式填写（不允许使用默认值兜底），请逐项配置："
                + "、".join(missing)
            )

    # 2) LLM 端点三元组（资源与配置 kb.config.extraction）
    try:
        from app.services.kb.kb_config_loader import kb_config_loader

        kb_cfg = await kb_config_loader.load(kb_id, db)
        llm_svc = (kb_cfg.config.get("services") or {}).get("llm_vllm") or {}
        if not llm_svc.get("api_base"):
            errors.append("未配置 LLM 服务端点 api_base（资源与配置 → LLM vLLM 服务）")
        if not llm_svc.get("model"):
            errors.append("未配置 LLM 服务模型 model_id（资源与配置 → LLM vLLM 服务）")
    except Exception as exc:  # noqa: BLE001
        logger.warning("加载 KB 配置用于校验端点失败", kb_id=str(kb_id), error=str(exc))
        errors.append(f"加载知识库配置失败，无法校验 LLM 端点：{exc}")

    # 3) Schema 模板：至少一个启用
    tpl_count = (
        await db.execute(
            select(SchemaTemplate).where(
                SchemaTemplate.kb_id == kb_id,
                SchemaTemplate.is_active.is_(True),
            )
        )
    ).scalars().all()
    if not tpl_count:
        errors.append("未配置任何启用的 Schema 模板，请先在 Schema 模板中创建模板与类别")

    # 4) Prompt 模板：必须已配置（不回退内置）
    cfg = await _config_resolver.resolve(db, kb_id)
    if not cfg.prompt_templates:
        errors.append("未配置 Prompt 模板，请配置（按要求不回退内置）")

    # 5) 引擎合法性
    engine = None
    if isinstance(raw, dict):
        engine = (raw.get("llm") or {}).get("engine")
    if engine and engine not in _VALID_ENGINES:
        errors.append(f"抽取引擎配置无效：{engine}（应为 {'/'.join(_VALID_ENGINES)}）")

    # 6) 重排模型可用性（开启时不静默降级）
    if check_rerank and cfg is not None:
        reranker_cfg = cfg.get("retrieval", "reranker") or {}
        if reranker_cfg.get("enabled"):
            model_path = (reranker_cfg.get("model") or "").strip()
            if not model_path:
                errors.append(
                    "已开启重排序，但未配置重排模型路径，请配置 retrieval.reranker.model"
                )
            elif retrieval_reranker._load(model_path) is None:
                errors.append(
                    "已开启重排序，但重排模型不可用（无法加载），请关闭重排序或配置正确的模型路径"
                )

    return errors


async def ensure_extraction_config_valid(db: AsyncSession, kb_id: Any) -> None:
    """校验知识库抽取配置，未通过时抛出 ``BusinessException``。

    Raises:
        BusinessException: 存在配置缺失或无效时抛出，携带全部错误提示。
    """
    errors = await validate_extraction_config(db, kb_id)
    if errors:
        message = "抽取配置未通过完整性校验，请先完成下列配置后再提交任务：\n- " + "\n- ".join(errors)
        raise BusinessException(message=message)