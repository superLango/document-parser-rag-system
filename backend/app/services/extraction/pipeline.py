"""结构化抽取主流水线（E3）：类别构建 → 检索上下文 → Prompt → LLM → 脚本。"""

from __future__ import annotations

import asyncio
import time
import uuid

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.services import kb_resource_service
from app.services.extraction import (
    category_builder,
    category_builder_v2,
    context_assembler,
    extraction_resolver,
    llm_extractor,
    script_processor,
)
from app.services.extraction.extraction_models import CategoryResult, SkippedFeature

logger = get_logger(__name__)


async def run(
    *,
    kb_id,
    document_id,
    progress_cb=None,
    llm_client=None,
    db=None,
    schema_template_id=None,
) -> dict:
    """执行抽取流水线。

    llm_client 用于测试注入；为 None 时从 KB 资源配置构建。
    schema_template_id：仅抽取指定 Schema 模板（系统对接按 prompt 选择时使用）。
    """
    total_start = time.monotonic()
    session = db if db is not None else AsyncSessionLocal()
    try:
        cfg = await extraction_resolver.resolve(session, kb_id)
        if schema_template_id:
            cfg.schema_templates = [
                t for t in cfg.schema_templates
                if str(t.get("id")) == str(schema_template_id)
            ]
        await _progress(progress_cb, 10, "解析抽取配置")

        targets, skipped = await category_builder.build_targets(
            cfg, session, kb_id=kb_id,
        )
        await _progress(progress_cb, 20, "类别展开完成")
        # 并发前预载只读数据（共享会话禁止并发查询）：
        # KB 术语集 + 规则脚本代码
        from app.services.extraction import script_tools
        from app.services.extraction.script_processor import _script_code

        term_data = await script_tools.load_term_data(session, kb_id)
        script_ids = {
            str(r.get("script_id"))
            for g in cfg.rule_groups
            for cat in g.get("categories") or []
            for r in cat.get("rules") or []
            if r.get("script_id")
        }
        script_codes: dict[str, str] = {}
        for sid in sorted(script_ids):
            script_codes[sid] = await _script_code(session, kb_id, sid)
        # 预热嵌入模型并缓存（脚本超时窗口内不再做首次模型加载）
        await script_tools.warmup_embed()
        for g in cfg.rule_groups:
            for cat in g.get("categories") or []:
                for r in cat.get("rules") or []:
                    sid = str(r.get("script_id") or "")
                    if sid in script_codes:
                        r["code"] = script_codes[sid]

        if not targets:
            return _result(cfg, [], [], skipped, 0.0, total_start)

        client = llm_client or await kb_resource_service.build_llm_client(session, kb_id)
        engine = (cfg.global_config.get("llm") or {}).get("engine") or "BaseExtract"
        engine_params = ((cfg.global_config.get("llm") or {}).get("engines") or {}).get(engine) or {}
        llm_endpoint = None
        if engine == "LangExtractPkg":
            # 原包适配器需要 KB LLM 资源原始配置（api_base/model/api_key）
            llm_endpoint = await kb_resource_service.get_llm_resource_raw(session, kb_id)
        retrieval_cfg = cfg.global_config.get("retrieval") or {}
        context_cfg = retrieval_cfg.get("context") or {}
        kb_tool = cfg.global_config.get("kb_tool") or {}
        script_timeout = int(kb_tool.get("script_timeout") or 10)

        # 类别间并发（LangExtract 用 cross_category，BaseExtract 用总并发）
        concurrency = int(
            (engine_params.get("concurrency") or {}).get("cross_category")
            or (engine_params.get("concurrency") or {}).get("max_concurrency")
            or 4
        )
        sem = asyncio.Semaphore(concurrency)
        # 全局 LLM 请求并发（段级并行共享）：匹配 vLLM max_num_seqs，避免超发排队
        llm_sem = asyncio.Semaphore(
            int((engine_params.get("concurrency") or {}).get("max_concurrency") or 8)
        )

        async def extract_one(target):
            async with sem:
                # 上下文组装用与检索一致的配置(V3 时 k40; V1 时全局)
                _rcfg = v3_retrieval_cfg if retrieval_route == "v3" else retrieval_cfg
                _ccfg = v3_context_cfg if retrieval_route == "v3" else context_cfg
                return await _extract_single(
                    session, cfg, target, client, engine, engine_params, _rcfg,
                    _ccfg, script_timeout, str(document_id), term_data, llm_endpoint,
                    llm_sem=llm_sem,
                )

        # 流式：逐个类别完成检索/重排后立即进入抽取，不等全部类别检索完
        # 检索路线开关: retrieval.route=v3 时走 V3(文档感知术语+语义证据+候选放大+阈值-5),
        # 否则走 V1(现状)。V1/V3 并存, 可配置切换。
        # V3 并行优化(2026-08-29): 类别检索 asyncio.gather + Semaphore 并发;
        # GPU 推理(embed/rerank)仍由 embedding 单线程锁与 reranker 类级缓存序列化,
        # 并发主要重叠 DB ANN/BM25 IO 与语义证据缓存。并发度由 global_config.retrieval.route_concurrency 控制(默认 8)。
        retrieval_route = (retrieval_cfg.get("route") or "v3")  # 2026-08-29: 默认 V3(证据判定+完整候选/无重排), 仅显式 v1 回退旧链路
        route_conc = int((retrieval_cfg.get("route_concurrency") or 8))
        # V3 配置(检索 + 上下文组装统一): 全局 retrieval 叠加 LARGE_CANDIDATES(k40)
        # 保证「检索 60 块」能完整送 LLM(修正 ctx_top_k 被全局 15 截断的问题)
        v3_retrieval_cfg = retrieval_cfg
        v3_context_cfg = context_cfg
        extract_tasks: list[asyncio.Task] = []
        if retrieval_route == "v3":
            rr = (retrieval_cfg.get("reranker") or {})
            v3_override = {**category_builder_v2.LARGE_CANDIDATES}
            v3_override["reranker"] = {**rr, "threshold": -5.0,
                                       "semantic_evidence_enabled": True}
            # 组装上下文也读取 k40 的 top_k/context_top_k(含 context.sort_mode)
            v3_retrieval_cfg = {**retrieval_cfg, **category_builder_v2.LARGE_CANDIDATES}
            v3_context_cfg = {
                **context_cfg,
                **((category_builder_v2.LARGE_CANDIDATES.get("context") or {})),
            }
            _sem = asyncio.Semaphore(route_conc)

            async def _build_v3(t):
                async with _sem:
                    return await category_builder_v2.build_one_v2(
                        cfg, session, kb_id=kb_id, document_id=document_id, target=t,
                        retrieval_override=v3_override,
                    )

            built_list = await asyncio.gather(
                *(_build_v3(t) for t in targets), return_exceptions=True,
            )
            built_targets: list[tuple] = []
            for t, r in zip(targets, built_list):
                if isinstance(r, Exception):
                    logger.error("类别检索异常(V3)", feature=t.feature, error=str(r))
                    continue
                built, sk = r
                if built is None:
                    if sk is not None:
                        skipped.append(sk)
                    continue
                built_targets.append(built)
        else:
            built_targets = []
            for t in targets:
                built, sk = await category_builder.build_one(
                    cfg, session, kb_id=kb_id, document_id=document_id, target=t,
                )
                if built is None:
                    if sk is not None:
                        skipped.append(sk)
                    continue
                built_targets.append(built)
        for built in built_targets:
            logger.info("类别检索完成，进入抽取", feature=built.feature, hit_count=built.hit_count)
            extract_tasks.append(asyncio.create_task(extract_one(built)))
        await _progress(progress_cb, 40, "开始类别抽取")
        results = await asyncio.gather(*extract_tasks, return_exceptions=True)
        # 任一类别异常（含 LLM 不可用）→ 任务整体失败（B11：不静默吞错）
        for i, r in enumerate(results):
            if not isinstance(r, CategoryResult):
                logger.error("类别抽取异常", feature=targets[i].feature, error=str(r))
                raise r if isinstance(r, Exception) else RuntimeError(f"类别抽取异常：{r}")
        categories = [r for r in results if isinstance(r, CategoryResult)]
        await _progress(progress_cb, 90, "抽取完成，保存结果")

        non_empty = [c for c in categories if c.records or c.rejected]
        return _result(cfg, non_empty, categories, skipped, 0.0, total_start)
    finally:
        if db is None:
            await session.close()


