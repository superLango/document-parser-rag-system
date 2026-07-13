"""知识图谱构建任务模块。

本模块定义 arq 异步任务，负责将文档解析结果构建为知识图谱的完整流水线：

1. ``build_document_graph_impl``：单文档知识图谱构建主任务，执行端到端流程：
   - 从数据库加载 Document 记录
   - 获取已解析的文本（Document.parsed_text）
   - 调用结构感知分块器对文本进行章节分块
   - 使用 graph_extract_service.extract_batch 抽取实体与关系
   - 按实体名称去重合并（merge by entity name）
   - 调用 graph_store.batch_create 将节点与关系写入 Neo4j
   - 更新 Document.status = "graph_built"

2. ``rebuild_all_graphs_impl``：重建所有文档的知识图谱
   - 遍历所有已解析文档并重新构建图谱

3. ``remove_document_graph_impl``：删除指定文档的知识图谱数据
   - 按 doc_id 删除 Neo4j 中的关联节点与关系

arq 任务原生为 async 函数，与服务层异步接口完美契合，无需 ``asyncio.run`` 包装。
数据库访问直接使用 ``AsyncSessionLocal`` 上下文管理器，而非 FastAPI 的 ``get_db`` 依赖。

错误处理策略：
    图谱构建过程中任一阶段抛出异常时，将 ``Document.status`` 置为 ``failed``，
    记录错误信息，更新任务状态为 ``failed``，并重新抛出以由 arq 标记失败。
"""

import re
import traceback
import uuid

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.exceptions import BusinessException, ErrorCode
from app.core.logging import get_logger
from app.models.document import Document
from app.models.task import Task as TaskModel
from app.services.chunking_service import chunker
from app.services.graph_extract_service import (
    Entity,
    ExtractionResult,
    Relation,
    graph_extract_service,
)
from app.services.graph_store import graph_store

logger = get_logger(__name__)


# ---------------------------------------------------------------
# 实体类型与关系类型中英文映射
# ---------------------------------------------------------------
# Neo4j 节点标签与关系类型仅允许字母、数字、下划线（graph_store 校验），
# 因此将抽取服务输出的中文类型映射为英文标签。
_ENTITY_TYPE_MAP: dict[str, str] = {
    "材料": "Material",
    "标准": "Standard",
    "工艺": "Process",
    "参数": "Parameter",
    "组织": "Organization",
    "设备": "Equipment",
    "属性值": "Attribute",
}

_RELATION_TYPE_MAP: dict[str, str] = {
    "执行标准": "EXECUTES_STANDARD",
    "材质": "MATERIAL_OF",
    "用于": "USED_FOR",
    "包含": "CONTAINS",
    "参数值": "PARAM_VALUE",
    "属于": "BELONGS_TO",
    "生产于": "PRODUCED_IN",
}

# 合法标签正则：字母/下划线开头，仅含字母数字下划线
_LABEL_SAFE_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _map_entity_type(entity_type: str) -> str:
    """将中文实体类型映射为英文节点标签。

    未知类型回退为 "Entity" 以保证写入不中断，并记录警告。

    Args:
        entity_type: 抽取服务输出的中文实体类型。

    Returns:
        str: 合法的英文节点标签。
    """
    mapped = _ENTITY_TYPE_MAP.get(entity_type)
    if mapped:
        return mapped
    # 已是合法英文标签则直接使用
    if entity_type and _LABEL_SAFE_PATTERN.match(entity_type):
        return entity_type
    logger.warning("未知实体类型，回退为 Entity", entity_type=entity_type)
    return "Entity"


def _map_relation_type(relation_type: str) -> str:
    """将中文关系类型映射为英文关系类型。

    未知类型回退为 "RELATED_TO" 以保证写入不中断，并记录警告。

    Args:
        relation_type: 抽取服务输出的中文关系类型。

    Returns:
        str: 合法的英文关系类型。
    """
    mapped = _RELATION_TYPE_MAP.get(relation_type)
    if mapped:
        return mapped
    if relation_type and _LABEL_SAFE_PATTERN.match(relation_type):
        return relation_type
    logger.warning("未知关系类型，回退为 RELATED_TO", relation_type=relation_type)
    return "RELATED_TO"


