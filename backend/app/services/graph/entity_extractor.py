"""知识图谱抽取服务 - 基于OneKE指令格式的LLM知识抽取。

使用OneKE/IEPile风格的schema指令，通过vLLM(Qwen3.5-9B)进行
实体和关系抽取，替代原DeepKE方案。

实体类型：材料、标准、工艺、参数、组织、设备、属性值
关系类型：执行标准、材质、用于、包含、参数值、属于、生产于

使用示例：
    from app.services.graph.entity_extractor import graph_extract_service

    result = await graph_extract_service.extract("本工程使用Q235钢材，执行GB/T700标准。")
    # result.entities -> [Entity(text="Q235钢材", type="材料"), ...]
    # result.relations -> [Relation(head="Q235钢材", relation="执行标准", tail="GB/T700"), ...]
"""

import asyncio
from typing import Any

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


# OneKE schema 声明的实体与关系类型
_ENTITY_TYPES = "材料、标准、工艺、参数、组织、设备、属性值"
_RELATION_TYPES = "执行标准、材质、用于、包含、参数值、属于、生产于"

# LLM 抽取输入文本的最大长度，避免超出模型上下文窗口
_MAX_LLM_TEXT_LEN = 2000


class GraphExtractService:
    """知识图谱抽取服务。

    基于OneKE/IEPile风格的schema指令，通过vLLM(Qwen3.5-9B)进行
    实体和关系抽取。无需加载本地模型，所有推理均通过LLM服务完成。
    """

    def __init__(self) -> None:
        # 无需任何模型加载，所有抽取通过LLM服务完成
        pass

    async def extract(self, text: str) -> ExtractionResult:
        """从文本中抽取实体和关系。

        基于OneKE schema驱动的指令构建提示词，调用LLM服务进行抽取，
        再解析返回的JSON为 ExtractionResult。

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

        from app.services.llm.llm_service import llm_service

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
        """构造OneKE风格的知识抽取指令。

        基于IEPile格式，使用schema驱动的指令构建。
        """
        return (
            "你是一个知识抽取助手。请从以下文本中抽取实体和关系。\n\n"
            "Schema:\n"
            f"实体类型: {_ENTITY_TYPES}\n"
            f"关系类型: {_RELATION_TYPES}\n\n"
            "指令:\n"
            "请从给定的文本中抽取符合Schema定义的实体和关系三元组。\n"
            "输出JSON格式，包含entities和relations两个字段。\n\n"
            "文本:\n"
            f"{text}\n\n"
            "输出格式:\n"
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

    async def extract_entities_and_relations(
        self,
        text: str,
        doc_id: str | None = None,
        kb_id: str | None = None,
    ) -> tuple[list[Entity], list[Relation]]:
        """从文本中抽取实体和关系（供index_graph_tasks使用的简化接口）。

        Args:
            text: 待抽取的文本内容。
            doc_id: 文档 ID（用于日志记录）。
            kb_id: 知识库 ID（用于日志记录）。

        Returns:
            tuple: (entities, relations) 实体和关系列表。
        """
        result = await self.extract(text)
        return result.entities, result.relations


# 模块级单例，供整个应用直接导入使用
graph_extract_service = GraphExtractService()
graph_entity_extractor = graph_extract_service
