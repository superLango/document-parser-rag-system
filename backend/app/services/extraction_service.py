"""结构化信息抽取服务模块。

本模块基于 Google LangExtract 库从非结构化文本中抽取结构化字段信息，主要能力包括：
- 模式驱动抽取：依据 schema_definition 描述的字段清单构造 few-shot 示例与提示
- 用户自定义示例：将 schema.sample_fields 作为 LangExtract 的抽取依据，提升抽取准确性
- 字段缺失校验：对照 schema 检查必填字段是否齐全
- 批量抽取：对多段文本批量执行抽取
- 流式抽取：将长文本切分为多个 chunk，逐块抽取并推送进度，避免长时间等待

schema_definition 格式约定：
    {
        "fields": [
            {
                "name": "材料名称",
                "type": "string",
                "description": "材料的标准名称",
                "required": true
            },
            ...
        ]
    }

sample_fields 格式约定：
    {
        "材料名称": "Q235 钢",
        "规格型号": "GB/T 700-2006"
    }
    或多示例：
    {
        "材料名称": ["Q235 钢", "Q345 钢"]
    }

使用示例：
    from app.services.extraction_service import extraction_service

    schema = {
        "fields": [
            {"name": "材料名称", "type": "string", "description": "材料的标准名称"},
            {"name": "规格型号", "type": "string", "description": "规格与型号"},
        ]
    }
    sample_fields = {"材料名称": "Q235 钢", "规格型号": "GB/T 700-2006"}
    data = await extraction_service.extract("某型号钢材规格为...", schema, sample_fields)
"""

import asyncio
import re
from collections.abc import AsyncGenerator

import langextract
from langextract.data import FormatType, ExampleData, Extraction
from langextract.factory import ModelConfig

from app.core.config import settings
from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger

logger = get_logger(__name__)


