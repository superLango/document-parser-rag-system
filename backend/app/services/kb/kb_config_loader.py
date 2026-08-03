"""知识库配置加载器（方案 §7 配置中心 / §A.6 三层覆盖）。

实现「全局 settings → KB config JSON → Hook 脚本」三层配置覆盖：

1. **全局默认**（``DEFAULT_KB_CONFIG``）：从 ``app.core.config.settings`` 派生，
   与现有硬编码配置项对齐，保证默认 KB 行为等价
2. **KB 覆盖**（``KnowledgeBase.config`` JSON）：用户在配置中心调整的参数
3. **领域配置表**（``kb_categories`` / ``kb_field_templates`` / ``kb_regex_rules``
   / ``kb_dict_configs``）：替代 ``extraction_schemas.py`` 等硬编码

合并产物为 ``KBConfig`` 对象，供抽取流程、RAG、OCR 等服务按 KB 配置执行。

向后兼容（方案 §A.6）：
- 现有硬编码（extraction_schemas/field_template/正则/阈值）导入默认 KB 领域配置表
- ``extraction_schemas.py`` 保留兜底，本加载器优先读 KB 配置，缺失时回退
"""

import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.models.kb_domain_config import (
    KbCategory,
    KbCategoryEnum,
    KbDictConfig,
    KbFieldTemplate,
    KbRegexRule,
)
from app.models.knowledge_base import KnowledgeBase

logger = get_logger(__name__)


# ============================================================
# 全局默认 KB 配置（从 settings 派生，保证默认 KB 行为等价）
# ============================================================
def _build_default_config() -> dict[str, Any]:
    """构建全局默认 KB 配置。

    从 ``settings`` 读取现有硬编码配置项，作为每个 KB 的初始默认值。
    KB 的 ``config`` JSON 可覆盖这些值。
    """
    return {
        # OCR 配置
        "ocr": {
            "enable_popo": True,  # 是否启用 Popo 后处理
            "image_dpi": 200,
            "max_pages": 0,  # 0=不限制
        },
        # 向量索引配置
        "vector": {
            "embedding_model": settings.EMBEDDING_MODEL_PATH,
            "embedding_batch_size": settings.EMBEDDING_BATCH_SIZE,
            "reranker_model": settings.RERANKER_MODEL_DIR,
            "top_k": settings.RAG_TOP_K,
            "rerank_pool": settings.RAG_RERANK_POOL,
            "max_context_length": settings.RAG_MAX_CONTEXT_LENGTH,
        },
        # 结构化抽取配置（对齐 settings.EXTRACTION_*）
        "extraction": {
            "provider": settings.EXTRACTION_PROVIDER,
            "api_base": settings.EXTRACTION_API_BASE,
            "api_key": settings.EXTRACTION_API_KEY,
            "model_id": settings.EXTRACTION_MODEL_ID,
            "max_concurrency": settings.EXTRACTION_MAX_CONCURRENCY,
            "max_output_tokens": settings.EXTRACTION_MAX_OUTPUT_TOKENS,
            "temperature": settings.EXTRACTION_TEMPERATURE,
            "output_schema_mode": settings.EXTRACTION_OUTPUT_SCHEMA_MODE,
            "passes": settings.EXTRACTION_PASSES,
            "context_window_chars": settings.EXTRACTION_CONTEXT_WINDOW_CHARS,
            "max_char_buffer": settings.EXTRACTION_MAX_CHAR_BUFFER,
            "langextract_max_workers": settings.EXTRACTION_LANGEXTRACT_MAX_WORKERS,
            "prompt_validation_level": settings.EXTRACTION_PROMPT_VALIDATION_LEVEL,
            "prompt_static_prefix_enabled": settings.EXTRACTION_PROMPT_STATIC_PREFIX_ENABLED,
            "recall_classify_filter_enabled": settings.EXTRACTION_RECALL_CLASSIFY_FILTER_ENABLED,
            "recall_classify_threshold": settings.EXTRACTION_RECALL_CLASSIFY_THRESHOLD,
            "recall_min_chunks": settings.EXTRACTION_RECALL_MIN_CHUNKS,
        },
        # 问答配置
        "qa": {
            "llm_api_base": settings.LLM_API_BASE,
            "llm_model": settings.LLM_API_MODEL,
            "light_model": settings.LLM_LIGHT_MODEL,
            "enable_cache": True,
        },
        # 字典配置（默认值，KB 专属 kb_dict_configs 表覆盖）
        "dict": {
            "enabled": True,
            "match_threshold": 0.6,
            "whitelist_top_k": 20,
            "validation_top_k": 1,
            "validation_similarity_threshold": 0.6,
        },
    }


