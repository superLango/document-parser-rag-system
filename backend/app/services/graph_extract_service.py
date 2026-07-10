"""知识图谱抽取服务 - 实体与关系抽取。

按方案 7.5 节实现，优先使用 DeepKE 进行实体关系抽取，
当 DeepKE 不可用时回退到 LLM（Qwen3.5-9B）进行抽取。

主要能力：
- DeepKE 抽取：基于 BERT 的关系抽取模型，提供 predict_entities / predict_relations
- LLM 回退：当 DeepKE 安装或加载失败时，使用 vLLM/Qwen3.5-9B 通过提示词抽取
- 批量抽取：并发处理多段文本

实体类型：材料、标准、工艺、参数、组织、设备、属性值
关系类型：执行标准、材质、用于、包含、参数值、属于、生产于

使用示例：
    from app.services.graph_extract_service import graph_extract_service

    result = await graph_extract_service.extract("本工程使用Q235钢材，执行GB/T700标准。")
    # result.entities -> [Entity(text="Q235钢材", type="材料"), ...]
    # result.relations -> [Relation(head="Q235钢材", relation="执行标准", tail="GB/T700"), ...]
"""

import asyncio
import json
from typing import Any, ClassVar, Optional

from pydantic import BaseModel, Field

from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger

logger = get_logger(__name__)


class Entity(BaseModel):
    """实体。

    Attributes:
        text: 实体文本内容。
        type: 实体类型，如 材料/标准/工艺/参数/组织/设备/属性值。
        start: 实体在原文中的起始字符偏移，缺省为 0。
        end: 实体在原文中的结束字符偏移，缺省为 0。
    """

    text: str
    type: str
    start: int = 0
    end: int = 0


class Relation(BaseModel):
    """关系。

    Attributes:
        head: 头实体文本。
        relation: 关系类型，如 执行标准/材质/用于/包含/参数值/属于/生产于。
        tail: 尾实体文本。
    """

    head: str
    relation: str
    tail: str


class ExtractionResult(BaseModel):
    """抽取结果。

    Attributes:
        entities: 抽取到的实体列表。
        relations: 抽取到的关系列表。
    """

    entities: list[Entity] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)


# LLM 抽取提示词中声明的实体与关系类型
_ENTITY_TYPES = "材料、标准、工艺、参数、组织、设备、属性值"
_RELATION_TYPES = "执行标准、材质、用于、包含、参数值、属于、生产于"

# LLM 抽取输入文本的最大长度，避免超出模型上下文窗口
_MAX_LLM_TEXT_LEN = 2000