class ExtractionService:
    """结构化信息抽取服务。

    基于 Google LangExtract 执行文本到结构化字段的抽取。通过 schema_definition
    描述待抽取字段的名称、类型与含义，并可使用 sample_fields 作为自定义 few-shot
    示例引导模型抽取。模型加载由 LangExtract 在抽取时按需处理。

    Attributes:
        _config: LangExtract 模型配置实例。
    """

    def __init__(
        self,
        model_id: str = "qwen3.5:9b",
        model_url: str = "http://localhost:11434",
    ) -> None:
        """初始化抽取服务。

        Args:
            model_id: Ollama 中已加载的模型标识，默认 "qwen3.5:9b"。
            model_url: Ollama 服务地址，默认 "http://localhost:11434"。
        """
        self._config = ModelConfig(
            model_id=model_id,
            provider="ollama",
            provider_kwargs={"model_url": model_url},
        )

    # ---------------------------------------------------------------
    # 示例构造
    # ---------------------------------------------------------------
    def _build_examples(
        self,
        schema_definition: dict,
        sample_fields: dict | None = None,
    ) -> list[ExampleData]:
        """根据 schema 字段与可选的 sample_fields 构造 few-shot 示例。

        示例构造策略：
        1. 若 sample_fields 中包含真实抽取示例，则优先使用这些示例作为 ExampleData。
           支持单值（str）和多值（list[str]）两种形式，多值时生成多个 ExampleData。
        2. 若 sample_fields 不可用或字段不全，则按字段类型生成默认示例值作为兜底。

        Args:
            schema_definition: 字段定义字典，需包含 "fields" 列表。
            sample_fields: 可选，用户配置的字段抽取示例。

        Returns:
            list[ExampleData]: few-shot 示例列表。
        """
        fields = schema_definition.get("fields", [])
        if not fields:
            return []

        # 处理 sample_fields：将单值统一转换为列表形式，便于多示例生成
        normalized_samples: dict[str, list[str]] = {}
        if sample_fields:
            for k, v in sample_fields.items():
                if v is None:
                    continue
                if isinstance(v, list):
                    normalized_samples[k] = [str(item) for item in v if item]
                else:
                    normalized_samples[k] = [str(v)]

        # 计算最大示例数（取所有字段示例列表的最大长度）
        max_examples = max(
            (len(v) for v in normalized_samples.values()),
            default=1,
        )

        examples: list[ExampleData] = []
        for example_idx in range(max_examples):
            # 为每个示例索引构造一组完整的字段值
            sample_values: dict[str, str] = {}
            text_segments: list[str] = []

            for field in fields:
                name = field.get("name", "")
                if not name:
                    continue
                ftype = field.get("type", "string")

                # 优先使用 sample_fields 中的值
                samples_for_field = normalized_samples.get(name, [])
                if samples_for_field and example_idx < len(samples_for_field):
                    value = samples_for_field[example_idx]
                else:
                    # 兜底：按字段类型生成默认示例值
                    value = self._sample_value_for_type(name, ftype)

                sample_values[name] = value
                # 拼装示例文本：字段名 + 值，让模型理解上下文
                text_segments.append(f"{name}为{value}")

            sample_text = "本示例文本中，" + "，".join(text_segments) + "。"

            extractions = [
                Extraction(
                    extraction_class=name,
                    extraction_text=value,
                )
                for name, value in sample_values.items()
            ]

            examples.append(
                ExampleData(
                    text=sample_text,
                    extractions=extractions,
                )
            )

        return examples

    @staticmethod
    def _sample_value_for_type(name: str, ftype: str) -> str:
        """根据字段类型生成示例值。

        Args:
            name: 字段名，用于生成更贴合语义的示例值。
            ftype: 字段类型（string / number / boolean 等）。

        Returns:
            str: 示例值字符串。
        """
        if ftype == "number":
            return "100"
        if ftype == "boolean":
            return "是"
        # 默认 string 及其他类型
        return f"示例{name}"

    def _build_prompt_description(
        self,
        schema_definition: dict,
        sample_fields: dict | None = None,
    ) -> str:
        """构建中文提示描述，说明抽取目标字段。

        Args:
            schema_definition: 字段定义字典，需包含 "fields" 列表。
            sample_fields: 可选，用户配置的字段抽取示例，用于在描述中追加示例提示。

        Returns:
            str: 拼接完成的中文提示描述。
        """
        fields = schema_definition.get("fields", [])
        field_lines: list[str] = []
        for field in fields:
            name = field.get("name", "")
            desc = field.get("description", "")
            required = field.get("required", False)
            req_label = "必填" if required else "选填"
            field_lines.append(f"- {name}（{req_label}）：{desc}")
        fields_text = "\n".join(field_lines) if field_lines else "（无字段定义）"

        # 追加示例说明（若 sample_fields 可用）
        samples_hint = ""
        if sample_fields:
            samples_hint = (
                "\n\n抽取示例（请参考以下示例的字段名与值的对应关系）：\n"
                + self._format_samples_for_prompt(sample_fields)
            )

        return (
            "从给定文本中抽取以下结构化字段信息：\n"
            f"{fields_text}\n"
            "仅抽取文本中明确出现的内容，不要编造文本中不存在的信息。"
            f"{samples_hint}"
        )

    @staticmethod
    def _format_samples_for_prompt(sample_fields: dict) -> str:
        """将 sample_fields 格式化为提示描述中的可读文本。

        Args:
            sample_fields: 字段示例字典。

        Returns:
            str: 格式化后的示例文本。
        """
        lines: list[str] = []
        for k, v in sample_fields.items():
            if isinstance(v, list):
                v_str = " / ".join(str(item) for item in v)
            else:
                v_str = str(v)
            lines.append(f"  {k}: {v_str}")
        return "\n".join(lines)

    # ---------------------------------------------------------------
    # 校验
    # ---------------------------------------------------------------
    def _validate_extraction(
        self,
        data: dict,
        schema_definition: dict,
    ) -> list[str]:
        """校验抽取结果是否满足 schema 中的必填字段要求。

        Args:
            data: 抽取得到的字典数据。
            schema_definition: 字段定义字典。

        Returns:
            list[str]: 缺失的必填字段名列表，若全部齐全则返回空列表。
        """
        fields = schema_definition.get("fields", [])
        missing: list[str] = []
        for field in fields:
            if not field.get("required", False):
                continue
            name = field.get("name", "")
            if name not in data or data[name] is None or data[name] == "":
                missing.append(name)
        return missing

    # ---------------------------------------------------------------
    # 文本分块
    # ---------------------------------------------------------------
    @staticmethod
    def _split_text_into_chunks(
        text: str,
        chunk_size: int = 4000,
        overlap: int = 200,
    ) -> list[str]:
        """将长文本切分为多个 chunk，相邻 chunk 之间保留一定重叠。

        切分策略：
        1. 优先按段落（双换行）切分，避免破坏语义完整性
        2. 段落超过 chunk_size 时按句子切分
        3. 不足 chunk_size 的相邻段落合并

        Args:
            text: 原始长文本。
            chunk_size: 每个 chunk 的目标字符数，默认 4000。
            overlap: 相邻 chunk 之间的重叠字符数，默认 200。

        Returns:
            list[str]: 切分后的 chunk 列表。
        """
        if not text or not text.strip():
            return []
        if len(text) <= chunk_size:
            return [text.strip()]

        # 按段落切分
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if not paragraphs:
            return [text.strip()]

        chunks: list[str] = []
        current: list[str] = []
        current_size = 0

        for para in paragraphs:
            # 单个段落过长时按句子进一步切分
            if len(para) > chunk_size:
                # 先保存当前累积的内容
                if current:
                    chunks.append("\n\n".join(current))
                    current = []
                    current_size = 0

                # 按句子切分长段落
                sentences = re.split(r"(?<=[。！？.!?])\s*", para)
                sent_buf: list[str] = []
                sent_size = 0
                for sent in sentences:
                    if sent_size + len(sent) > chunk_size and sent_buf:
                        chunks.append("".join(sent_buf))
                        # 保留 overlap
                        overlap_text = "".join(sent_buf)[-overlap:] if overlap > 0 else ""
                        sent_buf = [overlap_text] if overlap_text else []
                        sent_size = len(overlap_text)
                    sent_buf.append(sent)
                    sent_size += len(sent)
                if sent_buf:
                    chunks.append("".join(sent_buf))
                continue

            # 普通段落：累积直到接近 chunk_size
            if current_size + len(para) + 2 > chunk_size and current:
                chunks.append("\n\n".join(current))
                # 保留 overlap
                if overlap > 0:
                    overlap_text = "\n\n".join(current)[-overlap:]
                    current = [overlap_text] if overlap_text else []
                    current_size = len(overlap_text)
                else:
                    current = []
                    current_size = 0
            current.append(para)
            current_size += len(para) + 2  # +2 for "\n\n"

        if current:
            chunks.append("\n\n".join(current))

        return chunks

    # ---------------------------------------------------------------
    # 同步抽取核心
    # ---------------------------------------------------------------
    def _extract_sync(
        self,
        text: str,
        schema_definition: dict,
        sample_fields: dict | None = None,
    ) -> dict:
        """同步执行 LangExtract 抽取（线程池中调用）。

        Args:
            text: 待抽取文本。
            schema_definition: 字段定义字典。
            sample_fields: 可选，字段示例。

        Returns:
            dict: 抽取结果。
        """
        examples = self._build_examples(schema_definition, sample_fields)
        prompt_description = self._build_prompt_description(schema_definition, sample_fields)

        result = langextract.extract(
            text,
            prompt_description=prompt_description,
            examples=examples,
            config=self._config,
            format_type=FormatType.JSON,
            show_progress=False,
        )

        extractions = getattr(result, "extractions", None) or []
        data: dict = {}
        for ext in extractions:
            data[ext.extraction_class] = ext.extraction_text

        return data

    # ---------------------------------------------------------------
    # 异步抽取入口
    # ---------------------------------------------------------------
    async def extract(
        self,
        text: str,
        schema_definition: dict,
        sample_fields: dict | None = None,
    ) -> dict:
        """从单段文本中抽取结构化信息。

        流程：
        1. 校验 schema_definition 格式与文本非空
        2. 构造 few-shot 示例（优先使用 sample_fields）与提示描述
        3. 通过 asyncio.to_thread 调用同步的 langextract.extract
        4. 校验必填字段是否齐全（缺失时记录警告但不阻断）
        5. 返回抽取结果字典

        Args:
            text: 待抽取的非结构化文本。
            schema_definition: 字段定义字典，需包含 "fields" 列表。
            sample_fields: 可选，字段抽取示例，作为 LangExtract 的抽取依据。

        Returns:
            dict: 抽取得到的结构化数据，键为字段名，值为抽取内容或 None。

        Raises:
            BusinessException: schema 格式错误或抽取失败时抛出。
        """
        if not isinstance(schema_definition, dict):
            raise BusinessException(
                code=ErrorCode.VALIDATION_ERROR,
                message="schema_definition 必须为字典类型",
            )
        if "fields" not in schema_definition or not isinstance(
            schema_definition["fields"], list
        ):
            raise BusinessException(
                code=ErrorCode.VALIDATION_ERROR,
                message="schema_definition 必须包含 fields 列表",
            )
        if not text or not text.strip():
            raise BusinessException(
                code=ErrorCode.VALIDATION_ERROR,
                message="待抽取文本不能为空",
            )

        logger.info(
            "开始结构化抽取",
            text_len=len(text),
            field_count=len(schema_definition.get("fields", [])),
            has_samples=bool(sample_fields),
        )

        try:
            data = await asyncio.to_thread(
                self._extract_sync,
                text,
                schema_definition,
                sample_fields,
            )
        except BusinessException:
            raise
        except Exception as err:
            logger.error("结构化抽取失败", error=str(err), exc_info=True)
            raise BusinessException(
                code=ErrorCode.BUSINESS_TASK_FAILED,
                message=f"结构化抽取失败：{err}",
                details={"error": str(err)},
            ) from err

        missing = self._validate_extraction(data, schema_definition)
        if missing:
            logger.warning(
                "抽取结果缺失部分必填字段",
                missing_fields=missing,
                extracted_keys=list(data.keys()),
            )

        logger.info(
            "结构化抽取完成",
            extracted_field_count=len(data),
            missing_required=missing,
        )
        return data

    async def extract_batch(
        self,
        texts: list[str],
        schema_definition: dict,
        sample_fields: dict | None = None,
    ) -> list[dict]:
        """批量抽取多段文本的结构化信息。

        Args:
            texts: 待抽取的文本列表。
            schema_definition: 字段定义字典。
            sample_fields: 可选，字段示例。

        Returns:
            list[dict]: 抽取结果列表，顺序与输入 texts 一一对应。
        """
        if not texts:
            return []

        logger.info("开始批量抽取", batch_size=len(texts))

        async def _safe_extract(text: str) -> dict:
            try:
                return await self.extract(text, schema_definition, sample_fields)
            except BusinessException as err:
                logger.warning(
                    "批量抽取中单段失败，返回空字典",
                    message=err.message,
                    text_preview=text[:100],
                )
                return {}
            except Exception as err:
                logger.error(
                    "批量抽取中单段发生未预期异常",
                    error=str(err),
                    exc_info=True,
                )
                return {}

        results = await asyncio.gather(*[_safe_extract(t) for t in texts])
        success_count = sum(1 for r in results if r)
        logger.info(
            "批量抽取完成",
            total=len(texts),
            success=success_count,
            failed=len(texts) - success_count,
        )
        return list(results)

    # ---------------------------------------------------------------
    # 流式抽取（分块 + 进度推送）
    # ---------------------------------------------------------------
    async def extract_stream(
        self,
        text: str,
        schema_definition: dict,
        sample_fields: dict | None = None,
        chunk_size: int = 4000,
        overlap: int = 200,
    ) -> AsyncGenerator[dict, None]:
        """流式抽取：将长文本切分为多个 chunk，逐块抽取并推送进度。

        通过分块抽取避免长时间等待，每块抽取完成后通过 yield 推送
        增量结果与进度信息，调用方（如 SSE 端点）将其转发给前端。

        事件类型：
        - {"type": "progress", "progress": 0-100, "message": "...", "chunk_index": 0, "total_chunks": N}
        - {"type": "chunk_result", "data": {...}, "chunk_index": 0}
        - {"type": "done", "data": {...合并结果...}, "missing": [...]}
        - 异常时由调用方捕获并转为 error 事件

        Args:
            text: 待抽取的长文本。
            schema_definition: 字段定义字典。
            sample_fields: 可选，字段示例。
            chunk_size: 单个 chunk 的字符数，默认 4000。
            overlap: 相邻 chunk 的重叠字符数，默认 200。

        Yields:
            dict: 事件字典。
        """
        if not isinstance(schema_definition, dict):
            raise BusinessException(
                code=ErrorCode.VALIDATION_ERROR,
                message="schema_definition 必须为字典类型",
            )
        if "fields" not in schema_definition or not isinstance(
            schema_definition["fields"], list
        ):
            raise BusinessException(
                code=ErrorCode.VALIDATION_ERROR,
                message="schema_definition 必须包含 fields 列表",
            )
        if not text or not text.strip():
            raise BusinessException(
                code=ErrorCode.VALIDATION_ERROR,
                message="待抽取文本不能为空",
            )

        # 切分文本
        chunks = self._split_text_into_chunks(text, chunk_size=chunk_size, overlap=overlap)
        total_chunks = len(chunks)

        logger.info(
            "开始流式抽取",
            text_len=len(text),
            total_chunks=total_chunks,
            chunk_size=chunk_size,
            overlap=overlap,
            field_count=len(schema_definition.get("fields", [])),
            has_samples=bool(sample_fields),
        )

        # 推送开始事件
        yield {
            "type": "progress",
            "progress": 0,
            "message": f"已切分为 {total_chunks} 个文本块，开始抽取",
            "chunk_index": 0,
            "total_chunks": total_chunks,
        }

        # 逐块抽取
        merged_data: dict = {}
        for idx, chunk in enumerate(chunks):
            # 推送当前块开始进度
            progress_pct = int(idx / total_chunks * 100)
            yield {
                "type": "progress",
                "progress": progress_pct,
                "message": f"正在抽取第 {idx + 1}/{total_chunks} 块…",
                "chunk_index": idx,
                "total_chunks": total_chunks,
            }

            try:
                chunk_data = await asyncio.to_thread(
                    self._extract_sync,
                    chunk,
                    schema_definition,
                    sample_fields,
                )
            except Exception as err:
                logger.error(
                    "流式抽取中单块失败，跳过该块",
                    chunk_index=idx,
                    error=str(err),
                    exc_info=True,
                )
                # 推送单块失败事件，但不终止整个流程
                yield {
                    "type": "chunk_error",
                    "chunk_index": idx,
                    "error": str(err),
                    "message": f"第 {idx + 1} 块抽取失败，已跳过",
                }
                continue

            # 合并结果：后出现的字段值覆盖前面的（取最后一个非空值）
            for k, v in chunk_data.items():
                if v is not None and v != "":
                    merged_data[k] = v
                elif k not in merged_data:
                    merged_data[k] = v

            # 推送单块完成事件（包含增量结果）
            yield {
                "type": "chunk_result",
                "data": chunk_data,
                "chunk_index": idx,
                "progress": int((idx + 1) / total_chunks * 100),
                "message": f"第 {idx + 1}/{total_chunks} 块抽取完成",
            }

        # 校验必填字段
        missing = self._validate_extraction(merged_data, schema_definition)

        # 推送完成事件
        yield {
            "type": "done",
            "data": merged_data,
            "missing": missing,
            "progress": 100,
            "message": f"抽取完成，共抽取 {len(merged_data)} 个字段"
                       + (f"，缺失必填字段：{', '.join(missing)}" if missing else ""),
        }

        logger.info(
            "流式抽取完成",
            extracted_field_count=len(merged_data),
            missing_required=missing,
            total_chunks=total_chunks,
        )


# 模块级单例，默认使用 settings.OLLAMA_HOST 作为 Ollama 服务地址
extraction_service = ExtractionService(model_url=settings.OLLAMA_HOST)