# 全局默认配置单例（启动时构建一次）
DEFAULT_KB_CONFIG: dict[str, Any] = _build_default_config()


# ============================================================
# KBConfig 数据对象
# ============================================================
@dataclass
class KBConfig:
    """知识库完整配置对象。

    由 ``KBConfigLoader.load`` 合并全局默认 + KB config JSON + 领域配置表后产出，
    供各服务按 KB 配置执行。

    Attributes:
        kb_id: 知识库 ID。
        config: 合并后的扁平配置字典（含 ocr/vector/extraction/qa/dict 各节）。
        categories: 抽取类别列表（从 kb_categories 表加载）。
        field_templates: 字段模板（doc_info / category_data）。
        regex_rules: 候选项目正则规则。
        dict_config: 基础字典同步与校验配置。
    """

    kb_id: uuid.UUID
    config: dict[str, Any] = field(default_factory=dict)
    categories: list[dict] = field(default_factory=list)
    field_templates: dict[str, list] = field(default_factory=dict)
    regex_rules: list[dict] = field(default_factory=list)
    dict_config: dict[str, Any] = field(default_factory=dict)

    # ---- 便捷访问器 ----
    @property
    def ocr(self) -> dict[str, Any]:
        return self.config.get("ocr", {})

    @property
    def vector(self) -> dict[str, Any]:
        return self.config.get("vector", {})

    @property
    def extraction(self) -> dict[str, Any]:
        return self.config.get("extraction", {})

    @property
    def qa(self) -> dict[str, Any]:
        return self.config.get("qa", {})

    @property
    def dict_section(self) -> dict[str, Any]:
        return self.config.get("dict", {})

    def get(self, *keys: str, default: Any = None) -> Any:
        """按层级路径取配置值，如 ``cfg.get("extraction", "passes")``。"""
        node: Any = self.config
        for k in keys:
            if not isinstance(node, dict):
                return default
            node = node.get(k, default)
        return node


