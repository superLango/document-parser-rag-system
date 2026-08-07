"""抽取配置解析器（ExtractionConfigResolver）。

将从数据库读取抽取配置中心的全量配置（全局配置 / Prompt 模板 / 规则 /
验证规则 / Schema 模板 / 术语绑定），并合并内置默认值，组装为
单一的 ``ExtractionDomainConfig`` 数据对象，供 v3 流水线各阶段消费。

配置分层（见方案 §5.3）：
- 全局层：kb_extraction_config（retrieval / llm / post_process）
- 模板层：kb_prompt_templates + kb_term_bindings
- Schema 层：schema_templates + schema_configs（类别/字段三层）

解析策略：仅读取用户显式配置（不做内置默认合并）；缺失配置项在运行时
访问时即报错（不允许硬编码回退），完整性由提交前 ``config_validator`` 全量校验。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.core.exceptions import BusinessException
from app.models.extraction_config import (
    KbDomainConfigVersion,
    KbExtractionConfig,
    KbPromptCategory,
    KbPromptTemplate,
    KbRule,
    KbTermBinding,
)
from app.models.schema_model import SchemaConfig, SchemaTemplate
from app.services.extraction_config.defaults import (
    ENGINE_BASE_EXTRACT,
    ENGINE_LANG_EXTRACT,
)

logger = get_logger(__name__)


@dataclass
class ExtractionDomainConfig:
    """抽取领域配置聚合对象（一次解析的结果）。"""

    kb_id: str
    # 全局配置（retrieval / llm / post_process）
    global_config: dict[str, Any] = field(default_factory=dict)
    # 全局配置是否启用（false 时回退内置默认）
    config_enabled: bool = True
    # Prompt 模板：{name: {content, variables, template_type}}
    prompt_templates: dict[str, dict] = field(default_factory=dict)
    # 规则（统一 kb_rules）：{rule_key: {stage, name, enabled, params, scope}}
    rules: dict[str, dict] = field(default_factory=dict)
    # 验证规则（兼容字段，已统一并入 rules，保留空）
    validation_rules: dict[str, dict] = field(default_factory=dict)
    # 术语绑定：{(schema_id, field_name): {term_base_id, config}}
    term_bindings: dict[tuple, dict] = field(default_factory=dict)
    # Schema 模板列表（含类别/字段）
    schema_templates: list[dict] = field(default_factory=list)
    # KB 专属抽取端点（资源与配置 kb.config.extraction）：{base_url, api_key, model}
    endpoint: dict = field(default_factory=dict)
    # Prompt 校验级别（资源与配置 kb.config.extraction）：off/warning/error
    prompt_validation_level: str | None = None

    # ------------------------------------------------------------------
    # 便捷访问
    # ------------------------------------------------------------------
    @property
    def retrieval(self) -> dict:
        return self.global_config.get("retrieval", {})

    @property
    def llm(self) -> dict:
        return self.global_config.get("llm", {})

    @property
    def post_process(self) -> dict:
        return self.global_config.get("post_process", {})

    def get(self, block: str, key: str, default: Any = None) -> Any:
        """按区块 + 键取全局配置值。"""
        return self.global_config.get(block, {}).get(key, default)

    # ------------------------------------------------------------------
    # 并发 / LLM 参数便捷访问（配置驱动，按引擎分组，调用方不再回退硬编码）
    # ------------------------------------------------------------------
    def engine_params(self, engine: str | None = None) -> dict:
        """返回指定或当前引擎分组的参数字典（未配置时返回空 dict）。"""
        name = engine or self.llm_engine()
        return (self.llm.get("engines") or {}).get(name) or {}

    def total_llm_concurrency(self) -> int:
        """LLM 调用总并发上限（当前引擎分组 concurrency.max_concurrency）。

        配置缺失即抛错（提交前已由 config_validator 全量校验，不允许硬编码回退）。
        """
        mc = (self.engine_params().get("concurrency") or {}).get("max_concurrency")
        if mc is None:
            raise BusinessException(f"未配置 LLM 总并发上限 llm.engines.{self.llm_engine()}.concurrency.max_concurrency")
        return int(mc)

    def category_concurrency(self, engine: str | None = None) -> int:
        """类别间调度并发（当前引擎分组 concurrency.cross_category）。

        - LangExtract：cross_category（类别内 each 用 within_category 并发）
        - BaseExtract：类别内串行，类别并发 = 总并发，以填满 vLLM 队列
        """
        name = engine or self.llm_engine()
        cross = (self.engine_params(name).get("concurrency") or {}).get("cross_category")
        if cross is None:
            raise BusinessException(f"未配置类别并发 llm.engines.{name}.concurrency.cross_category")
        if name == ENGINE_LANG_EXTRACT:
            return int(cross)
        # BaseExtract 线路类别内串行，类别并发 = 总并发
        return self.total_llm_concurrency()

    def within_category_concurrency(self) -> int:
        """类别内并发（LangExtract 的 max_workers）。缺失即抛错，不允许硬编码回退。"""
        wc = (self.engine_params().get("concurrency") or {}).get("within_category")
        if wc is None:
            raise BusinessException(f"未配置类别内并发 llm.engines.{self.llm_engine()}.concurrency.within_category")
        return int(wc)

    def llm_engine(self) -> str:
        """抽取引擎（BaseExtract / LangExtract）。缺失即抛错。"""
        e = self.llm.get("engine")
        if not e:
            raise BusinessException("未配置抽取引擎 llm.engine")
        return e

    def engine_temperature(self, engine: str | None = None) -> float | None:
        """引擎采样温度（仅返回当前引擎自有配置，不回退其他引擎）。

        配置缺失时返回 None，由配置完整性校验在提交前拦截报错。
        """
        params = self.engine_params(engine)
        temp = params.get("temperature")
        return float(temp) if temp is not None else None

    def max_output_tokens(self, engine: str | None = None) -> int | None:
        """引擎分组 max_tokens。配置缺失返回 None，由提交前校验拦截。"""
        v = self.engine_params(engine).get("max_tokens")
        return int(v) if v else None

    def llm_batch(self) -> dict:
        """BaseExtract 批处理参数（single_threshold / batch_chars / overlap / context_truncate）。"""
        return self.engine_params(ENGINE_BASE_EXTRACT).get("batch") or {}

    # ------------------------------------------------------------------
    # 检索子配置便捷访问
    # ------------------------------------------------------------------
    def phase2_retrieval(self) -> dict:
        """Phase 2 类别召回参数（top_k / per_dim_top_k）。"""
        return self.retrieval.get("phase2") or {}

    def query_embed(self) -> dict:
        """五维查询编码参数（query_embedder）。"""
        return self.retrieval.get("query_embed") or {}

    def context_chars_per_token(self) -> float:
        """上下文 token 估算系数。缺失即抛错，不允许硬编码回退。"""
        v = (self.retrieval.get("context") or {}).get("chars_per_token")
        if v is None:
            raise BusinessException("未配置 retrieval.context.chars_per_token")
        return float(v)

    def context_top_k(self) -> int | None:
        """抽取上下文按块数截断上限（None=不截断）。"""
        v = self.retrieval.get("context_top_k")
        return int(v) if v else None

    def context_min_keep_chars(self) -> int:
        """上下文截断最后一个块时的最小保留字符数。缺失即抛错。"""
        v = (self.retrieval.get("context") or {}).get("min_keep_chars")
        if v is None:
            raise BusinessException("未配置 retrieval.context.min_keep_chars")
        return int(v)

    def context_truncate_marker(self) -> str:
        """上下文截断时追加的标记文本。缺失即抛错。"""
        v = (self.retrieval.get("context") or {}).get("truncate_marker")
        if not v:
            raise BusinessException("未配置 retrieval.context.truncate_marker")
        return v

    def kb_tool(self) -> dict:
        """脚本工具性能参数（kb_tool 区块）。"""
        return self.global_config.get("kb_tool") or {}

    # ------------------------------------------------------------------
    # Prompt 模板便捷访问
    # ------------------------------------------------------------------
    def get_prompt(self, name: str) -> dict | None:
        """按名称取 Prompt 模板（未配置返回 None）。"""
        return self.prompt_templates.get(name)

    def prompt_for_category(
        self,
        template_id: str | None,
        category_id: str | None,
    ) -> tuple[str, str] | None:
        """按类别解析其绑定的 Prompt 模板（精确匹配，无回退）。

        与 Schema 一致：类别必须显式绑定 Prompt 模板，未绑定时返回 None，
        由调用方报错，**不做任何兜底/回退**（不回退到 simple 全局模板、不
        回退到内置模板）。只有绑定到该类别所属 Schema 模板且命中
        ``category_id`` 的类别级 user_prompt 才被采用。

        Returns:
            (system_prompt, user_prompt) 或 None（未绑定则 None）。
        """
        if not self.prompt_templates:
            return None

        # 仅精确匹配：类别所属模板 + 类别 id
        if template_id and category_id:
            for _name, tpl in self.prompt_templates.items():
                if tpl.get("schema_template_id") == template_id:
                    for c in tpl.get("categories", []):
                        if c.get("category_id") == category_id:
                            return (tpl.get("system_prompt") or "", c.get("user_prompt") or "")
        return None

    def category_template_id(self, category: dict) -> str | None:
        """返回类别节点所属的 Schema 模板 id（用于 Prompt 绑定解析）。"""
        template_id = category.get("template_id")
        if template_id:
            return str(template_id)
        # 未直接挂模板时，从所属模板容器兜底
        return None


class ExtractionConfigResolver:
    """抽取配置解析器。

    从数据库读取配置并组装为 ``ExtractionDomainConfig``。读取操作显式按
    ``kb_id`` 过滤（纵深防御，不依赖 RLS，因 superuser 会绕过 RLS）。
    """

    async def resolve(self, db: AsyncSession, kb_id) -> ExtractionDomainConfig:
        """解析 KB 的完整抽取配置。"""
        kb_id_str = str(kb_id)
        cfg = ExtractionDomainConfig(kb_id=kb_id_str)

        await self._load_global(db, kb_id, cfg)
        await self._load_prompts(db, kb_id, cfg)
        await self._load_rules(db, kb_id, cfg)
        await self._load_bindings(db, kb_id, cfg)
        await self._load_schemas(db, kb_id, cfg)

        return cfg

    # ------------------------------------------------------------------
    # 各子配置加载
    # ------------------------------------------------------------------
    async def _load_global(self, db: AsyncSession, kb_id, cfg: ExtractionDomainConfig) -> None:
        row = (
            await db.execute(
                select(KbExtractionConfig).where(KbExtractionConfig.kb_id == kb_id)
            )
        ).scalar_one_or_none()
        if row is None or not row.enabled or not row.content:
            # 未显式配置：global_config 置空，运行时访问缺失项即报错（不允许内置默认回退）
            cfg.global_config = {}
            cfg.config_enabled = row is not None and row.enabled
            return
        # 只读用户显式配置，不做默认值合并（缺失即报错，不允许硬编码回退）
        cfg.global_config = row.content
        cfg.config_enabled = True

    async def _load_prompts(self, db: AsyncSession, kb_id, cfg: ExtractionDomainConfig) -> None:
        rows = (
            await db.execute(
                select(KbPromptTemplate)
                .where(KbPromptTemplate.kb_id == kb_id, KbPromptTemplate.is_active.is_(True))
                .order_by(KbPromptTemplate.created_at)
            )
        ).scalars().all()
        for p in rows:
            cats = (
                await db.execute(
                    select(KbPromptCategory).where(
                        KbPromptCategory.prompt_template_id == p.id
                    )
                )
            ).scalars().all()
            cfg.prompt_templates[p.name] = {
                "id": str(p.id),
                "scope": p.scope,
                "system_prompt": p.system_prompt or "",
                "user_prompt": p.user_prompt or "",
                "schema_template_id": str(p.schema_template_id) if p.schema_template_id else None,
                "categories": [
                    {
                        "category_id": str(c.category_id) if c.category_id else None,
                        "user_prompt": c.user_prompt or "",
                    }
                    for c in cats
                ],
            }

    async def _load_rules(self, db: AsyncSession, kb_id, cfg: ExtractionDomainConfig) -> None:
        rows = (
            await db.execute(
                select(KbRule)
                .where(KbRule.kb_id == kb_id)
                .order_by(KbRule.stage, KbRule.sort_order, KbRule.rule_key)
            )
        ).scalars().all()
        for r in rows:
            scope = r.scope or {"type": "global"}
            # 复合键保留多作用域实例（同 rule_key 可绑不同 scope）
            key = f"{r.rule_key}|{scope.get('type', 'global')}:{scope.get('template_id') or scope.get('category_id') or scope.get('field_id') or 'all'}"
            cfg.rules[key] = {
                "id": str(r.id),
                "rule_key": r.rule_key,
                "stage": r.stage,
                "name": r.name,
                "description": r.description or "",
                "enabled": r.enabled,
                "params": r.params or {},
                "scope": scope,
            }

    async def _load_bindings(self, db: AsyncSession, kb_id, cfg: ExtractionDomainConfig) -> None:
        rows = (
            await db.execute(
                select(KbTermBinding).where(KbTermBinding.kb_id == kb_id)
            )
        ).scalars().all()
        for b in rows:
            key = (str(b.schema_id) if b.schema_id else None, b.field_name)
            cfg.term_bindings[key] = {
                "term_base_id": str(b.term_base_id) if b.term_base_id else None,
                "config": b.config or {},
            }

    async def _load_schemas(self, db: AsyncSession, kb_id, cfg: ExtractionDomainConfig) -> None:
        templates = (
            await db.execute(
                select(SchemaTemplate)
                .where(SchemaTemplate.kb_id == kb_id, SchemaTemplate.is_active.is_(True))
                .order_by(SchemaTemplate.created_at)
            )
        ).scalars().all()
        for tpl in templates:
            nodes = (
                await db.execute(
                    select(SchemaConfig)
                    .where(
                        SchemaConfig.kb_id == kb_id,
                        SchemaConfig.template_id == tpl.id,
                    )
                    .order_by(SchemaConfig.sort_order, SchemaConfig.created_at)
                )
            ).scalars().all()
            categories = []
            fields_by_parent: dict[str, list[dict]] = {}
            for n in nodes:
                if n.node_type == "field":
                    fields_by_parent.setdefault(str(n.parent_id), []).append(
                        _serialize_field(n)
                    )
                elif n.node_type == "category":
                    categories.append(_serialize_category(n, str(tpl.id)))
            # 把子字段挂到对应类别（供 schema 构建直接消费）
            for cat in categories:
                cat["fields"] = fields_by_parent.get(cat["id"], [])
            cfg.schema_templates.append(
                {
                    "id": str(tpl.id),
                    "name": tpl.name,
                    "description": tpl.description or "",
                    "categories": categories,
                    "fields": fields_by_parent,
                }
            )


def _serialize_category(n: SchemaConfig, template_id: str) -> dict:
    return {
        "id": str(n.id),
        "template_id": template_id,
        "name": n.name,
        "description": n.description or "",
        "return_type": n.return_type,
        "is_active": n.is_active,
        "extraction_strategy": n.extraction_strategy,
        "query_mode": n.query_mode,
        "fixed_query": n.fixed_query,
        "confidence_threshold": n.confidence_threshold,
        "top_k": n.top_k,
        "rerank_top_k": n.rerank_top_k,
        "max_tokens": n.max_tokens,
        "datasets": n.datasets or [],
        # 名称来源 / Query 术语集配置（供类别构建与字段绑定）
        "name_source": n.name_source,
        "name_term_base_id": str(n.name_term_base_id) if n.name_term_base_id else None,
        "name_term_field": n.name_term_field,
        "query_sources": n.query_sources or [],
        "fields": [],
    }


def _serialize_field(n: SchemaConfig) -> dict:
    defn = n.schema_definition if isinstance(n.schema_definition, dict) else {}
    sample = n.sample_fields if isinstance(n.sample_fields, dict) else {}
    return {
        "id": str(n.id),
        "name": n.name,
        "description": n.description or "",
        "type": defn.get("type", "string"),
        "required": defn.get("required", False),
        "example": sample.get("example"),
    }