async def _extract_single(session, cfg, target, client, engine, engine_params, retrieval_cfg, context_cfg, script_timeout, doc_id, term_data=None, llm_endpoint=None, llm_sem=None) -> CategoryResult:
    try:
        hits = target.hits or []
        # 块级过滤（第二部分）：非 always 类别按块重排分数阈值过滤低分块。
        # always 类别（标准信息/热处理制度）保留全部上下文（需要全文档信息）。
        if (target.extraction_strategy or "auto") != "always":
            reranker_cfg = retrieval_cfg.get("reranker") or {}
            if reranker_cfg.get("block_filter_enabled", True):
                rerank_threshold = float(reranker_cfg.get("threshold") or 0.0)
                hits = [
                    h for h in hits
                    if h.get("rerank_score") is None or h.get("rerank_score") >= rerank_threshold
                ]
        # context_top_k：拼接上下文的最大块数（超出部分按相关性截断）
        ctx_top_k = target.top_k or int(retrieval_cfg.get("top_k") or 10)
        ctx_top_k = min(ctx_top_k, int(retrieval_cfg.get("context_top_k") or ctx_top_k))
        # 上下文排序（全局配置 retrieval.context）：
        #   sort_mode：page=页码排序（主流程，正常文档阅读顺序）/ rerank=重排分数降序
        #   retry_rerank_on_empty：主排序抽取为 0 条时，自动用重排排序再抽一次
        context_cfg = context_cfg or {}
        sort_mode = str(context_cfg.get("sort_mode") or "page")
        primary_mode = sort_mode if sort_mode in ("page", "rerank") else "page"
        retry_rerank = bool(context_cfg.get("retry_rerank_on_empty", True))

        def _make_context(mode: str) -> str:
            if mode == "rerank":
                return context_assembler.assemble_full_sorted(hits, top_k=ctx_top_k)
            return context_assembler.assemble_page_order(hits, top_k=ctx_top_k)

        async def _run_engine(ctx: str) -> list[dict]:
            segments = [{"type": "text", "content": ctx}]
            if engine == "LangExtractPkg":
                from app.services.extraction import lang_pkg_extractor

                return await lang_pkg_extractor.extract_category_pkg(
                    kb_id=cfg.kb_id, cfg=cfg, target=target, context=ctx, segments=segments,
                    engine_params=engine_params, llm_endpoint=llm_endpoint or {}, llm_sem=llm_sem,
                )
            return await llm_extractor.extract_category(cfg, target, ctx, client, engine_params, engine=engine)

        context = _make_context(primary_mode)
        # 主排序上下文为空时，若允许重试则直接切重排
        if not context.strip() and retry_rerank and primary_mode != "rerank":
            primary_mode = "rerank"
            context = _make_context(primary_mode)
        if not context.strip():
            return CategoryResult(
                feature=target.feature, records=[], rejected=[],
                hit_score=target.hit_score, hit_count=target.hit_count,
            )
        # 上下文规模预估（chars_per_token / context_max_tokens 接线）：
        # 只做预估与告警，不截断——整段拼入 Prompt 一次给模型。
        chars_per_token = float(context_cfg.get("chars_per_token") or 1.5)
        est_tokens = int(len(context) / max(0.1, chars_per_token))
        ctx_token_limit = int(retrieval_cfg.get("context_max_tokens") or 0)
        if ctx_token_limit > 0 and est_tokens > ctx_token_limit:
            logger.warning(
                "上下文预估 token 超限（整段仍发送）",
                feature=target.feature, est_tokens=est_tokens, limit=ctx_token_limit,
                context_chars=len(context),
            )
        logger.info(
            "类别开始", feature=target.feature,
            context_chars=len(context), est_tokens=est_tokens,
            sort_mode=primary_mode, engine=engine,
        )
        records = await _run_engine(context)
        retried = False
        retry_info = None
        if not records and retry_rerank and primary_mode != "rerank":
            context2 = _make_context("rerank")
            if context2.strip():
                logger.info("类别 0 条，切换重排排序重试", feature=target.feature, context_chars=len(context2))
                records2 = await _run_engine(context2)
                retried = True
                retry_info = {
                    "mode": "rerank",
                    "records": len(records2),
                    "context_chars": len(context2),
                }
                if records2:
                    records = records2
        logger.info("LLM 完成", feature=target.feature, records=len(records), retried=retried)
        # 规则组脚本：post 后处理 + validation 校验（仅对最终采用的一轮结果执行一次）
        rules = _rules_for_category(cfg, target.category_id)
        kept, rejected = records, []
        if rules:
            kept, rejected = await script_processor.apply_scripts(
                session, uuid.UUID(str(cfg.kb_id)),
                category_feature=target.feature, records=records, doc_id=doc_id,
                rules=rules, script_timeout=script_timeout, term_data=term_data,
            )
        missing = llm_extractor.missing_required_fields(kept, target.schema)
        logger.info("类别完成", feature=target.feature, kept=len(kept), rejected=len(rejected))
        return CategoryResult(
            feature=target.feature, records=kept, rejected=rejected,
            missing_fields=missing, hit_score=target.hit_score, hit_count=target.hit_count,
            retried=retried, retry=retry_info,
        )
    except Exception as exc:
        logger.error("类别抽取异常", feature=target.feature, error=str(exc))
        raise


