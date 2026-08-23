"""系统启动模型预热（异步）：进程内模型加载 + 外部 vLLM 服务连通性检测。

背景：抽取/文档解析流程中首次调用才加载模型，若此时显存不足或外部服务
未启动，会在流程中途报错（如 BGE-M3 CUDA OOM / GLM-OCR 不可达）。
本模块在后端启动时异步预热全部模型并记录状态，失败明确记录、不阻塞
API 启动；状态可通过 GET /api/v1/system/models/status 查看。
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from typing import Self

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class ModelWarmupService:
    """模型预热门面：单例；启动后台预热并缓存状态。"""

    _instance: ModelWarmupService | None = None

    def __new__(cls) -> Self:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        self.results: dict[str, dict] = {}
        self.running: bool = False
        self.started_at: float | None = None
        self.finished_at: float | None = None

    async def warmup_all(self) -> dict[str, dict]:
        """并发预热全部模型；任一项失败只记录，不抛异常（不阻塞启动）。"""
        if self.running:
            return self.results
        self.running = True
        self.started_at = time.time()
        logger.info("模型预热开始", items=["embedding", "reranker", "layout", "llm_qwen", "glm_ocr"])
        # 串行预热（仍异步、不阻塞 API 启动）：transformers 5.x 首次懒加载
        # 子模块存在并发竞态（embedding 线程与 reranker 主线程同时 import
        # 会偶发 ImportError），串行可彻底规避；外部服务检测放最后。
        items = [
            ("embedding", self._warmup_embedding()),
            ("reranker", self._warmup_reranker()),
            ("layout", self._warmup_layout()),
        ]
        # 容器化部署：OCR/LLM 由宿主机 vLLM 独立运行，跳过外部预热
        if not settings.MODEL_WARMUP_SKIP_EXTERNAL:
            items.extend([
                ("llm_qwen", self._warmup_llm_qwen()),
                ("glm_ocr", self._warmup_glm_ocr()),
            ])
        for name, coro in items:
            try:
                self.results[name] = await coro
            except BaseException as exc:  # noqa: BLE001 - 单项失败不阻塞其余预热
                self.results[name] = {
                    "status": "error",
                    "error": f"{type(exc).__name__}: {str(exc)[:280]}",
                }
        self.running = False
        self.finished_at = time.time()
        logger.info(
            "模型预热完成",
            results={k: v.get("status") for k, v in self.results.items()},
            elapsed=round((self.finished_at - self.started_at), 1),
        )
        return self.results

    def status(self) -> dict:
        """当前预热状态（供 /system/models/status 与启动日志使用）。"""
        return {
            "running": self.running,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "results": self.results,
        }

    # ---------------- 各项预热 ----------------

    async def _warmup_embedding(self) -> dict:
        """BGE-M3 嵌入模型：加载权重并跑一次小批量（覆盖显存不足提前暴露）。"""
        from app.services.embedding.embedding_service import embedding_service

        t0 = time.time()
        await embedding_service.warmup()
        return {
            "status": "ready",
            "model": settings.EMBEDDING_MODEL_DIR,
            "device": settings.EMBEDDING_DEVICE,
            "elapsed": round(time.time() - t0, 1),
        }

    async def _warmup_reranker(self) -> dict:
        """bge-reranker 交叉编码重排：加载权重并跑一次最小打分。"""
        from app.services.indexing.reranker import CrossEncoderReranker

        t0 = time.time()
        reranker = CrossEncoderReranker(settings.RERANKER_MODEL_DIR)
        dummy = SimpleNamespace(
            chunk_id="warmup",
            content="预热文本：抗拉强度 Rm 不小于 1275 MPa",
        )
        await reranker.rerank("预热查询：室温拉伸", [dummy], top_k=1)
        return {
            "status": "ready",
            "model": settings.RERANKER_MODEL_DIR,
            "elapsed": round(time.time() - t0, 1),
        }

    async def _warmup_layout(self) -> dict:
        """PP-DocLayoutV3 版面模型：加载权重与 processor（含权重完整性校验）。"""
        from app.services.parsekit.layout_ppdoc import PPDocLayoutEngine

        t0 = time.time()
        engine = PPDocLayoutEngine(
            settings.PARSEKIT_LAYOUT_MODEL_DIR,
            conf_threshold=settings.PARSEKIT_LAYOUT_CONF_THRESHOLD,
        )
        engine._load_model()
        return {
            "status": "ready",
            "model": settings.PARSEKIT_LAYOUT_MODEL_DIR,
            "device": engine.device,
            "elapsed": round(time.time() - t0, 1),
        }

    async def _warmup_llm_qwen(self) -> dict:
        """Qwen3.6 vLLM 服务：连通性 + 最小生成请求（验证真实可用）。"""
        import httpx

        t0 = time.time()
        base = settings.LLM_SERVER_URL.rstrip("/")
        async with httpx.AsyncClient(timeout=30) as client:
            r = await client.get(f"{base}/models")
            r.raise_for_status()
            body = {
                "model": settings.LLM_SERVER_MODEL,
                "messages": [{"role": "user", "content": "回复：ok"}],
                "max_tokens": 8,
                "temperature": 0.0,
            }
            r2 = await client.post(f"{base}/chat/completions", json=body)
            r2.raise_for_status()
        return {
            "status": "ready",
            "model": settings.LLM_SERVER_MODEL,
            "elapsed": round(time.time() - t0, 1),
        }

    async def _warmup_glm_ocr(self) -> dict:
        """GLM-OCR 服务：连通性检测（生成需图像输入，仅验证模型已就绪）。"""
        import httpx

        t0 = time.time()
        url = settings.GLMOCR_SERVER_URL
        base = url.rsplit("/chat/completions", 1)[0] or url
        async with httpx.AsyncClient(timeout=15) as client:
            r = await client.get(f"{base}/models")
            r.raise_for_status()
        return {
            "status": "ready",
            "model": settings.GLMOCR_MODEL,
            "elapsed": round(time.time() - t0, 1),
        }


model_warmup = ModelWarmupService()
