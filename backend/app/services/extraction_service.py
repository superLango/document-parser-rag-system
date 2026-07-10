"""结构化信息抽取服务模块。

本模块基于 LLMService 从非结构化文本中抽取结构化字段信息，主要能力包括：
- 模式驱动抽取：依据 schema_definition 描述的字段清单构造提示词
- JSON 输出约束：要求模型仅输出合法 JSON，并做后处理解析与校验
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
import json

from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.services.llm_service import LLMService, llm_service

logger = get_logger(__name__)

# 抽取任务的系统提示词，约束模型行为与输出格式
_EXTRACTION_SYSTEM_PROMPT = (
    "你是一个专业的结构化信息抽取助手。你的任务是根据给定的字段 schema，"
    "从用户提供的文本中抽取结构化信息，并以严格的 JSON 格式输出。\n\n"
    "输出要求：\n"
    "1. 仅输出一个合法的 JSON 对象，不要输出任何额外文字、解释或 markdown 标记\n"
    "2. JSON 的键必须与 schema 中的字段 name 完全一致\n"
    "3. 若文本中无法找到某字段的值，将该字段的值设为 null\n"
    "4. 字段值应为字符串、数字或布尔类型，不要输出嵌套对象\n"
    "5. 不要编造文本中不存在的信息"
)


class ExtractionService:
    """结构化信息抽取服务。

    基于 LLMService 执行文本到结构化字段的抽取。通过 schema_definition
    描述待抽取字段的名称、类型与含义，构造提示词引导模型输出 JSON，
    并对输出做字段完整性校验。

    Attributes:
        _llm: 注入的 LLM 服务实例。
    """

    def __init__(self, llm: LLMService) -> None:
        """初始化抽取服务。

        Args:
            llm: 已配置好的 LLM 服务实例，用于执行模型推理。
        """
        self._llm = llm

    def _build_extraction_prompt(self, text: str, schema_definition: dict) -> str:
        """构建抽取提示词。

        根据 schema_definition 中描述的字段清单，构造详细的用户提示词，
        指导模型从文本中抽取对应字段并输出 JSON。

        Args:
            text: 待抽取的非结构化文本。
            schema_definition: 字段定义字典，需包含 "fields" 列表，
                每个 field 含 name、type、description、required 等键。

        Returns:
            str: 拼接完成的用户提示词。
        """
        fields = schema_definition.get("fields", [])
        # 构造字段说明清单
        field_lines: list[str] = []
        for field in fields:
            name = field.get("name", "")
            ftype = field.get("type", "string")
            desc = field.get("description", "")
            required = field.get("required", False)
            req_label = "必填" if required else "选填"
            field_lines.append(
                f"- 字段名: {name} | 类型: {ftype} | 是否必填: {req_label} | 说明: {desc}"
            )
        fields_text = "\n".join(field_lines) if field_lines else "（无字段定义）"

        # 构造输出示例，帮助模型理解期望格式
        example_keys = [f.get("name", "") for f in fields[:3]] if fields else ["字段1"]
        example_obj = {k: "<对应值或null>" for k in example_keys}
        example_json = json.dumps(example_obj, ensure_ascii=False, indent=2)

        prompt = (
            f"请从以下文本中抽取结构化信息。\n\n"
            f"【待抽取字段 schema】\n{fields_text}\n\n"
            f"【待抽取文本】\n{text}\n\n"
            f"【输出要求】\n"
            f"1. 输出一个 JSON 对象，键为字段名，值为抽取到的内容\n"
            f"2. 仅输出 JSON，不要包含任何其他文字或解释\n"
            f"3. 找不到的字段值设为 null\n\n"
            f"【输出示例（仅供参考格式，实际值以文本为准）】\n{example_json}"
        )
        return prompt

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
        1. 校验 schema_definition 格式
        2. 构造抽取提示词
        3. 调用 LLM 生成 JSON
        4. 校验必填字段是否齐全（缺失时记录警告但不阻断，返回已抽取数据）
        5. 返回抽取结果字典

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

        # 构造提示词并调用 LLM
        prompt = self._build_extraction_prompt(text, schema_definition)
        logger.info(
            "开始结构化抽取",
            text_len=len(text),
            field_count=len(schema_definition.get("fields", [])),
        )

        try:
            data = await self._llm.generate_json(
                prompt=prompt,
                system_prompt=_EXTRACTION_SYSTEM_PROMPT,
            )
        except BusinessException:
            # LLM 调用异常已封装，直接向上抛出
            raise
        except Exception as err:
            logger.error("结构化抽取失败", error=str(err), exc_info=True)
            raise BusinessException(
                code=ErrorCode.BUSINESS_TASK_FAILED,
                message=f"结构化抽取失败：{err}",
                details={"error": str(err)},
            ) from err

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


# 模块级单例，依赖 llm_service 单例
extraction_service = ExtractionService(llm_service)