# ============================================================
# 配置加载器
# ============================================================
class KBConfigLoader:
    """知识库配置加载器。

    合并全局默认配置 + KB ``config`` JSON + 领域配置表，产出 ``KBConfig``。
    缓存策略由调用方决定（本加载器不缓存，每次重新加载以保证最新）。
    """

    async def load(
        self,
        kb_id: uuid.UUID,
        db: AsyncSession,
        kb: KnowledgeBase | None = None,
    ) -> KBConfig:
        """加载知识库完整配置。

        Args:
            kb_id: 知识库 ID。
            db: 异步数据库会话（RLS 已由 KBContext 激活，查询自动按 kb_id 过滤）。
            kb: 可选的 KnowledgeBase ORM 对象，避免重复查询。

        Returns:
            KBConfig: 合并后的完整配置对象。
        """
        # 1. 取 KB ORM 对象
        if kb is None:
            stmt = select(KnowledgeBase).where(KnowledgeBase.id == kb_id)
            result = await db.execute(stmt)
            kb = result.scalar_one_or_none()
        if kb is None:
            logger.warning("配置加载：知识库不存在，返回默认配置", kb_id=str(kb_id))
            return KBConfig(kb_id=kb_id, config=_deep_copy(DEFAULT_KB_CONFIG))

        # 2. 深拷贝全局默认 + 覆盖 KB config JSON
        merged = _deep_copy(DEFAULT_KB_CONFIG)
        kb_config = kb.config if isinstance(kb.config, dict) else {}
        _deep_merge(merged, kb_config)

        # 3. 加载领域配置表（显式按 kb_id 过滤，纵深防御：不依赖 RLS，
        #    因 PostgreSQL superuser 绕过 RLS，即使 FORCE 也无效）
        categories = await self._load_categories(db, kb_id)
        field_templates = await self._load_field_templates(db, kb_id)
        regex_rules = await self._load_regex_rules(db, kb_id)
        dict_config = await self._load_dict_config(db, kb_id)

        # 字典配置表覆盖默认 dict 节
        if dict_config:
            _deep_merge(merged["dict"], dict_config)

        logger.debug(
            "KB 配置已加载",
            kb_id=str(kb_id),
            categories=len(categories),
            regex_rules=len(regex_rules),
        )

        return KBConfig(
            kb_id=kb_id,
            config=merged,
            categories=categories,
            field_templates=field_templates,
            regex_rules=regex_rules,
            dict_config=dict_config,
        )

    # ---- 领域配置表加载 ----
    async def _load_categories(self, db: AsyncSession, kb_id: uuid.UUID) -> list[dict]:
        """加载抽取类别定义（含 enum 约束）。显式按 kb_id 过滤。"""
        stmt = (
            select(KbCategory, KbCategoryEnum)
            .outerjoin(
                KbCategoryEnum, KbCategoryEnum.category_id == KbCategory.id
            )
            .where(
                KbCategory.kb_id == kb_id,
                KbCategory.is_active.is_(True),
            )
            .order_by(KbCategory.sort_order, KbCategory.name)
        )
        result = await db.execute(stmt)
        # 聚合 category -> enums
        cat_map: dict[uuid.UUID, dict] = {}
        for cat, enum in result.all():
            if cat.id not in cat_map:
                cat_map[cat.id] = {
                    "id": str(cat.id),
                    "name": cat.name,
                    "extraction_class": cat.extraction_class,
                    "description": cat.description,
                    "sort_order": cat.sort_order,
                    "recall_filter_threshold": cat.recall_filter_threshold,
                    "enums": {},
                }
            if enum is not None:
                cat_map[cat.id]["enums"][enum.field_name] = enum.enum_values
        return list(cat_map.values())

    async def _load_field_templates(self, db: AsyncSession, kb_id: uuid.UUID) -> dict[str, list]:
        """加载字段模板（doc_info / category_data）。显式按 kb_id 过滤。"""
        stmt = select(KbFieldTemplate).where(KbFieldTemplate.kb_id == kb_id)
        result = await db.execute(stmt)
        templates: dict[str, list] = {}
        for ft in result.scalars():
            templates[ft.template_type] = ft.fields if isinstance(ft.fields, list) else []
        return templates

    async def _load_regex_rules(self, db: AsyncSession, kb_id: uuid.UUID) -> list[dict]:
        """加载候选项目正则规则。显式按 kb_id 过滤。"""
        stmt = (
            select(KbRegexRule)
            .where(
                KbRegexRule.kb_id == kb_id,
                KbRegexRule.enabled.is_(True),
            )
            .order_by(KbRegexRule.sort_order)
        )
        result = await db.execute(stmt)
        return [
            {
                "id": str(r.id),
                "name": r.name,
                "pattern": r.pattern,
                "description": r.description,
            }
            for r in result.scalars()
        ]

    async def _load_dict_config(self, db: AsyncSession, kb_id: uuid.UUID) -> dict[str, Any]:
        """加载基础字典同步与校验配置。显式按 kb_id 过滤。"""
        stmt = select(KbDictConfig).where(KbDictConfig.kb_id == kb_id)
        result = await db.execute(stmt)
        dc = result.scalar_one_or_none()
        if dc is None:
            return {}
        return {
            "enabled": dc.enabled,
            "sync_url": dc.sync_url,
            "sync_cron": dc.sync_cron,
            "match_threshold": dc.match_threshold,
            "whitelist_top_k": dc.whitelist_top_k,
            "validation_top_k": dc.validation_top_k,
            "validation_similarity_threshold": dc.validation_similarity_threshold,
            "tables_mapping": dc.tables_mapping if isinstance(dc.tables_mapping, dict) else {},
        }


# ============================================================
# 工具函数
# ============================================================
def _deep_copy(d: dict) -> dict:
    """深拷贝字典（配置合并前必备，避免污染全局默认）。"""
    import copy

    return copy.deepcopy(d)


def _deep_merge(base: dict, override: dict) -> dict:
    """递归合并：override 覆盖 base 同名键，子字典递归合并。

    Args:
        base: 基础字典（会被原地修改）。
        override: 覆盖字典。

    Returns:
        dict: 合并后的 base 字典。
    """
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v
    return base


# 全局单例
kb_config_loader = KBConfigLoader()
