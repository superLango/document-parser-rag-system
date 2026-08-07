"""层级感知重建 + 五维向量入库主服务（Popo 后处理版）。

编排完整流程：
Popo 后处理（归一化 → VLM 推理 → 文档树） → 适配转换 → 表格清洗 →
题注关联 → 父子块切分 → 五维向量化 → Markdown 输出。

使用示例::

    from app.services.vector import reconstruction_service

    # 仅 Markdown 重建（不建向量索引）
    result = await reconstruction_service.reconstruct_only_markdown("task_123")

    # 完整重建（含五维向量入库）
    result = await reconstruction_service.reconstruct("task_123", doc_id="doc_456")
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from app.core.config import settings
from app.services.popo import popo_service
from app.services.vector.chunker import hierarchy_chunker
from app.services.vector.caption_linker import table_caption_linker
from app.services.vector.five_dim_embedder import five_dim_embedder
from app.services.vector.markdown_builder import markdown_builder
from app.services.vector.vector_models import DocumentElement
from app.services.vector.popo_adapter import PopoAdapter
from app.services.vector.table_cleaner import table_cleaner
from app.services.vector.five_dim_vector_store import five_dim_vector_store

logger = logging.getLogger(__name__)


class ReconstructionService:
    """层级感知重建 + 五维向量入库主服务（Popo 版）。"""

    @staticmethod
    def _get_task_dir(task_id: str, kb_id: str | None = None) -> Path:
        """获取任务输出目录。

        KB隔离时路径为 {OCR_OUTPUT_DIR}/{kb_id}/{task_id}/，
        无KB时兼容旧路径 {OCR_OUTPUT_DIR}/{task_id}/。
        """
        base = Path(settings.OCR_OUTPUT_DIR)
        if kb_id:
            kb_dir = base / kb_id
            if kb_dir.exists():
                # KB目录存在，检查该KB下是否有task_id子目录
                task_dir = kb_dir / task_id
                if task_dir.exists():
                    return task_dir
                # 如果该KB下没有对应task，fallback到旧路径（兼容）
                return base / task_id
            # KB目录不存在，使用旧路径
            return base / task_id
        return base / task_id

    @staticmethod
    def _get_merged_json_path(task_id: str, kb_id: str | None = None) -> Path:
        """获取 merged.json 路径。"""
        return ReconstructionService._get_task_dir(task_id, kb_id) / "merged.json"

    @staticmethod
    def _clean_table_elements(elements: list[DocumentElement]) -> int:
        """清洗所有表格元素的 HTML 内容。

        Returns:
            清洗的表格数量。
        """
        count = 0
        for elem in elements:
            if elem.type == "table" and table_cleaner.is_table(elem.content):
                elem.content = table_cleaner.clean(elem.content)
                count += 1
        return count

    async def reconstruct(
        self,
        task_id: str,
        doc_id: str | None = None,
        build_vector_index: bool = True,
        kb_id: str | None = None,
    ) -> dict:
        """完整重建流程（Popo 后处理 + 五维向量入库）。

        Args:
            task_id: OCR 任务 ID（定位 merged.json）。
            doc_id: 文档 ID（向量库关联键），默认用 task_id。
            build_vector_index: 是否构建五维向量索引。
            kb_id: 知识库 ID，用于向量 Collection 隔离。

        Returns:
            重建结果字典，包含输出路径、各阶段耗时和统计信息。
        """
        doc_id = doc_id or task_id
        task_dir = self._get_task_dir(task_id, kb_id)
        merged_json_path = self._get_merged_json_path(task_id, kb_id)

        if not merged_json_path.exists():
            raise FileNotFoundError(
                f"merged.json 不存在: {merged_json_path}，请先完成 OCR"
            )

        logger.info("开始 Popo 后处理 + 五维向量重建", extra={"task_id": task_id, "doc_id": doc_id})
        t_total_start = time.time()

        # ── 阶段 1: Popo 后处理（归一化 → VLM 推理 → 文档树 → Markdown）──
        t0 = time.time()
        popo_result = popo_service.reconstruct(task_id, save_intermediate=True, kb_id=kb_id)
        t_popo = time.time() - t0
        logger.info("Popo 后处理完成: %.2fs", t_popo)

        # ── 阶段 2: 适配转换（Popo doc_blocks → DocumentElement）──
        t1 = time.time()
        import json
        popo_output_path = task_dir / "popo_output" / f"{Path(popo_result.get('pdf_stem', 'source')).stem}.json"
        # Popo 保存的文件名可能是 source.json 或 {pdf_stem}.json
        if not popo_output_path.exists():
            # 尝试 source.json
            popo_output_path = task_dir / "popo_output" / "source.json"
        if not popo_output_path.exists():
            # 从 popo_output 目录中找第一个 .json
            popo_output_dir = task_dir / "popo_output"
            json_files = list(popo_output_dir.glob("*.json")) if popo_output_dir.exists() else []
            if json_files:
                popo_output_path = json_files[0]

        if not popo_output_path.exists():
            raise FileNotFoundError(f"Popo 推理输出文件不存在: {popo_output_path}")

        with popo_output_path.open("r", encoding="utf-8") as f:
            doc_blocks = json.load(f)

        elements = PopoAdapter.adapt(doc_blocks)
        total_elements = len(elements)
        t_adapt = time.time() - t1
        logger.info("Popo 适配转换完成: %d 元素, %.2fs", total_elements, t_adapt)

        # ── 阶段 3: 表格清洗 ──
        t2 = time.time()
        cleaned_tables = self._clean_table_elements(elements)
        t_clean = time.time() - t2
        logger.info("表格清洗: %d 张, %.2fs", cleaned_tables, t_clean)

        # ── 阶段 4: 表格题注关联 ──
        t3 = time.time()
        caption_count = table_caption_linker.link(elements)
        t_caption = time.time() - t3
        logger.info("题注关联: %d 个, %.2fs", caption_count, t_caption)

        # ── 阶段 5: 父子块切分 ──
        t4 = time.time()
        parent_chunks, child_chunks = hierarchy_chunker.chunk(elements, doc_id)
        t_chunk = time.time() - t4
        logger.info("父子块切分: %d 父块, %d 子块, %.2fs", len(parent_chunks), len(child_chunks), t_chunk)

        # ── 阶段 6: 五维向量编码 + 入库（可选）──
        t5 = time.time()
        vector_count = 0
        t_vec_delete = t_vec_encode = t_vec_insert = 0.0
        if build_vector_index and child_chunks:
            # 6.1 先删除旧数据（如有）
            t5a = time.time()
            await five_dim_vector_store.delete_by_doc_id(doc_id, kb_id=kb_id)
            t_vec_delete = time.time() - t5a
            logger.info("  [6.1] 删除旧向量: %.2fs", t_vec_delete)

            # 6.2 编码五维向量（含模型加载/预热）
            t5b = time.time()
            await five_dim_embedder.encode_batch(child_chunks)
            t_vec_encode = time.time() - t5b
            logger.info("  [6.2] 五维向量编码: %.2fs", t_vec_encode)

            # 6.2.5 入库前显式确保 KB 的 BM25 模型存在（缺失则用本文档块语料生成）
            t5b5 = time.time()
            if kb_id is not None and child_chunks:
                from app.services.vector.bm25_sparse import ensure_kb_bm25
                corpus = [f"{c.content} {c.title}" for c in child_chunks]
                ensure_kb_bm25(kb_id, corpus)
            logger.info("  [6.2.5] 确保 KB BM25 模型: %.2fs", time.time() - t5b5)

            # 6.3 入库
            t5c = time.time()
            vector_count = await five_dim_vector_store.insert_chunks(child_chunks, doc_id, kb_id=kb_id)
            t_vec_insert = time.time() - t5c
            logger.info("  [6.3] Milvus 插入: %.2fs", t_vec_insert)
        t_vector = time.time() - t5
        logger.info(
            "五维向量入库: %d 条, %.2fs (删除 %.2fs + 编码 %.2fs + 插入 %.2fs)",
            vector_count, t_vector, t_vec_delete, t_vec_encode, t_vec_insert,
        )

        # ── 阶段 6.5: 保存 child_chunks.json（供 RAG 索引用）──
        import json as _json
        child_chunks_data = []
        for chunk in child_chunks:
            child_chunks_data.append({
                "id": chunk.id,
                "parent_id": chunk.parent_id,
                "hierarchy_path": chunk.hierarchy_path,
                "title": chunk.title,
                "content": chunk.content,
                "parent_text": chunk.parent_text,
                "chunk_index": chunk.chunk_index,
                "level": chunk.level,
                "has_table": chunk.has_table,
                "semantic_label": chunk.semantic_label,
                "source_pages": chunk.source_pages,
            })
        chunks_path = task_dir / "child_chunks.json"
        chunks_path.write_text(
            _json.dumps(child_chunks_data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        logger.info("child_chunks.json 已保存: %d 个子块", len(child_chunks_data))

        # ── 阶段 7: Markdown 输出 ──
        t6 = time.time()
        stats = {
            "总元素数": total_elements,
            "表格清洗数": cleaned_tables,
            "题注关联数": caption_count,
            "父块数": len(parent_chunks),
            "子块数": len(child_chunks),
            "向量入库数": vector_count,
        }
        markdown_content = markdown_builder.build(parent_chunks, child_chunks, stats)
        output_path = task_dir / "reconstructed.md"
        output_path.write_text(markdown_content, encoding="utf-8")
        t_md = time.time() - t6

        t_total = time.time() - t_total_start

        # 完整耗时统计
        timing = {
            "Popo后处理(s)": round(t_popo, 2),
            "适配转换(s)": round(t_adapt, 2),
            "表格清洗(s)": round(t_clean, 2),
            "题注关联(s)": round(t_caption, 2),
            "父子块切分(s)": round(t_chunk, 2),
            "五维向量入库(s)": round(t_vector, 2),
            "  - 删除旧向量(s)": round(t_vec_delete, 2),
            "  - 向量编码(s)": round(t_vec_encode, 2),
            "  - Milvus插入(s)": round(t_vec_insert, 2),
            "Markdown输出(s)": round(t_md, 2),
            "总耗时(s)": round(t_total, 2),
        }
        stats.update(timing)

        logger.info(
            "Popo + 五维向量重建完成: task=%s, 总耗时 %.2fs, 向量 %d 条",
            task_id, t_total, vector_count,
            extra={"timing": timing},
        )

        return {
            "task_id": task_id,
            "doc_id": doc_id,
            "output_path": str(output_path),
            "popo_output_path": str(popo_output_path),
            "stats": stats,
            "timing": timing,
        }

    async def reconstruct_only_markdown(self, task_id: str, kb_id: str | None = None) -> str:
        """快速模式：仅 Popo 后处理 + Markdown（不建向量索引）。

        Args:
            task_id: OCR 任务 ID。
            kb_id: 知识库 ID。

        Returns:
            reconstructed.md 文件路径。
        """
        result = await self.reconstruct(
            task_id, doc_id=task_id, build_vector_index=False, kb_id=kb_id
        )
        return result["output_path"]


# 模块级单例
reconstruction_service = ReconstructionService()
