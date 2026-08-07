"""v3 结构化抽取主流水线（Phase 2-4 编排）。

串联三个阶段，完成从五维向量检索到 LLM 抽取的完整流程：

```
Phase 2 类别构建
    五维 query 批量编码 → 并发 hybrid_search →
    置信度过滤 → 构建 ExtractionTargets + 类别 schema
        ↓
Phase 3+4 类别列表（并发，extractor 双线路）
    并发 retrieve → extract_with_fallback → post_processor
        ↓
result_writer.save → {OCR_OUTPUT_DIR}/{task_id}/extract_result.json
```

并发模型：
- **LLM 总并发**：``llm_max_concurrency``（默认 24），全局 Semaphore
- **类别间并发**：``effective_category_concurrency``（LangExtract=8 / glmocr=24）
- **类别内并发**：LangExtract max_workers=3 / glmocr 串行
- 总 inflight = 类别间并发 × 类别内并发 ≤ vLLM max-num-seqs=32

使用示例::

    from app.services.extraction.extraction_pipeline import extraction_pipeline

    result = await extraction_pipeline.run(task_id="abc123", doc_id="abc123")
    # 结果已保存到 {OCR_OUTPUT_DIR}/{task_id}/extract_result.json
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.core.exceptions import BusinessException
from app.services.extraction.extraction_models import (
    CategoryResult,
    ExtractionResult,
    ExtractionTarget,
    SkippedFeature,
)
from app.services.extraction.category.category_builder import category_builder
from app.services.extraction.retrieval.retrieval_service import retrieval_service
from app.services.extraction.llm_extract.extractor_factory import extract_with_fallback
from app.services.extraction.prompts.config_prompt_renderer import config_prompt_renderer
from app.services.extraction.result_writer import result_writer
from app.services.extraction.rule_engine.script_manager import script_manager
from app.services.extraction_config.resolver import ExtractionConfigResolver

logger = get_logger(__name__)

# 配置解析器
_config_resolver = ExtractionConfigResolver()


class ExtractionPipeline:
    """v3 结构化抽取主流水线。

    编排 Phase 2（类别构建）→ Phase 3（向量检索）→ Phase 4（LLM 抽取 + 后处理），
    最终将结果保存到任务目录。

    所有阶段共享 ``llm_semaphore``（LLM 调用总并发信号量），类别抽取额外
    受 ``category_semaphore`` 控制类别间并发。
    """

    def __init__(self) -> None:
        pass

    async def run(
        self,
        task_id: str,
        doc_id: str,
        kb_id: str | None = None,
    ) -> ExtractionResult:
        """执行完整的 v3 抽取流程（Phase 2-4）。

        Args:
            task_id: 任务 ID（雪花 ID，同时作为结果保存目录名）。
            doc_id: 文档 ID（五维向量库中的 doc_id 过滤条件，通常 == task_id）。
            kb_id: 知识库 ID，用于向量 Collection 隔离。

        Returns:
            ExtractionResult: v3 抽取最终结果（同时已保存为 JSON 文件）。
        """
        total_start = time.time()
        logger.info(
            "v3 抽取流程开始",
            extra={"task_id": task_id, "doc_id": doc_id, "kb_id": kb_id},
        )

        # 解析 KB 抽取领域配置（Schema 模板 / Prompt 模板 / 全局配置 / 术语绑定）
        # 配置缺失即报错，不允许静默回退内置默认
        if not kb_id:
            raise BusinessException("缺少知识库上下文（kb_id），无法解析抽取配置")
        cfg_db = AsyncSessionLocal()
        try:
            cfg = await _config_resolver.resolve(cfg_db, kb_id)
        except Exception as err:
            logger.error(
                "解析抽取领域配置失败",
                extra={"kb_id": kb_id, "error": str(err), "exc_info": True},
            )
            raise BusinessException(f"解析抽取领域配置失败：{err}")

        # 加载 LLM vLLM 服务端点（资源与配置 LLM vLLM 服务），挂到 cfg.endpoint
        try:
            from app.services.kb.kb_config_loader import kb_config_loader

            kb_cfg = await kb_config_loader.load(kb_id, cfg_db)
            _llm_svc = (kb_cfg.config.get("services") or {}).get("llm_vllm") or {}
            if _llm_svc.get("api_base") or _llm_svc.get("model"):
                cfg.endpoint = {
                    "base_url": _llm_svc.get("api_base"),
                    "api_key": _llm_svc.get("api_key"),
                    "model": _llm_svc.get("model"),
                }
            # Prompt 校验级别（kb.config.extraction，由抽取配置提供）
            _ext_cfg = (kb_cfg.config.get("extraction") or {})
            if _ext_cfg.get("prompt_validation_level"):
                cfg.prompt_validation_level = _ext_cfg.get("prompt_validation_level")
        except Exception as err:
            logger.error(
                "加载 LLM vLLM 端点失败",
                extra={"kb_id": kb_id, "error": str(err), "exc_info": True},
            )
            raise BusinessException(f"加载 LLM vLLM 端点失败：{err}")

        # 全局 LLM 并发信号量（所有 Phase 4 LLM 调用共享，配置驱动）
        _total_concurrency = cfg.total_llm_concurrency()
        llm_semaphore = asyncio.Semaphore(_total_concurrency)

        # ------------------------------------------------------------------
        # Phase 2：类别构建（Schema 模板驱动）
        # ------------------------------------------------------------------
        phase2_start = time.time()
        try:
            targets, skipped, schemas = await category_builder.build(
                doc_id, kb_id=kb_id, cfg=cfg, db=cfg_db
            )
        finally:
            if cfg_db is not None:
                await cfg_db.close()
        phase2_elapsed = time.time() - phase2_start

        logger.info(
            "Phase 2 完成",
            extra={
                "task_id": task_id,
                "kept_features": len(targets),
                "skipped_features": len(skipped),
                "elapsed_sec": round(phase2_elapsed, 2),
            },
        )

        # ------------------------------------------------------------------
        # Phase 3+4：类别列表抽取（并发）
        # ------------------------------------------------------------------
        categories_start = time.time()
        category_schemas: dict[str, dict[str, Any]] = schemas.get("categories", {})
        categories = await self._extract_categories(
            doc_id, targets, category_schemas, llm_semaphore, kb_id=kb_id, cfg=cfg
        )
        categories_elapsed = time.time() - categories_start

        logger.info(
            "类别列表抽取完成",
            extra={
                "task_id": task_id,
                "category_count": len(categories),
                "total_records": sum(len(c.records) for c in categories),
                "elapsed_sec": round(categories_elapsed, 2),
            },
        )

        # ------------------------------------------------------------------
        # 汇总结果并保存
        # ------------------------------------------------------------------
        total_elapsed = time.time() - total_start

        # 剔除空类别（records=0 且 rejected=0），文档中无对应内容的类别不保留
        non_empty_categories = [
            c for c in categories
            if len(c.records) > 0 or len(c.rejected) > 0
        ]
        removed_count = len(categories) - len(non_empty_categories)
        if removed_count > 0:
            logger.info(
                "剔除空类别",
                extra={
                    "task_id": task_id,
                    "total_categories": len(categories),
                    "non_empty_categories": len(non_empty_categories),
                    "removed_empty": removed_count,
                },
            )

        result = ExtractionResult(
            categories=non_empty_categories,
            timing={
                "phase2_category_build": round(phase2_elapsed, 2),
                "categories_extraction": round(categories_elapsed, 2),
                "total": round(total_elapsed, 2),
            },
        )

        # 保存到任务目录
        result_path = await result_writer.save(task_id, result, skipped)

        logger.info(
            "v3 抽取流程完成",
            extra={
                "task_id": task_id,
                "result_path": str(result_path),
                "total_records": result.summary.get("total_records", 0),
                "total_rejected": result.summary.get("total_rejected", 0),
                "total_elapsed_sec": round(total_elapsed, 2),
            },
        )
        return result

    # ------------------------------------------------------------------
    # 类别列表抽取（第二部分，并发）
    # ------------------------------------------------------------------

    async def _extract_categories(
        self,
        doc_id: str,
        targets: list[ExtractionTarget],
        category_schemas: dict[str, dict[str, Any]],
        llm_semaphore: asyncio.Semaphore,
        kb_id: str | None = None,
        cfg: Any = None,
    ) -> list[CategoryResult]:
        """并发抽取所有类别的检测数据记录。

        类别间并发受 ``effective_category_concurrency`` 控制，
        每个 feature 独立执行 retrieve → extract → post_process 流程。

        Args:
            doc_id: 文档 ID。
            targets: 保留的 ExtractionTarget 列表。
            category_schemas: feature 名 → schema 定义。
            llm_semaphore: LLM 调用总并发信号量。
            kb_id: 知识库 ID。
            cfg: 抽取领域配置。

        Returns:
            list[CategoryResult]: 各类别抽取结果（含通过和剔除的记录）。
        """
        if not targets:
            return []

        # 类别间调度并发（配置驱动，引擎感知，缺失即报错，无 settings 兜底）
        if cfg is None:
            raise BusinessException("类别抽取缺少抽取配置（cfg）")
        _engine = cfg.llm_engine()
        _cat_concurrency = cfg.category_concurrency(_engine)
        category_semaphore = asyncio.Semaphore(_cat_concurrency)

        async def extract_one(target: ExtractionTarget) -> CategoryResult:
            """单个 feature 的完整抽取流程（含信号量控制）。"""
            async with category_semaphore:
                return await self._extract_single_category(
                    doc_id, target, category_schemas, llm_semaphore,
                    kb_id=kb_id, cfg=cfg,
                )

        # 并发执行所有 feature 的抽取
        results = await asyncio.gather(
            *[extract_one(t) for t in targets],
            return_exceptions=True,
        )

        # 过滤异常，保留成功的 CategoryResult
        categories: list[CategoryResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                feature_name = targets[i].feature if i < len(targets) else "unknown"
                # 配置/业务类错误（如缺失 Prompt 模板、参数缺失）必须上报，
                # 不作为空结果静默剔除（"有执行，没有就报错"）
                if isinstance(result, BusinessException):
                    raise result
                logger.error(
                    "类别抽取异常",
                    extra={"feature": feature_name, "error": str(result)},
                )
                # 运行时异常返回空结果，保证流程继续
                categories.append(CategoryResult(
                    feature=feature_name,
                    records=[],
                    rejected=[],
                    timing={"error": -1.0},
                ))
            elif isinstance(result, CategoryResult):
                categories.append(result)

        # 按记录数降序排列（记录多的类别在前）
        categories.sort(key=lambda c: len(c.records), reverse=True)
        return categories

    async def _extract_single_category(
        self,
        doc_id: str,
        target: ExtractionTarget,
        category_schemas: dict[str, dict[str, Any]],
        llm_semaphore: asyncio.Semaphore,
        kb_id: str | None = None,
        cfg: Any = None,
    ) -> CategoryResult:
        """单个 feature 的完整抽取流程（Phase 3 检索 → Phase 4 抽取 → 后处理）。

        Args:
            doc_id: 文档 ID。
            target: 该 feature 的抽取目标。
            category_schemas: 全部 feature 的 schema 字典。
            llm_semaphore: LLM 调用总并发信号量。
            kb_id: 知识库 ID。
            cfg: 抽取领域配置。

        Returns:
            CategoryResult: 该类别的抽取结果（含 timing）。
        """
        start = time.time()
        schema = category_schemas.get(target.feature, {})

        # Phase 3：向量检索
        retrieve_start = time.time()
        context = await retrieval_service.retrieve(target, doc_id, kb_id=kb_id, cfg=cfg)
        retrieve_elapsed = time.time() - retrieve_start

        if not context.text:
            logger.warning(
                "类别检索上下文为空，跳过抽取",
                extra={"feature": target.feature, "doc_id": doc_id},
            )
            return CategoryResult(
                feature=target.feature,
                records=[],
                rejected=[],
                timing={
                    "retrieval": round(retrieve_elapsed, 2),
                    "extraction": 0.0,
                    "post_processing": 0.0,
                    "total": round(time.time() - start, 2),
                },
            )

        # Phase 4：LLM 抽取（双线路 + 降级）
        extract_start = time.time()
        records = await extract_with_fallback(
            context=context,
            schema=schema,
            target=target,
            llm_semaphore=llm_semaphore,
            cfg=cfg,
        )
        extract_elapsed = time.time() - extract_start

        # 自定义脚本：抽取后处理 + 校验（脚本全权接管后处理，已移除内置管道）
        post_start = time.time()
        kept = [r.to_dict() for r in records]
        rejected: list[dict[str, Any]] = []
        if kb_id:
            _kb_tool = cfg.kb_tool() if cfg is not None else {}
            _script_timeout = _kb_tool.get("script_timeout")
            if _script_timeout is None:
                raise BusinessException("未配置脚本执行超时 kb_tool.script_timeout")
            async with AsyncSessionLocal() as rule_db:
                kept, script_rejected = await script_manager.apply_records(
                    rule_db, kb_id, "post", kept, target.feature, doc_id,
                    target=target, kb_tool=_kb_tool, timeout=_script_timeout,
                )
                rejected.extend(script_rejected)
                kept, script_rejected = await script_manager.apply_records(
                    rule_db, kb_id, "validation", kept, target.feature, doc_id,
                    target=target, kb_tool=_kb_tool, timeout=_script_timeout,
                )
                rejected.extend(script_rejected)
        post_elapsed = time.time() - post_start

        total_elapsed = time.time() - start
        logger.info(
            "单类别抽取完成",
            extra={
                "feature": target.feature,
                "retrieval_sec": round(retrieve_elapsed, 2),
                "extraction_sec": round(extract_elapsed, 2),
                "post_processing_sec": round(post_elapsed, 2),
                "total_sec": round(total_elapsed, 2),
                "kept": len(kept),
                "rejected": len(rejected),
            },
        )

        return CategoryResult(
            feature=target.feature,
            records=kept,
            rejected=rejected,
            timing={
                "retrieval": round(retrieve_elapsed, 2),
                "extraction": round(extract_elapsed, 2),
                "post_processing": round(post_elapsed, 2),
                "total": round(total_elapsed, 2),
            },
        )


# 模块级单例
extraction_pipeline = ExtractionPipeline()
