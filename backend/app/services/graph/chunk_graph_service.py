"""跨语义块知识关联图谱服务。

利用 Neo4j graph_store 构建语义块、实体、章节之间的关联图谱，
实现实体间关系的可视化与可查询。

节点类型：
- SemanticChunk: 语义块节点（chunk_id/summary/category/doc_id）
- Entity: 关键实体节点（牌号/标准号/项目名）
- Section: 章节节点

关系类型：
- BELONGS_TO: SemanticChunk → Section
- CONTAINS_ENTITY: SemanticChunk → Entity
- RELATED_TO: SemanticChunk → SemanticChunk（基于共享实体）
- SAME_CATEGORY: SemanticChunk → SemanticChunk（同类别关联）
"""

from __future__ import annotations

from typing import Any

from app.core.logging import get_logger
from app.services.rag.chunk_services.chunk_summary import chunk_summary_service

logger = get_logger("chunk_graph")


class ChunkGraphService:
    """跨语义块知识关联图谱构建服务。"""

    async def build_graph_for_document(
        self,
        doc_id: str,
        semantic_chunks: list[dict[str, Any]],
    ) -> dict[str, int]:
        """为文档构建跨语义块知识关联图谱。

        Args:
            doc_id: 文档 ID。
            semantic_chunks: 语义块列表，每个块包含：
                - chunk_id: 分块 ID
                - text: 文本内容
                - title_chain: 章节路径
                - category: 所属类别
                - summary: 摘要字典（可选，无则自动生成）

        Returns:
            dict: 创建统计 {nodes: N, relations: M, entities: E}
        """
        from app.services.graph.graph_store import graph_store

        if not semantic_chunks:
            return {"nodes": 0, "relations": 0, "entities": 0}

        # 清理旧图谱（文档重建场景）
        try:
            await graph_store.delete_by_doc(doc_id)
        except Exception as err:
            logger.warning("清理旧图谱失败", doc_id=doc_id, error=str(err))

        node_count = 0
        relation_count = 0
        entity_set: set[str] = set()

        # 1. 创建章节节点
        sections_map: dict[str, str] = {}  # section_name → name
        for chunk in semantic_chunks:
            title_chain = chunk.get("title_chain", "")
            if not title_chain:
                continue
            for section in title_chain.split(">"):
                section = section.strip()
                if section and section not in sections_map:
                    sections_map[section] = section
                    try:
                        await graph_store.create_node(
                            "Section",
                            {"name": section, "doc_id": doc_id, "type": "section"},
                        )
                        node_count += 1
                    except Exception as err:
                        logger.warning("创建章节节点失败", section=section, error=str(err))

        # 2. 创建语义块节点 + 关联章节
        chunk_names: list[str] = []
        for idx, chunk in enumerate(semantic_chunks):
            chunk_id = chunk.get("chunk_id", f"chunk_{idx}")
            chunk_name = f"{doc_id}_chunk_{idx}"
            chunk_names.append(chunk_name)

            # 生成摘要（如果未提供）
            summary = chunk.get("summary")
            if not summary:
                summary = chunk_summary_service.generate_summary(
                    chunk.get("text", ""),
                    chunk.get("title_chain", ""),
                    chunk.get("category", ""),
                )

            # 创建 SemanticChunk 节点
            try:
                await graph_store.create_node(
                    "SemanticChunk",
                    {
                        "name": chunk_name,
                        "doc_id": doc_id,
                        "chunk_id": chunk_id,
                        "category": chunk.get("category", ""),
                        "core_topic": summary.get("core_topic", ""),
                        "text_preview": chunk.get("text", "")[:200],
                    },
                )
                node_count += 1
            except Exception as err:
                logger.warning("创建语义块节点失败", chunk_name=chunk_name, error=str(err))
                continue

            # BELONGS_TO: SemanticChunk → Section
            title_chain = chunk.get("title_chain", "")
            if title_chain:
                primary_section = title_chain.split(">")[0].strip()
                if primary_section:
                    try:
                        await graph_store.create_relation(
                            "SemanticChunk", chunk_name,
                            "BELONGS_TO", "Section", primary_section,
                            {"doc_id": doc_id},
                        )
                        relation_count += 1
                    except Exception as err:
                        logger.warning("创建 BELONGS_TO 关系失败", error=str(err))

            # CONTAINS_ENTITY: SemanticChunk → Entity
            entities = summary.get("key_entities", {})
            for grade in entities.get("grades", []):
                entity_name = f"牌号_{grade}"
                entity_set.add(entity_name)
                try:
                    await graph_store.create_node(
                        "Entity",
                        {"name": entity_name, "type": "grade", "value": grade, "doc_id": doc_id},
                    )
                    node_count += 1
                    await graph_store.create_relation(
                        "SemanticChunk", chunk_name,
                        "CONTAINS_ENTITY", "Entity", entity_name,
                        {"entity_type": "grade"},
                    )
                    relation_count += 1
                except Exception as err:
                    logger.warning("创建实体关系失败", entity=entity_name, error=str(err))

            for std in entities.get("standards", []):
                entity_name = f"标准_{std}"
                entity_set.add(entity_name)
                try:
                    await graph_store.create_node(
                        "Entity",
                        {"name": entity_name, "type": "standard", "value": std, "doc_id": doc_id},
                    )
                    node_count += 1
                    await graph_store.create_relation(
                        "SemanticChunk", chunk_name,
                        "CONTAINS_ENTITY", "Entity", entity_name,
                        {"entity_type": "standard"},
                    )
                    relation_count += 1
                except Exception as err:
                    logger.warning("创建标准关系失败", entity=entity_name, error=str(err))

        # 3. 创建 SAME_CATEGORY 和 RELATED_TO 关系
        # 同类别的相邻语义块建立 SAME_CATEGORY 关系
        for i in range(len(chunk_names) - 1):
            chunk_i = semantic_chunks[i]
            chunk_j = semantic_chunks[i + 1]
            if chunk_i.get("category") == chunk_j.get("category") and chunk_i.get("category"):
                try:
                    await graph_store.create_relation(
                        "SemanticChunk", chunk_names[i],
                        "SAME_CATEGORY", "SemanticChunk", chunk_names[i + 1],
                        {"category": chunk_i["category"]},
                    )
                    relation_count += 1
                except Exception as err:
                    logger.warning("创建 SAME_CATEGORY 关系失败", error=str(err))

        logger.info(
            "文档知识图谱构建完成",
            doc_id=doc_id,
            nodes=node_count,
            relations=relation_count,
            entities=len(entity_set),
            chunks=len(semantic_chunks),
        )

        return {
            "nodes": node_count,
            "relations": relation_count,
            "entities": len(entity_set),
        }


# 模块级单例
chunk_graph_service = ChunkGraphService()
