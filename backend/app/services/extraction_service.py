"""结构化信息抽取服务模块。

本模块基于 Google LangExtract 库从非结构化文本中抽取结构化字段信息，主要能力包括：
- 模式驱动抽取：依据 schema_definition 描述的字段清单构造 few-shot 示例与提示
- Few-shot 示例：基于 schema 字段生成 ExampleData，引导模型理解抽取目标
- 字段缺失校验：对照 schema 检查必填字段是否齐全
- 批量抽取：对多段文本批量执行抽取

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

使用示例：
    from app.services.extraction_service import extraction_service

    schema = {
        "fields": [
            {"name": "材料名称", "type": "string", "description": "材料的标准名称"},
            {"name": "规格型号", "type": "string", "description": "规格与型号"},
        ]
    }
    data = await extraction_service.extract("某型号钢材规格为...", schema)
"""

import asyncio

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
    描述待抽取字段的名称、类型与含义，构造 few-shot 示例与提示描述引导模型抽取，
    并对输出做字段完整性校验。模型加载由 LangExtract 在抽取时按需处理，
    初始化阶段仅创建 ModelConfig，不建立任何连接。

    Attributes:
        _config: LangExtract 模型配置实例。
    """

    def __init__(
        self,
        model_id: str = "qwen3.5:9b",
        model_url: str = "http://localhost:11434",
    ) -> None:
        """初始化抽取服务。

        创建 LangExtract 的 ModelConfig，provider 固定为 ollama。
        模型加载由 LangExtract 在首次抽取时按需完成，此处仅保存配置。

        Args:
            model_id: Ollama 中已加载的模型标识，默认 "qwen3.5:9b"。
            model_url: Ollama 服务地址，默认 "http://localhost:11434"。
        """
        self._config = ModelConfig(
            model_id=model_id,
            provider="ollama",
            provider_kwargs={"model_url": model_url},
        )

    def _build_examples(self, schema_definition: dict) -> list[ExampleData]:
        """根据 schema 字段构造 few-shot 示例。

        为每个字段生成与类型匹配的示例值，拼装成一段示例文本，
        并创建对应的 Extraction 列表，使模型理解字段名与抽取目标的对应关系。

        Args:
            schema_definition: 字段定义字典，需包含 "fields" 列表。

        Returns:
            list[ExampleData]: 包含示例文本与抽取结果的 ExampleData 列表。
        """
        fields = schema_definition.get("fields", [])
        if not fields:
            return []

        # 按字段类型生成示例值，并拼装示例文本
        sample_values: dict[str, str] = {}
        text_segments: list[str] = []
        for field in fields:
            name = field.get("name", "")
            ftype = field.get("type", "string")
            value = self._sample_value_for_type(name, ftype)
            sample_values[name] = value
            text_segments.append(f"{name}为{value}")

        sample_text = "本示例文本中，" + "，".join(text_segments) + "。"

        extractions = [
            Extraction(
                extraction_class=name,
                extraction_text=value,
            )
            for name, value in sample_values.items()
        ]

        return [
            ExampleData(
                text=sample_text,
                extractions=extractions,
            )
        ]

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

    def _build_prompt_description(self, schema_definition: dict) -> str:
        """构建中文提示描述，说明抽取目标字段。

        将 schema 中的字段名、描述与必填/选填标记组织成自然语言描述，
        作为 langextract.extract 的 prompt_description 参数传入。

        Args:
            schema_definition: 字段定义字典，需包含 "fields" 列表。

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

        return (
            "从给定文本中抽取以下结构化字段信息：\n"
            f"{fields_text}\n"
            "仅抽取文本中明确出现的内容，不要编造文本中不存在的信息。"
        )

    def _validate_extraction(
        self, data: dict, schema_definition: dict
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
            # 字段缺失或值为 None 均视为缺失
            if name not in data or data[name] is None:
                missing.append(name)
        return missing

    async def extract(self, text: str, schema_definition: dict) -> dict:
        """从单段文本中抽取结构化信息。

        流程：
        1. 校验 schema_definition 格式与文本非空
        2. 构造 few-shot 示例与提示描述
        3. 通过 asyncio.to_thread 调用同步的 langextract.extract
        4. 将 AnnotatedDocument.extractions 转换为字典
        5. 校验必填字段是否齐全（缺失时记录警告但不阻断，返回已抽取数据）
        6. 返回抽取结果字典

        Args:
            text: 待抽取的非结构化文本。
            schema_definition: 字段定义字典，需包含 "fields" 列表。

        Returns:
            dict: 抽取得到的结构化数据，键为字段名，值为抽取内容或 None。

        Raises:
            BusinessException: schema 格式错误或抽取失败时抛出。
        """
        # 校验 schema_definition 格式
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

        # 构造示例与提示描述
        examples = self._build_examples(schema_definition)
        prompt_description = self._build_prompt_description(schema_definition)

        logger.info(
            "开始结构化抽取",
            text_len=len(text),
            field_count=len(schema_definition.get("fields", [])),
        )

        # 通过 asyncio.to_thread 调用同步的 langextract.extract
        try:
            result = await asyncio.to_thread(
                langextract.extract,
                text,
                prompt_description=prompt_description,
                examples=examples,
                config=self._config,
                format_type=FormatType.JSON,
                show_progress=False,
            )
        except BusinessException:
            # 业务异常已封装，直接向上抛出
            raise
        except Exception as err:
            logger.error("结构化抽取失败", error=str(err), exc_info=True)
            raise BusinessException(
                code=ErrorCode.BUSINESS_TASK_FAILED,
                message=f"结构化抽取失败：{err}",
                details={"error": str(err)},
            ) from err

        # 将 AnnotatedDocument.extractions 转换为字典
        extractions = getattr(result, "extractions", None) or []
        data: dict = {}
        for ext in extractions:
            data[ext.extraction_class] = ext.extraction_text

        # 校验必填字段
        missing = self._validate_extraction(data, schema_definition)
        if missing:
            # 缺失必填字段时记录警告，但不阻断返回已抽取的数据
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
        self, texts: list[str], schema_definition: dict
    ) -> list[dict]:
        """批量抽取多段文本的结构化信息。

        使用 asyncio.gather 并发执行多段文本的抽取任务，提升整体吞吐量。
        单段抽取失败不会中断其他任务，对应位置返回空字典并记录错误日志。

        Args:
            texts: 待抽取的文本列表。
            schema_definition: 字段定义字典，需包含 "fields" 列表。

        Returns:
            list[dict]: 抽取结果列表，顺序与输入 texts 一一对应；
                失败的位置返回空字典 {}。
        """
        if not texts:
            return []

        logger.info("开始批量抽取", batch_size=len(texts))

        async def _safe_extract(text: str) -> dict:
            """单段抽取的安全包装，异常时返回空字典而非中断批量任务。"""
            try:
                return await self.extract(text, schema_definition)
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

        # 并发执行所有抽取任务
        results = await asyncio.gather(*[_safe_extract(t) for t in texts])
        success_count = sum(1 for r in results if r)
        logger.info(
            "批量抽取完成",
            total=len(texts),
            success=success_count,
            failed=len(texts) - success_count,
        )
        return list(results)


# 模块级单例，默认使用 settings.OLLAMA_HOST 作为 Ollama 服务地址
extraction_service = ExtractionService(model_url=settings.OLLAMA_HOST)
