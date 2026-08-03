"""Popo 后处理编排主服务。

编排完整流程：归一化 → VLM 推理 → 文档树构建 → Markdown 渲染。

使用示例::

    from app.services.popo import popo_service

    result = popo_service.reconstruct("0HrsR68jRANoFpQREXPxiv")

输出 ``popo_reconstructed.md`` 到任务目录，与 ``reconstructed.md`` 对比。
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from app.core.config import settings
from app.services.popo.markdown_renderer import render as render_markdown
from app.services.popo.normalizer import GlmOcrNormalizer
from app.services.popo.popo_inference import PopoInference
from app.services.popo.tree_builder import build_tree, count_nodes

logger = logging.getLogger(__name__)


class PopoReconstructionService:
    """Popo OCR 后处理编排服务。"""

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
                task_dir = kb_dir / task_id
                if task_dir.exists():
                    return task_dir
                return base / task_id
            return base / task_id
        return base / task_id

    @staticmethod
    def reconstruct(task_id: str, save_intermediate: bool = True, kb_id: str | None = None) -> dict:
        """执行 Popo 后处理完整流程。

        Args:
            task_id: OCR 任务 ID（定位 merged.json 和 source.pdf）。
            save_intermediate: 是否保存推理中间产物。
            kb_id: 知识库 ID，用于路径定位。

        Returns:
            结果字典，包含输出路径和统计信息。

        Raises:
            FileNotFoundError: merged.json 或 source.pdf 不存在。
        """
        task_dir = PopoReconstructionService._get_task_dir(task_id, kb_id)
        merged_json = task_dir / "merged.json"
        pdf_path = task_dir / "source.pdf"

        if not merged_json.exists():
            raise FileNotFoundError(f"merged.json 不存在: {merged_json}")
        if not pdf_path.exists():
            raise FileNotFoundError(f"source.pdf 不存在: {pdf_path}")

        logger.info("Popo 后处理开始: task_id=%s", task_id)
        t_start = time.time()

        # 1. 归一化
        t0 = time.time()
        popo_input = GlmOcrNormalizer.normalize(merged_json, pdf_path)
        t_normalize = time.time() - t0
        total_pages = len(popo_input)
        total_blocks = sum(len(v) for v in popo_input.values())
        logger.info("归一化完成: %d 页, %d 块, %.1fs", total_pages, total_blocks, t_normalize)

        # 2. VLM 推理
        t1 = time.time()
        output_dir = task_dir / "popo_output" if save_intermediate else None
        doc_blocks = PopoInference.infer(str(pdf_path), popo_input, output_dir)
        t_infer = time.time() - t1
        logger.info("VLM 推理完成: %.1fs", t_infer)

        # 3. 构建文档树
        t2 = time.time()
        tree = build_tree(doc_blocks)
        t_build = time.time() - t2

        # 4. 统计 + 渲染 Markdown
        node_counts = count_nodes(tree)
        stats = {
            "总块数": total_blocks,
            "标题数": node_counts["titles"],
            "文本数": node_counts["texts"],
            "表格数": node_counts["tables"],
            "图片数": node_counts["images"],
            "题注数": node_counts["captions"],
            "跨页合并数": sum(1 for b in doc_blocks if b.get("contd", -1) > 0),
            "表格合并数": sum(1 for b in doc_blocks if b.get("table_merge", -1) >= 0),
            "归一化耗时(s)": f"{t_normalize:.2f}",
            "推理耗时(s)": f"{t_infer:.2f}",
            "树构建耗时(s)": f"{t_build:.2f}",
            "总耗时(s)": f"{time.time() - t_start:.2f}",
        }

        markdown = render_markdown(tree, stats)

        # 5. 输出
        out_path = task_dir / "popo_reconstructed.md"
        out_path.write_text(markdown, encoding="utf-8")

        logger.info(
            "Popo 后处理完成: %s, 总耗时 %.1fs",
            out_path, time.time() - t_start,
        )

        return {
            "task_id": task_id,
            "output_path": str(out_path),
            "stats": stats,
        }


# 模块级单例
popo_service = PopoReconstructionService()
