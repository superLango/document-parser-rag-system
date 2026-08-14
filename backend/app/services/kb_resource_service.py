"""KB 资源与配置服务（E2：LLM vLLM 服务）。"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BusinessException, ErrorCode
from app.models.knowledge_base import KnowledgeBase
from app.services.llm.llm_client import OpenAICompatibleClient, mask_api_key

SERVICE_KEY = "llm_vllm"


async def _get_kb(db: AsyncSession, kb_id) -> KnowledgeBase:
    kb = (
        await db.execute(
            select(KnowledgeBase).where(
                KnowledgeBase.id == kb_id, KnowledgeBase.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if kb is None:
        raise BusinessException(code=ErrorCode.BUSINESS_KB_NOT_FOUND, message="知识库不存在")
    return kb


def _read_config(kb: KnowledgeBase) -> dict:
    return (((kb.config or {}).get("services") or {}).get(SERVICE_KEY) or {})


def _to_view(raw: dict) -> dict:
    return {
        "enabled": bool(raw.get("enabled", False)),
        "api_base": raw.get("api_base", ""),
        "model": raw.get("model", ""),
        "api_key_masked": mask_api_key(raw.get("api_key", "")),
        "timeout": int(raw.get("timeout") or 300),
    }


async def get_llm_resource(db: AsyncSession, kb_id) -> dict:
    kb = await _get_kb(db, kb_id)
    return _to_view(_read_config(kb))


async def save_llm_resource(db: AsyncSession, kb_id, data: dict) -> dict:
    kb = await _get_kb(db, kb_id)
    config = dict(kb.config or {})
    services = dict(config.get("services") or {})
    old = dict(services.get(SERVICE_KEY) or {})
    new = {
        "enabled": bool(data.get("enabled", False)),
        "api_base": (data.get("api_base") or "").strip(),
        "model": (data.get("model") or "").strip(),
        # 未传新 key 时保留旧 key
        "api_key": (data.get("api_key") or "").strip() or old.get("api_key", ""),
        "timeout": int(data.get("timeout") or 300),
    }
    services[SERVICE_KEY] = new
    config["services"] = services
    kb.config = config
    await db.commit()
    await db.refresh(kb)
    return _to_view(new)


async def test_llm_resource(db: AsyncSession, kb_id, data: dict | None = None) -> dict:
    """连通性测试：优先用请求体配置，否则用已保存配置。"""
    kb = await _get_kb(db, kb_id)
    raw = data or _read_config(kb)
    api_base = (raw.get("api_base") or "").strip()
    model = (raw.get("model") or "").strip()
    if not api_base or not model:
        return {"ok": False, "error": "请先填写 LLM 服务地址与模型名称"}
    try:
        client = OpenAICompatibleClient(
            base_url=api_base,
            model=model,
            api_key=(raw.get("api_key") or "").strip(),
            timeout=int(raw.get("timeout") or 300),
        )
        await client.ping()
        return {"ok": True}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)}


async def get_llm_resource_raw(db: AsyncSession, kb_id) -> dict:
    """读取 LLM 资源原始配置（内部使用：适配器/诊断，含未脱敏 api_key）。"""
    kb = await _get_kb(db, kb_id)
    return dict(_read_config(kb))


async def build_llm_client(db: AsyncSession, kb_id) -> OpenAICompatibleClient:
    """构建已启用的 LLM 客户端（E3 抽取流水线使用）。"""
    kb = await _get_kb(db, kb_id)
    raw = _read_config(kb)
    if not raw.get("enabled"):
        raise BusinessException(message="LLM 服务未启用，请先在资源与配置中配置")
    if not (raw.get("api_base") or "").strip() or not (raw.get("model") or "").strip():
        raise BusinessException(message="LLM 服务地址或模型未配置")
    return OpenAICompatibleClient(
        base_url=raw["api_base"],
        model=raw["model"],
        api_key=raw.get("api_key", ""),
        timeout=int(raw.get("timeout") or 300),
    )
