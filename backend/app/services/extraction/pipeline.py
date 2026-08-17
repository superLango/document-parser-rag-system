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
) -> dict:
    """执行抽取流水线。

    llm_client 用于测试注入；为 None 时从 KB 资源配置构建。
    """
    total_start = time.monotonic()
    session = db if db is not None else AsyncSessionLocal()
    try:
        cfg = await extraction_resolver.resolve(session, kb_id)
        await _progress(progress_cb, 10, "解析抽取配置")

        targets, skipped, _schemas = await category_builder.build(
            cfg, session, kb_id=kb_id, document_id=document_id,
        )
        await _progress(progress_cb, 30, "类别构建与召回完成")
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

        async def extract_one(target):
            async with sem:
                return await _extract_single(
                    session, cfg, target, client, engine, engine_params, retrieval_cfg,
                    context_cfg, script_timeout, str(document_id), term_data, llm_endpoint,
                )

        await _progress(progress_cb, 40, "开始类别抽取")
        results = await asyncio.gather(*[extract_one(t) for t in targets], return_exceptions=True)
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


async def _extract_single(session, cfg, target, client, engine, engine_params, retrieval_cfg, context_cfg, script_timeout, doc_id, term_data=None, llm_endpoint=None) -> CategoryResult:
    try:
        hits = target.hits or []
        # context_top_k：拼接上下文的最大块数（超出部分按相关性截断）
        ctx_top_k = target.top_k or int(retrieval_cfg.get("top_k") or 10)
        ctx_top_k = min(ctx_top_k, int(retrieval_cfg.get("context_top_k") or ctx_top_k))
        # 完整性优先：不按预算截断，全部命中块交由抽取引擎分批多次抽取
        context = context_assembler.assemble(
            hits,
            top_k=ctx_top_k,
            max_tokens=None,
            chars_per_token=float(context_cfg.get("chars_per_token") or 1.5),
            min_keep_chars=int(context_cfg.get("min_keep_chars") or 200),
            truncate_marker=context_cfg.get("truncate_marker") or "\n[...内容截断...]",
        )
        if not context:
            return CategoryResult(
                feature=target.feature, records=[], rejected=[],
                hit_score=target.hit_score, hit_count=target.hit_count,
            )
        logger.info("类别开始", feature=target.feature, context_chars=len(context), engine=engine)

        if engine == "LangExtractPkg":
            from app.services.extraction import lang_pkg_extractor

            records = await lang_pkg_extractor.extract_category_pkg(
                kb_id=cfg.kb_id, cfg=cfg, target=target, context=context,
                engine_params=engine_params, llm_endpoint=llm_endpoint or {},
            )
        else:
            records = await llm_extractor.extract_category(cfg, target, context, client, engine_params, engine=engine)
        logger.info("LLM 完成", feature=target.feature, records=len(records))
        # 规则组脚本：post 后处理 + validation 校验
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