class GraphExtractService:
    """知识图谱抽取服务。

    优先使用 DeepKE 进行实体关系抽取，DeepKE 不可用时回退到
    LLM（Qwen3.5-9B）抽取。模型初始化仅在首次实例化时执行一次，
    通过单例模式保证全局复用。

    Attributes:
        _deepke_model: DeepKE 模型实例，成功加载后非 None。
        _use_deepke: 是否使用 DeepKE 作为抽取后端。
        _initialized: 标记模型初始化是否已完成，避免重复初始化。
    """

    _instance: ClassVar[Optional["GraphExtractService"]] = None
    _deepke_model: Any = None
    _use_deepke: bool = False
    _initialized: bool = False

    def __new__(cls) -> "GraphExtractService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        # 已初始化则跳过，避免单例每次引用时重复加载模型
        if self._initialized:
            return
        self._init_model()

    def _init_model(self) -> None:
        """初始化抽取模型。

        尝试加载 DeepKE 关系抽取模型，失败时回退到 LLM 模式并记录警告。
        无论成功与否，均将 _initialized 置为 True 以避免重复尝试。
        """
        try:
            from deepke import DeepKE

            self._deepke_model = DeepKE(
                model_type="bert",
                task="relation_extraction",
            )
            self._use_deepke = True
            logger.info("DeepKE 模型已加载，将使用 DeepKE 进行知识抽取")
        except ImportError as err:
            logger.warning(
                "DeepKE 不可用，将使用 LLM 回退进行知识抽取",
                error=str(err),
            )
            self._use_deepke = False
        except Exception as err:
            # DeepKE 导入成功但初始化失败（如缺少预训练权重）
            logger.warning(
                "DeepKE 加载失败，回退到 LLM 抽取",
                error=str(err),
                exc_info=True,
            )
            self._use_deepke = False
        finally:
            self._initialized = True

    async def extract(self, text: str) -> ExtractionResult:
        """从文本中抽取实体和关系。

        根据初始化阶段确定的后端（DeepKE 或 LLM）执行抽取。

        Args:
            text: 待抽取的文本内容。

        Returns:
            ExtractionResult: 包含实体与关系的抽取结果。

        Raises:
            BusinessException: 文本为空或抽取失败时抛出。
        """
        if not text or not text.strip():
            raise BusinessException(
                code=ErrorCode.VALIDATION_ERROR,
                message="待抽取文本不能为空",
            )

        if self._use_deepke:
            return await self._extract_with_deepke(text)
        return await self._extract_with_llm(text)

    async def _extract_with_deepke(self, text: str) -> ExtractionResult:
        """使用 DeepKE 抽取实体和关系。

        DeepKE 的 predict_entities / predict_relations 为同步阻塞调用，
        通过 asyncio.to_thread 放入线程池执行，避免阻塞事件循环。

        Args:
            text: 待抽取的文本内容。

        Returns:
            ExtractionResult: 抽取结果。

        Raises:
            BusinessException: DeepKE 推理失败时抛出。
        """
        logger.info("使用 DeepKE 抽取知识", text_len=len(text))

        def _predict() -> dict:
            """在线程池中执行的同步推理逻辑。"""
            entities = self._deepke_model.predict_entities(text)
            relations = self._deepke_model.predict_relations(text)
            return {"entities": entities, "relations": relations}

        try:
            result = await asyncio.to_thread(_predict)
        except BusinessException:
            raise
        except Exception as err:
            logger.error("DeepKE 抽取失败", error=str(err), exc_info=True)
            raise BusinessException(
                code=ErrorCode.BUSINESS_TASK_FAILED,
                message=f"DeepKE 抽取失败：{err}",
                details={"error": str(err)},
            ) from err

        entities = [Entity(**e) for e in result.get("entities", [])]
        relations = [Relation(**r) for r in result.get("relations", [])]
        logger.info(
            "DeepKE 抽取完成",
            entity_count=len(entities),
            relation_count=len(relations),
        )
        return ExtractionResult(entities=entities, relations=relations)

    async def _extract_with_llm(self, text: str) -> ExtractionResult:
        """使用 LLM（Qwen3.5-9B）抽取实体关系 - DeepKE 回退方案。

        通过构造提示词引导 LLM 以 JSON 格式输出实体与关系，
        再解析为 ExtractionResult。

        Args:
            text: 待抽取的文本内容。

        Returns:
            ExtractionResult: 抽取结果。

        Raises:
            BusinessException: LLM 调用或解析失败时抛出。
        """
        from app.services.llm_service import llm_service

        # 截断超长文本，避免超出模型上下文窗口
        truncated = text[:_MAX_LLM_TEXT_LEN]
        prompt = self._build_llm_prompt(truncated)

        logger.info("使用 LLM 抽取知识", text_len=len(truncated))

        try:
            response = await llm_service.generate_json(prompt)
        except BusinessException:
            raise
        except Exception as err:
            logger.error("LLM 知识抽取失败", error=str(err), exc_info=True)
            raise BusinessException(
                code=ErrorCode.BUSINESS_TASK_FAILED,
                message=f"LLM 知识抽取失败：{err}",
                details={"error": str(err)},
            ) from err

        entities_data = response.get("entities", []) if isinstance(response, dict) else []
        relations_data = response.get("relations", []) if isinstance(response, dict) else []

        # 逐条解析，跳过格式不合法的条目而非整体失败
        entities = self._parse_entities(entities_data)
        relations = self._parse_relations(relations_data)

        logger.info(
            "LLM 抽取完成",
            entity_count=len(entities),
            relation_count=len(relations),
        )
        return ExtractionResult(entities=entities, relations=relations)

    @staticmethod
    def _build_llm_prompt(text: str) -> str:
        """构造 LLM 知识抽取提示词。

        Args:
            text: 待抽取的文本内容（已截断）。

        Returns:
            str: 完整的提示词。
        """
        return (
            "请从以下技术文档中抽取实体和关系，返回 JSON 格式。\n\n"
            f"实体类型：{_ENTITY_TYPES}\n"
            f"关系类型：{_RELATION_TYPES}\n\n"
            "文档内容：\n"
            f"{text}\n\n"
            "请返回 JSON 格式：\n"
            "{\n"
            '  "entities": [{"text": "实体文本", "type": "类型"}],\n'
            '  "relations": [{"head": "头实体", "relation": "关系", "tail": "尾实体"}]\n'
            "}\n"
        )

    @staticmethod
    def _parse_entities(entities_data: Any) -> list[Entity]:
        """将 LLM 返回的实体列表解析为 Entity 对象列表。

        跳过非字典或缺少必填字段的条目，记录警告但不抛出异常。

        Args:
            entities_data: LLM 返回的原始实体数据。

        Returns:
            list[Entity]: 成功解析的实体列表。
        """
        if not isinstance(entities_data, list):
            return []
        entities: list[Entity] = []
        for item in entities_data:
            if not isinstance(item, dict):
                continue
            try:
                entities.append(Entity(**item))
            except Exception as err:
                logger.warning("跳过格式不合法的实体条目", item=item, error=str(err))
        return entities

    @staticmethod
    def _parse_relations(relations_data: Any) -> list[Relation]:
        """将 LLM 返回的关系列表解析为 Relation 对象列表。

        跳过非字典或缺少必填字段的条目，记录警告但不抛出异常。

        Args:
            relations_data: LLM 返回的原始关系数据。

        Returns:
            list[Relation]: 成功解析的关系列表。
        """
        if not isinstance(relations_data, list):
            return []
        relations: list[Relation] = []
        for item in relations_data:
            if not isinstance(item, dict):
                continue
            try:
                relations.append(Relation(**item))
            except Exception as err:
                logger.warning("跳过格式不合法的关系条目", item=item, error=str(err))
        return relations

    async def extract_batch(self, texts: list[str]) -> list[ExtractionResult]:
        """批量抽取多段文本的实体和关系。

        使用 asyncio.gather 并发执行多段文本的抽取任务。单段抽取失败
        不会中断其他任务，对应位置返回空结果并记录错误日志。

        Args:
            texts: 待抽取的文本列表。

        Returns:
            list[ExtractionResult]: 抽取结果列表，顺序与输入一一对应；
                失败的位置返回空的 ExtractionResult。
        """
        if not texts:
            return []

        logger.info("开始批量知识抽取", batch_size=len(texts))

        async def _safe_extract(text: str) -> ExtractionResult:
            """单段抽取的安全包装，异常时返回空结果而非中断批量任务。"""
            try:
                return await self.extract(text)
            except BusinessException as err:
                logger.warning(
                    "批量抽取中单段失败，返回空结果",
                    message=err.message,
                    text_preview=text[:100],
                )
                return ExtractionResult()
            except Exception as err:
                logger.error(
                    "批量抽取中单段发生未预期异常",
                    error=str(err),
                    exc_info=True,
                )
                return ExtractionResult()

        results = await asyncio.gather(*[_safe_extract(t) for t in texts])
        success_count = sum(1 for r in results if r.entities or r.relations)
        logger.info(
            "批量知识抽取完成",
            total=len(texts),
            success=success_count,
            failed=len(texts) - success_count,
        )
        return list(results)


# 模块级单例，供整个应用直接导入使用
graph_extract_service = GraphExtractService()
