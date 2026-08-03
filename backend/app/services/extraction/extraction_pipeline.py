"""v3 结构化抽取主流水线（Phase 2-4 编排）。

串联三个阶段，完成从五维向量检索到 LLM 抽取的完整流程：

```
Phase 2 类别构建
    base_data 加载三表 → 五维 query 批量编码 → 并发 hybrid_search →
    置信度过滤 → 构建 ExtractionTargets + 三类 schema
        ↓
Phase 3+4 标准基本信息（单次，专用 prompt）
    retrieve_doc_info → render_doc_info_prompt → llm_client.chat_json
        ↓
Phase 3+4 类别列表（并发，extractor 双线路）
    并发 retrieve → extract_with_fallback → post_processor
        ↓
Phase 3+4 热处理制度（单次，专用 prompt）
    retrieve_heat_treatment → render_heat_treatment_prompt →
    llm_client.chat_json → post_processor（仅去重）
        ↓
result_writer.save → {OCR_OUTPUT_DIR}/{task_id}/extraction_v3.json
```

并发模型：
- **LLM 总并发**：``llm_max_concurrency``（默认 24），全局 Semaphore
- **类别间并发**：``effective_category_concurrency``（LangExtract=8 / glmocr=24）
- **类别内并发**：LangExtract max_workers=3 / glmocr 串行
- 总 inflight = 类别间并发 × 类别内并发 ≤ vLLM max-num-seqs=32

使用示例::

    from app.services.extraction.extraction_pipeline import extraction_pipeline

    result = await extraction_pipeline.run(task_id="abc123", doc_id="abc123")
    # 结果已保存到 {OCR_OUTPUT_DIR}/{task_id}/extraction_v3.json
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from app.core.logging import get_logger
from app.services.extraction.extraction_config import get_extraction_settings
from app.services.extraction.llm_client import llm_client
from app.services.extraction.extraction_models import (
    CategoryResult,
    ExtractionResult,
    ExtractionTarget,
    ExtractedRecord,
    HeatTreatmentResult,
    SkippedFeature,
)
from app.services.extraction.category.category_builder import category_builder
from app.services.extraction.retrieval.retrieval_service import retrieval_service
from app.services.extraction.llm_extract.extractor_factory import extract_with_fallback
from app.services.extraction.llm_extract.post_processor import post_processor
from app.services.extraction.prompts.prompt_manager import prompt_manager
from app.services.extraction.result_writer import result_writer

logger = get_logger(__name__)

# 标准基本信息抽取的 max_tokens（只需抽取名称和编号，输出很短）
_DOC_INFO_MAX_TOKENS = 2048


class ExtractionPipeline:
    """v3 结构化抽取主流水线。

    编排 Phase 2（类别构建）→ Phase 3（向量检索）→ Phase 4（LLM 抽取 + 后处理），
    最终将结果保存到任务目录。

    所有阶段共享 ``llm_semaphore``（LLM 调用总并发信号量），类别抽取额外
    受 ``category_semaphore`` 控制类别间并发。
    """

    def __init__(self) -> None:
        self._settings = get_extraction_settings()

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

        # 全局 LLM 并发信号量（所有 Phase 4 LLM 调用共享）
        llm_semaphore = asyncio.Semaphore(self._settings.llm_max_concurrency)

        # ------------------------------------------------------------------
        # Phase 2：类别构建
        # ------------------------------------------------------------------
        phase2_start = time.time()
        targets, skipped, schemas = await category_builder.build(doc_id, kb_id=kb_id)
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
        # Phase 3+4：标准基本信息抽取（单次，专用 prompt）
        # ------------------------------------------------------------------
        doc_info_start = time.time()
        doc_info = await self._extract_doc_info(doc_id, llm_semaphore, kb_id=kb_id)
        doc_info_elapsed = time.time() - doc_info_start

        logger.info(
            "标准基本信息抽取完成",
            extra={
                "task_id": task_id,
                "doc_info_keys": list(doc_info.keys()),
                "elapsed_sec": round(doc_info_elapsed, 2),
            },
        )

        # ------------------------------------------------------------------
        # Phase 3+4：类别列表抽取（并发）
        # ------------------------------------------------------------------
        categories_start = time.time()
        category_schemas: dict[str, dict[str, Any]] = schemas.get("categories", {})
        categories = await self._extract_categories(
            doc_id, targets, category_schemas, llm_semaphore, kb_id=kb_id
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
        # Phase 3+4：热处理制度抽取（单次，专用 prompt）
        # ------------------------------------------------------------------
        heat_start = time.time()
        heat_treatment = await self._extract_heat_treatment(
            doc_id, targets, llm_semaphore, kb_id=kb_id
        )
        heat_elapsed = time.time() - heat_start

        logger.info(
            "热处理制度抽取完成",
            extra={
                "task_id": task_id,
                "heat_records": len(heat_treatment.records),
                "elapsed_sec": round(heat_elapsed, 2),
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
            doc_info=doc_info,
            categories=non_empty_categories,
            heat_treatment=heat_treatment,
            timing={
                "phase2_category_build": round(phase2_elapsed, 2),
                "doc_info_extraction": round(doc_info_elapsed, 2),
                "categories_extraction": round(categories_elapsed, 2),
                "heat_treatment_extraction": round(heat_elapsed, 2),
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
    # 标准基本信息抽取（第一部分）
    # ------------------------------------------------------------------

    async def _extract_doc_info(
        self,
        doc_id: str,
        llm_semaphore: asyncio.Semaphore,
        kb_id: str | None = None,
    ) -> dict[str, Any]:
        """抽取标准基本信息（标准名称、标准编号）。

        使用专用 prompt 模板（phase4_doc_info.yaml），单次 LLM 调用，
        返回 object 类型（单条 dict）。

        Args:
            doc_id: 文档 ID。
            llm_semaphore: LLM 调用总并发信号量。
            kb_id: 知识库 ID。

        Returns:
            dict: 含 "标准名称" / "标准编号" 的字典。
        """
        try:
            # Phase 3：检索基础信息上下文
            context = await retrieval_service.retrieve_doc_info(doc_id, kb_id=kb_id)

            if not context.text:
                logger.warning("基础信息检索上下文为空", extra={"doc_id": doc_id})
                return {}

            # 构建专用 prompt
            system_prompt, user_prompt = prompt_manager.render_doc_info_prompt(
                context.text
            )

            # Phase 4：单次 LLM 调用
            async with llm_semaphore:
                data = await llm_client.chat_json(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    max_tokens=_DOC_INFO_MAX_TOKENS,
                    temperature=0.0,
                )

            # data 应为 dict（object 类型）
            if isinstance(data, dict):
                return data
            if isinstance(data, list) and data:
                # 兼容 LLM 返回数组的情况，取首项
                first = data[0]
                return first if isinstance(first, dict) else {}

            logger.warning("基础信息抽取结果格式异常", extra={"type": type(data).__name__})
            return {}

        except Exception as err:
            logger.error(
                "基础信息抽取失败",
                extra={"doc_id": doc_id, "error": str(err)},
            )
            return {}

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

        Returns:
            list[CategoryResult]: 各类别抽取结果（含通过和剔除的记录）。
        """
        if not targets:
            return []

        category_semaphore = asyncio.Semaphore(
            self._settings.effective_category_concurrency
        )

        async def extract_one(target: ExtractionTarget) -> CategoryResult:
            """单个 feature 的完整抽取流程（含信号量控制）。"""
            async with category_semaphore:
                return await self._extract_single_category(
                    doc_id, target, category_schemas, llm_semaphore, kb_id=kb_id
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
                logger.error(
                    "类别抽取异常",
                    extra={"feature": feature_name, "error": str(result)},
                )
                # 异常时返回空结果，保证流程继续
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
    ) -> CategoryResult:
        """单个 feature 的完整抽取流程（Phase 3 检索 → Phase 4 抽取 → 后处理）。

        Args:
            doc_id: 文档 ID。
            target: 该 feature 的抽取目标。
            category_schemas: 全部 feature 的 schema 字典。
            llm_semaphore: LLM 调用总并发信号量。
            kb_id: 知识库 ID。

        Returns:
            CategoryResult: 该类别的抽取结果（含 timing）。
        """
        start = time.time()
        schema = category_schemas.get(target.feature, {})

        # Phase 3：向量检索
        retrieve_start = time.time()
        context = await retrieval_service.retrieve(target, doc_id, kb_id=kb_id)
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
        )
        extract_elapsed = time.time() - extract_start

        # 后处理：归一化 + 年代号 + 跨类校验 + 去重
        post_start = time.time()
        kept, rejected = await post_processor.process(records, target)
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

    # ------------------------------------------------------------------
    # 热处理制度抽取（第三部分）
    # ------------------------------------------------------------------

    async def _extract_heat_treatment(
        self,
        doc_id: str,
        targets: list[ExtractionTarget],
        llm_semaphore: asyncio.Semaphore,
        kb_id: str | None = None,
    ) -> HeatTreatmentResult:
        """抽取热处理制度数据。

        使用专用 prompt 模板（phase4_heat_treatment.yaml），单次 LLM 调用，
        返回 array 类型（多条记录）。后处理仅做去重（无项目名归一化和跨类校验）。

        Args:
            doc_id: 文档 ID。
            targets: 保留的 ExtractionTarget 列表（用于构建 feature 列表）。
            llm_semaphore: LLM 调用总并发信号量。
            kb_id: 知识库 ID。

        Returns:
            HeatTreatmentResult: 热处理制度抽取结果。
        """
        start = time.time()
        feature_names = [t.feature for t in targets]

        try:
            # Phase 3：检索热处理制度上下文
            context = await retrieval_service.retrieve_heat_treatment(
                doc_id, feature_names, kb_id=kb_id
            )

            if not context.text:
                logger.warning(
                    "热处理制度检索上下文为空",
                    extra={"doc_id": doc_id},
                )
                return HeatTreatmentResult(
                    records=[],
                    timing={"total": round(time.time() - start, 2)},
                )

            # 构建专用 prompt
            features_list_str = "、".join(feature_names)
            system_prompt, user_prompt = prompt_manager.render_heat_treatment_prompt(
                context.text, features_list_str
            )

            # Phase 4：单次 LLM 调用
            async with llm_semaphore:
                data = await llm_client.chat_json(
                    prompt=user_prompt,
                    system_prompt=system_prompt,
                    max_tokens=self._settings.llm_max_output_tokens,
                    temperature=self._settings.llm_temperature,
                )

            # 解析记录（array 类型）
            records = self._parse_heat_treatment_records(data)

            # 后处理：仅去重（热处理制度无项目名，跨类校验会全部保留）
            heat_target = ExtractionTarget(feature="热处理制度")
            kept, _rejected = await post_processor.process(records, heat_target)

            total_elapsed = time.time() - start
            logger.info(
                "热处理制度抽取完成",
                extra={
                    "doc_id": doc_id,
                    "raw_records": len(records),
                    "kept_records": len(kept),
                    "elapsed_sec": round(total_elapsed, 2),
                },
            )

            return HeatTreatmentResult(
                records=kept,
                timing={
                    "retrieval_and_extraction": round(total_elapsed, 2),
                    "total": round(total_elapsed, 2),
                },
            )

        except Exception as err:
            logger.error(
                "热处理制度抽取失败",
                extra={"doc_id": doc_id, "error": str(err)},
            )
            return HeatTreatmentResult(
                records=[],
                timing={
                    "error": -1.0,
                    "total": round(time.time() - start, 2),
                },
            )

    @staticmethod
    def _parse_heat_treatment_records(data: Any) -> list[ExtractedRecord]:
        """将 LLM 输出解析为热处理制度记录列表。

        处理两种输出格式：
        - list[dict]：标准数组输出，每项为一条记录
        - dict：单条记录（兼容 LLM 返回 object 的情况）

        Args:
            data: LLM 输出的 JSON 数据。

        Returns:
            list[ExtractedRecord]: 热处理制度记录列表。
        """
        records: list[ExtractedRecord] = []

        if isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    records.append(ExtractedRecord(
                        feature="热处理制度",
                        data=dict(item),
                    ))
        elif isinstance(data, dict):
            records.append(ExtractedRecord(
                feature="热处理制度",
                data=dict(data),
            ))

        return records


# 模块级单例
extraction_pipeline = ExtractionPipeline()