async def _update_progress(task_id: str | None, progress: int, message: str) -> None:
    """更新任务进度到数据库。

    在独立的 ``AsyncSessionLocal`` 会话中更新 Task 记录的 progress 与 status 字段。
    若 task_id 为 None 或任务记录不存在，则静默跳过（不影响主流程）。

    Args:
        task_id: 任务唯一标识（arq job_id），为 None 时跳过。
        progress: 进度百分比（0-100）。
        message: 进度描述信息（当前未持久化，预留扩展）。
    """
    if not task_id:
        return
    try:
        async with AsyncSessionLocal() as db:
            stmt = select(TaskModel).where(TaskModel.id == task_id)
            result = await db.execute(stmt)
            task = result.scalar_one_or_none()
            if task:
                task.progress = progress
                task.status = "progress"
                await db.commit()
    except Exception as exc:
        # 进度更新失败不应影响主流程，仅记录日志
        logger.warning("更新任务进度失败", task_id=task_id, error=str(exc))


async def build_document_graph_impl(doc_id: str, ctx: dict) -> dict:
    """为文档构建知识图谱（arq 异步入口）。

    接收文档标识，执行完整的图谱构建流程：
    加载文档 → 获取解析文本 → 结构分块 → 实体关系抽取 → 去重 → Neo4j 入库。

    arq 任务原生为 async 函数，与服务层异步接口直接配合，无需 ``asyncio.run``。
    进度通过更新数据库 Task 记录上报，替代 Celery 的 ``self.update_state``。

    Args:
        doc_id: 待构建图谱文档的唯一标识（UUID 字符串）。
        ctx: arq 任务上下文，包含 ``job_id`` 等元数据。

    Returns:
        dict: 构建结果，包含 doc_id、status、entity_count、relation_count。

    Raises:
        Exception: 图谱构建过程中任一阶段失败时重新抛出，由 arq 标记任务失败。
    """
    # 从 arq ctx 获取任务 ID，用于数据库进度更新
    task_id: str | None = ctx.get("job_id") if isinstance(ctx, dict) else None

    logger.info("开始构建文档知识图谱", doc_id=doc_id, task_id=task_id)
    # 上报初始进度
    await _update_progress(task_id, 10, "开始构建图谱")

    doc_uuid: uuid.UUID = uuid.UUID(doc_id)

    try:
        async with AsyncSessionLocal() as db:
            # 加载文档记录，不存在则直接失败
            document: Document | None = await db.get(Document, doc_uuid)
            if document is None:
                raise BusinessException(
                    message=f"文档不存在: {doc_id}",
                    code=ErrorCode.BUSINESS_DOCUMENT_NOT_FOUND,
                )

            # 校验文档已解析完成
            if not document.parsed_text:
                raise BusinessException(
                    message="文档尚未解析完成，无法构建图谱",
                    code=ErrorCode.BUSINESS_TASK_FAILED,
                )

            try:
                # ----------------------------------------------------------
                # 阶段 1：准备文档元数据（进度 10%）
                # ----------------------------------------------------------
                doc_meta: dict = {
                    "doc_id": doc_id,
                    "doc_title": document.filename or "未命名文档",
                    "file_name": document.filename or "",
                }

                # ----------------------------------------------------------
                # 阶段 2：结构感知分块（进度 30%）
                # ----------------------------------------------------------
                await _update_progress(task_id, 30, "文本分块中")
                chunks: list[dict] = await chunker.chunk_document(
                    document.parsed_text, doc_meta
                )
                if not chunks:
                    raise BusinessException(
                        message="文档分块结果为空，无法构建图谱",
                        code=ErrorCode.BUSINESS_TASK_FAILED,
                    )
                logger.info(
                    "图谱构建分块完成",
                    doc_id=doc_id,
                    chunk_count=len(chunks),
                )

                # ----------------------------------------------------------
                # 阶段 3：批量抽取实体与关系（进度 60%）
                # ----------------------------------------------------------
                await _update_progress(task_id, 60, "抽取实体关系中")
                texts: list[str] = [c["text"] for c in chunks]
                extraction_results: list[ExtractionResult] = (
                    await graph_extract_service.extract_batch(texts)
                )
                logger.info(
                    "实体关系抽取完成",
                    doc_id=doc_id,
                    batch_count=len(extraction_results),
                )

                # ----------------------------------------------------------
                # 阶段 4：去重合并 + 组装入库数据
                # ----------------------------------------------------------
                nodes, relations = _merge_and_build(extraction_results, doc_id)
                logger.info(
                    "实体关系去重完成",
                    doc_id=doc_id,
                    node_count=len(nodes),
                    relation_count=len(relations),
                )

                # ----------------------------------------------------------
                # 阶段 5：写入 Neo4j（进度 90%）
                # ----------------------------------------------------------
                await _update_progress(task_id, 90, "写入图数据库中")
                store_result: dict = await graph_store.batch_create(nodes, relations)
                logger.info(
                    "图谱入库完成",
                    doc_id=doc_id,
                    nodes_created=store_result.get("nodes_created", 0),
                    relations_created=store_result.get("relations_created", 0),
                )

                # ----------------------------------------------------------
                # 阶段 6：更新文档状态为 graph_built（进度 100%）
                # ----------------------------------------------------------
                document.status = "graph_built"
                await db.commit()

                await _update_progress(task_id, 100, "图谱构建完成")
                logger.info(
                    "文档知识图谱构建任务完成",
                    doc_id=doc_id,
                    entity_count=len(nodes),
                    relation_count=len(relations),
                )

                return {
                    "doc_id": doc_id,
                    "status": "graph_built",
                    "entity_count": len(nodes),
                    "relation_count": len(relations),
                }

            except Exception as exc:
                # 异常处理：标记文档为失败，回滚后写入错误状态
                logger.error(
                    "图谱构建过程中异常，标记文档为失败",
                    doc_id=doc_id,
                    error=str(exc),
                )
                await db.rollback()
                try:
                    # 重新获取文档并标记失败（rollback 后原对象已过期）
                    failed_doc: Document | None = await db.get(Document, doc_uuid)
                    if failed_doc is not None:
                        failed_doc.status = "failed"
                        await db.commit()
                except Exception as mark_err:
                    logger.error(
                        "标记文档失败状态时再次异常",
                        doc_id=doc_id,
                        error=str(mark_err),
                    )
                raise

    except Exception as exc:
        # 记录完整错误堆栈，便于排障
        logger.error(
            "文档知识图谱构建任务失败",
            doc_id=doc_id,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        raise


def _merge_and_build(
    extraction_results: list[ExtractionResult], doc_id: str
) -> tuple[list[dict], list[dict]]:
    """合并多段抽取结果并组装 Neo4j 入库数据。

    - 实体按 ``(name, type)`` 去重，同名同类型实体合并为单个节点。
    - 关系按 ``(head, relation, tail)`` 去重。
    - 所有节点附带 ``doc_id`` 属性以支持文档级追溯与删除。

    Args:
        extraction_results: 多段文本的抽取结果列表。
        doc_id: 文档 ID，写入节点属性以支持追溯。

    Returns:
        tuple[list[dict], list[dict]]: (nodes, relations) 已去重的入库数据。
    """
    # 实体去重：以 (name, mapped_label) 为键
    entity_map: dict[tuple[str, str], dict] = {}
    # 关系去重：以 (head_name, relation_type, tail_name) 为键
    relation_map: dict[tuple[str, str, str], dict] = {}

    # 记录实体名称到标签的映射，便于后续关系组装时查找尾节点标签
    name_to_label: dict[str, str] = {}

    for result in extraction_results:
        entity: Entity
        for entity in result.entities:
            if not entity.text or not entity.text.strip():
                continue
            label = _map_entity_type(entity.type)
            name = entity.text.strip()
            key = (name, label)
            if key not in entity_map:
                entity_map[key] = {
                    "label": label,
                    "properties": {
                        "name": name,
                        "type": entity.type,
                        "doc_id": doc_id,
                    },
                }
                name_to_label[name] = label

        relation: Relation
        for relation in result.relations:
            if not relation.head or not relation.tail:
                continue
            head_name = relation.head.strip()
            tail_name = relation.tail.strip()
            rel_type = _map_relation_type(relation.relation)
            key = (head_name, rel_type, tail_name)
            if key not in relation_map:
                head_label = name_to_label.get(head_name, "Entity")
                tail_label = name_to_label.get(tail_name, "Entity")
                relation_map[key] = {
                    "head_label": head_label,
                    "head_name": head_name,
                    "relation": rel_type,
                    "tail_label": tail_label,
                    "tail_name": tail_name,
                    "properties": {"doc_id": doc_id},
                }

    nodes: list[dict] = list(entity_map.values())
    relations: list[dict] = list(relation_map.values())
    return nodes, relations


async def rebuild_all_graphs_impl(ctx: dict) -> dict:
    """重建所有文档的知识图谱（arq 异步入口）。

    处理流程：
        1. 查询所有已解析（completed / indexed / graph_built）的文档
        2. 逐个重新构建知识图谱

    Args:
        ctx: arq 任务上下文，包含 ``job_id`` 等元数据。

    Returns:
        dict: 重建结果，包含 total_docs、success_count、failed_count。
    """
    logger.info("开始重建所有文档知识图谱")
    try:
        # 查询所有已解析文档（包含 completed / indexed / graph_built 状态）
        async with AsyncSessionLocal() as db:
            stmt = select(Document).where(
                Document.status.in_(["completed", "indexed", "graph_built"])
            )
            result = await db.execute(stmt)
            documents: list[Document] = list(result.scalars().all())

        total_docs: int = len(documents)
        success_count: int = 0
        failed_count: int = 0
        failed_docs: list[str] = []

        logger.info("开始逐一重建知识图谱", total_docs=total_docs)

        # 逐个重建图谱
        for doc in documents:
            doc_id_str = str(doc.id)
            try:
                # 复用 build_document_graph_impl 完成单文档图谱构建
                # 传入空 ctx 以跳过进度上报（重建过程不单独更新进度）
                await build_document_graph_impl(doc_id_str, {})
                success_count += 1
                logger.info(
                    "文档重建图谱成功",
                    doc_id=doc_id_str,
                    progress=f"{success_count}/{total_docs}",
                )
            except Exception as exc:
                failed_count += 1
                failed_docs.append(doc_id_str)
                logger.error(
                    "文档重建图谱失败",
                    doc_id=doc_id_str,
                    error=str(exc),
                )

        logger.info(
            "知识图谱重建完成",
            total_docs=total_docs,
            success_count=success_count,
            failed_count=failed_count,
        )
        return {
            "total_docs": total_docs,
            "success_count": success_count,
            "failed_count": failed_count,
            "failed_docs": failed_docs,
        }
    except Exception as exc:
        logger.error(
            "知识图谱重建任务失败",
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        raise


async def remove_document_graph_impl(doc_id: str, ctx: dict) -> dict:
    """删除文档的知识图谱数据（arq 异步入口）。

    按 ``doc_id`` 删除 Neo4j 中该文档的所有关联节点与关系。
    不删除 Document 数据库记录本身（由文档管理端点负责）。

    Args:
        doc_id: 待删除图谱数据的文档唯一标识（UUID 字符串）。
        ctx: arq 任务上下文，包含 ``job_id`` 等元数据。

    Returns:
        dict: 删除结果，包含 doc_id、status、deleted。
    """
    logger.info("删除文档知识图谱数据", doc_id=doc_id)
    try:
        deleted: int = await graph_store.delete_by_doc(doc_id)
        logger.info("文档图谱已删除", doc_id=doc_id, deleted=deleted)
        return {"doc_id": doc_id, "status": "removed", "deleted": deleted}
    except Exception as exc:
        logger.error(
            "删除文档图谱失败",
            doc_id=doc_id,
            error=str(exc),
            traceback=traceback.format_exc(),
        )
        raise