def _rules_for_category(cfg, category_id: str) -> list[dict]:
    """从规则组详情中取该类别全部规则（post/validation 合并按组顺序）。"""
    rules: list[dict] = []
    for g in cfg.rule_groups:
        for cat in g.get("categories") or []:
            if cat.get("id") == category_id:
                rules.extend(cat.get("rules") or [])
    return rules


def _result(cfg, categories, all_categories, skipped, elapsed, total_start) -> dict:
    skipped_items = [
        {"feature": s.feature, "reason": s.reason, "score": s.score}
        for s in skipped if isinstance(s, SkippedFeature)
    ]
    # 第二版：命中分数分布（调参与阈值决策依据）
    scores = [c.hit_score for c in all_categories if c.hit_score is not None]
    bands = {
        "0-0.3": sum(1 for x in scores if x < 0.3),
        "0.3-0.5": sum(1 for x in scores if 0.3 <= x < 0.5),
        "0.5-0.7": sum(1 for x in scores if 0.5 <= x < 0.7),
        "0.7-0.9": sum(1 for x in scores if 0.7 <= x < 0.9),
        "0.9-1.0": sum(1 for x in scores if x >= 0.9),
    }
    recall_mode = ((cfg.global_config.get("retrieval") or {}).get("category_recall") or {}).get("mode") or "loose"
    summary = {
        "total_records": sum(len(c.records) for c in categories),
        "kept_categories": len(categories),
        "categories_attempted": len(all_categories),
        "skipped": skipped_items,
        "recall": {
            "mode": recall_mode,
            "participated": len(all_categories) + len(skipped_items),
            "kept": len(all_categories),
            "skipped_count": len(skipped_items),
            "score_bands": bands,
        },
    }
    timing = {"total_sec": round(time.monotonic() - total_start, 2)}
    tpl = cfg.schema_templates[0] if cfg.schema_templates else None
    return {
        "schema_template_id": tpl.get("id") if tpl else None,
        "schema_name": tpl.get("name") if tpl else "",
        "categories": [c.to_dict() for c in categories],
        "summary": summary,
        "timing": timing,
    }


async def _progress(progress_cb, progress: int, message: str) -> None:
    if progress_cb is not None:
        try:
            await progress_cb(progress, message)
        except Exception:  # noqa: BLE001
            logger.warning("进度回调失败", progress=progress, message=message)
