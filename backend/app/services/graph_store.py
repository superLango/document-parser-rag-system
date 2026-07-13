"""Neo4j 知识图谱存储 - 节点/边 CRUD + 子图查询。

按方案 9.3 节实现核心能力：
- 节点创建：MERGE 去重，按 name 唯一约束
- 关系创建：双向 MERGE 节点后 MERGE 关系
- 批量写入：批量节点 + 关系创建
- 子图查询：按实体名查询 N 跳邻居子图
- 节点搜索：按标签/名称模糊检索
- 文档级删除：按 doc_id 清理全部关联节点与关系
- 图统计：节点/关系/标签统计

技术选型：
- Neo4j 5 Enterprise + APOC + Graph Data Science (GDS) 插件
- neo4j Python 驱动原生 async API（AsyncGraphDatabase）
- 单例模式 + 懒加载：模块导入时不连接，首次调用时才建立连接

使用示例：
    from app.services.graph_store import graph_store

    # 创建节点
    node = await graph_store.create_node("Material", {"name": "不锈钢", "type": "材料"})

    # 创建关系
    rel = await graph_store.create_relation(
        "Material", "不锈钢", "执行标准", "Standard", "GB/T 1220"
    )

    # 批量创建
    result = await graph_store.batch_create(nodes, relations)

    # 查询子图
    subgraph = await graph_store.get_subgraph("不锈钢", max_hops=2)
"""

from __future__ import annotations

import re
from typing import Any

from neo4j import AsyncGraphDatabase, AsyncDriver

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# 标签与关系类型合法性校验：仅允许字母、数字、下划线
# 防止 Cypher 注入（标签/关系类型无法参数化，必须拼接进 Cypher 语句）
_LABEL_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class GraphStore:
    """Neo4j 知识图谱存储封装。

    采用单例模式：Neo4j 连接在首次实际调用时建立并复用，
    避免重复连接开销，同时确保模块导入时不依赖 Neo4j 服务可用性。
    所有数据库操作使用 neo4j 原生 async API（AsyncGraphDatabase），
    不阻塞事件循环。

    Attributes:
        _instance: 单例实例。
        _driver: Neo4j 异步驱动，懒加载。
        _connected: 是否已建立连接。
    """

    _instance: GraphStore | None = None
    _driver: AsyncDriver | None = None
    _connected: bool = False

    def __new__(cls) -> GraphStore:
        """单例模式 - Driver 仅创建一次。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化图谱存储封装，不连接 Neo4j（懒加载）。

        连接推迟到首次实际调用 ``create_node`` / ``get_subgraph`` 等方法时，
        确保模块导入时不依赖 Neo4j 服务可用性。单例模式下
        ``__init__`` 仅在首次构造时生效。
        """

    def _ensure_connected(self) -> None:
        """确保已连接 Neo4j（懒加载入口）。"""
        if not self._connected:
            self._connect()

    def _try_connect(self) -> bool:
        """尝试连接 Neo4j，失败时返回 False 而非抛出异常。

        用于读操作（get_graph / search_nodes / get_stats / get_subgraph）
        的优雅降级：Neo4j 不可用时返回空数据，避免 500 错误。
        """
        try:
            self._ensure_connected()
            return True
        except RuntimeError as exc:
            logger.warning("Neo4j 不可用，返回空数据", error=str(exc))
            return False

    def _connect(self) -> None:
        """连接 Neo4j 并创建异步 Driver。

        从配置项读取 Neo4j 连接信息，创建异步驱动实例。
        连接失败时抛出 RuntimeError，由调用方决定重试或降级。

        Raises:
            RuntimeError: Neo4j 连接失败时抛出。
        """
        try:
            self._driver = AsyncGraphDatabase.driver(
                settings.NEO4J_URI,
                auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
            )
        except Exception as exc:  # noqa: BLE001 - 顶层需统一捕获连接类异常
            logger.error(
                "连接 Neo4j 失败，请确认服务已启动",
                uri=settings.NEO4J_URI,
                error=str(exc),
            )
            raise RuntimeError(
                f"无法连接 Neo4j({settings.NEO4J_URI}): {exc}"
            ) from exc

        self._connected = True
        logger.info(
            "已连接 Neo4j",
            uri=settings.NEO4J_URI,
            user=settings.NEO4J_USER,
        )

    @staticmethod
    def _validate_label(label: str) -> str:
        """校验节点标签或关系类型合法性。

        标签/关系类型无法通过参数化方式传入 Cypher（Neo4j 语法限制），
        必须拼接进查询语句，因此需要严格校验以防止 Cypher 注入。
        合法字符：字母、数字、下划线，且不能以数字开头。

        Args:
            label: 待校验的标签或关系类型字符串。

        Returns:
            str: 校验通过的标签字符串。

        Raises:
            ValueError: 标签包含非法字符时抛出。
        """
        if not label or not _LABEL_PATTERN.match(label):
            raise ValueError(f"非法的标签或关系类型: {label!r}")
        return label

    async def create_node(self, label: str, properties: dict) -> dict:
        """创建节点（MERGE 去重）。

        按 name 属性 MERGE 节点，存在则更新属性，不存在则创建。
        使用 MERGE 避免重复创建同名实体。

        Args:
            label: 节点标签（Entity/Document/Standard/Material/...）。
            properties: 节点属性，必须包含 ``name`` 字段，例如：
                ``{"name": "不锈钢", "type": "材料", "doc_id": "doc_001"}``

        Returns:
            dict: 创建的节点信息，包含 id、label 及全部属性。
        """
        self._ensure_connected()
        safe_label = self._validate_label(label)

        query = f"""
        MERGE (n:{safe_label} {{name: $name}})
        SET n += $properties
        RETURN n, id(n) AS node_id
        """

        async with self._driver.session() as session:
            result = await session.run(
                query, name=properties["name"], properties=properties
            )
            record = await result.single()

        logger.info(
            "节点创建/更新完成",
            label=safe_label,
            name=properties.get("name", ""),
        )
        return {"id": record["node_id"], "label": safe_label, **properties}

    async def create_relation(
        self,
        head_label: str,
        head_name: str,
        relation_type: str,
        tail_label: str,
        tail_name: str,
        properties: dict | None = None,
    ) -> dict:
        """创建关系（MERGE 去重）。

        先 MERGE 两端节点，再 MERGE 关系。
        节点和关系均按 MERGE 语义去重。

        Args:
            head_label: 头节点标签。
            head_name: 头节点名称。
            relation_type: 关系类型（如 ``执行标准`` 需转为英文 ``EXECUTES`` 等）。
            tail_label: 尾节点标签。
            tail_name: 尾节点名称。
            properties: 关系属性，可选。

        Returns:
            dict: 创建的关系信息，包含 head、relation、tail。
        """
        self._ensure_connected()
        safe_head_label = self._validate_label(head_label)
        safe_tail_label = self._validate_label(tail_label)
        safe_rel_type = self._validate_label(relation_type)

        query = f"""
        MERGE (h:{safe_head_label} {{name: $head_name}})
        MERGE (t:{safe_tail_label} {{name: $tail_name}})
        MERGE (h)-[r:{safe_rel_type}]->(t)
        SET r += $props
        RETURN h.name AS head, type(r) AS relation, t.name AS tail
        """

        async with self._driver.session() as session:
            result = await session.run(
                query,
                head_name=head_name,
                tail_name=tail_name,
                props=properties or {},
            )
            record = await result.single()

        logger.info(
            "关系创建/更新完成",
            head=head_name,
            relation=safe_rel_type,
            tail=tail_name,
        )
        return {
            "head": record["head"] if record else head_name,
            "relation": safe_rel_type,
            "tail": record["tail"] if record else tail_name,
        }

    async def batch_create(
        self, nodes: list[dict], relations: list[dict]
    ) -> dict:
        """批量创建节点和关系。

        Args:
            nodes: 节点列表，每项格式：
                ``{"label": "Material", "properties": {"name": "不锈钢", "type": "材料"}}``
            relations: 关系列表，每项格式：
                ``{"head_label": "Material", "head_name": "不锈钢",
                   "relation": "执行标准", "tail_label": "Standard",
                   "tail_name": "GB/T 1220", "properties": {...}}``

        Returns:
            dict: 创建统计，包含 ``nodes_created`` 和 ``relations_created``。
        """
        node_count = 0
        for n in nodes:
            await self.create_node(n["label"], n["properties"])
            node_count += 1

        rel_count = 0
        for r in relations:
            await self.create_relation(
                r["head_label"],
                r["head_name"],
                r["relation"],
                r["tail_label"],
                r["tail_name"],
                r.get("properties"),
            )
            rel_count += 1

        logger.info(
            "批量创建完成",
            nodes_created=node_count,
            relations_created=rel_count,
        )
        return {"nodes_created": node_count, "relations_created": rel_count}

    async def get_subgraph(
        self, entity_name: str, max_hops: int = 2
    ) -> dict:
        """获取实体周边子图。

        以指定实体为中心，查询 N 跳范围内的全部节点与关系，
        用于前端知识图谱可视化展示。Neo4j 不可用时返回空子图。

        Args:
            entity_name: 中心实体名称。
            max_hops: 最大跳数，默认 2。

        Returns:
            dict: 子图数据，格式：
                ``{"nodes": [{"id": int, "labels": list, "name": str, "type": str}],
                   "edges": [{"source": str, "target": str, "type": str}]}``
                若实体不存在则返回空子图。
        """
        if not self._try_connect():
            return {"nodes": [], "edges": []}

        # 限制跳数范围，防止全图扫描
        hops = max(1, min(max_hops, 5))

        # 查询节点：UNWIND path 节点后去重收集
        nodes_query = f"""
        MATCH path = (n {{name: $name}})-[*1..{hops}]-(m)
        UNWIND nodes(path) AS node
        RETURN collect(DISTINCT node) AS nodes
        """

        # 查询关系：UNWIND path 关系后关联起止节点名称
        rels_query = f"""
        MATCH path = (n {{name: $name}})-[*1..{hops}]-(m)
        UNWIND relationships(path) AS rel
        WITH DISTINCT rel
        MATCH (a)-[rel]->(b)
        RETURN collect(
            DISTINCT {{source: a.name, target: b.name, type: type(rel)}}
        ) AS rels
        """

        async with self._driver.session() as session:
            # 获取节点
            result = await session.run(nodes_query, name=entity_name)
            record = await result.single()
            nodes_raw = record["nodes"] if record and record["nodes"] else []

            # 获取关系
            result = await session.run(rels_query, name=entity_name)
            record = await result.single()
            rels_raw = record["rels"] if record and record["rels"] else []

        # 转换节点为可序列化字典
        nodes: list[dict] = []
        for n in nodes_raw:
            nodes.append(
                {
                    "id": n.id,
                    "labels": list(n.labels),
                    "name": n.get("name", ""),
                    "type": n.get("type", ""),
                }
            )

        # 关系已为字典格式，直接使用
        edges: list[dict] = list(rels_raw)

        logger.info(
            "子图查询完成",
            entity=entity_name,
            max_hops=hops,
            node_count=len(nodes),
            edge_count=len(edges),
        )
        return {"nodes": nodes, "edges": edges}

    async def search_nodes(
        self, label: str | None = None, name: str | None = None, limit: int = 50
    ) -> list[dict]:
        """搜索节点。

        支持按标签过滤和按名称模糊检索，可组合使用。
        Neo4j 不可用时返回空列表。

        Args:
            label: 节点标签，为 None 时不按标签过滤。
            name: 名称模糊匹配关键词，为 None 时不按名称过滤。
            limit: 返回最大数量，默认 50。

        Returns:
            list[dict]: 匹配的节点列表，每项包含 id、name、labels。
        """
        if not self._try_connect():
            return []

        # 构建查询条件
        query_label = f":{self._validate_label(label)}" if label else ""
        conditions: list[str] = []
        params: dict[str, Any] = {"limit": limit}

        if name:
            conditions.append("n.name CONTAINS $name")
            params["name"] = name

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # 使用标量返回值而非节点对象，便于 data() 序列化
        query = f"""
        MATCH (n{query_label})
        {where}
        RETURN id(n) AS node_id, n.name AS name, labels(n) AS labels
        LIMIT $limit
        """

        async with self._driver.session() as session:
            result = await session.run(query, **params)
            records = await result.data()

        return [
            {
                "id": r["node_id"],
                "name": r["name"] or "",
                "labels": r["labels"],
            }
            for r in records
        ]

    async def delete_by_doc(self, doc_id: str) -> int:
        """删除文档相关的所有节点和关系。

        按 ``doc_id`` 属性匹配节点，使用 DETACH DELETE
        同时删除节点及其所有关联关系。

        Args:
            doc_id: 待删除的文档 ID。

        Returns:
            int: 实际删除的节点数。
        """
        self._ensure_connected()

        query = """
        MATCH (n {doc_id: $doc_id})
        DETACH DELETE n
        RETURN count(n) AS deleted
        """

        async with self._driver.session() as session:
            result = await session.run(query, doc_id=doc_id)
            record = await result.single()

        deleted = record["deleted"] if record else 0
        logger.info("按 doc_id 删除节点完成", doc_id=doc_id, deleted=deleted)
        return deleted

    async def get_stats(self) -> dict:
        """获取图统计信息。

        Neo4j 不可用时返回零值统计。

        Returns:
            dict: 统计信息，包含：
                - ``total_nodes``: 节点总数
                - ``total_relations``: 关系总数
                - ``node_labels``: 全部标签列表
        """
        if not self._try_connect():
            return {"total_nodes": 0, "total_relations": 0, "node_labels": []}

        stats: dict[str, Any] = {}

        async with self._driver.session() as session:
            # 节点总数
            result = await session.run("MATCH (n) RETURN count(n) AS c")
            record = await result.single()
            stats["total_nodes"] = record["c"] if record else 0

            # 关系总数
            result = await session.run("MATCH ()-[r]->() RETURN count(r) AS c")
            record = await result.single()
            stats["total_relations"] = record["c"] if record else 0

            # 全部标签
            result = await session.run(
                "CALL db.labels() YIELD label RETURN collect(label) AS labels"
            )
            record = await result.single()
            stats["node_labels"] = record["labels"] if record else []

        return stats

    async def get_graph(self, limit: int = 50) -> dict:
        """获取全局知识图谱（限制节点数）。

        查询全部节点（按 limit 截断）及其之间的关系，
        用于前端知识图谱页面的初始加载。Neo4j 不可用时返回空图谱。

        Args:
            limit: 最大返回节点数，默认 50。

        Returns:
            dict: 图谱数据，格式与 get_subgraph 一致：
                ``{"nodes": [...], "edges": [...]}``
        """
        if not self._try_connect():
            return {"nodes": [], "edges": []}

        nodes_query = """
        MATCH (n)
        RETURN id(n) AS node_id, n.name AS name, labels(n) AS labels, n.type AS type
        LIMIT $limit
        """

        async with self._driver.session() as session:
            result = await session.run(nodes_query, limit=limit)
            records = await result.data()

            nodes: list[dict] = [
                {
                    "id": r["node_id"],
                    "name": r["name"] or "",
                    "labels": r["labels"],
                    "type": r.get("type", ""),
                }
                for r in records
            ]

            # 查询这些节点之间的关系
            result = await session.run(
                """
                MATCH (a)-[r]->(b)
                WHERE a.name IS NOT NULL AND b.name IS NOT NULL
                RETURN a.name AS source, b.name AS target, type(r) AS rel_type
                LIMIT $limit
                """,
                limit=limit,
            )
            rel_records = await result.data()

        edges: list[dict] = [
            {"source": r["source"], "target": r["target"], "type": r["rel_type"]}
            for r in rel_records
        ]

        logger.info(
            "全局图谱查询完成",
            node_count=len(nodes),
            edge_count=len(edges),
        )
        return {"nodes": nodes, "edges": edges}

    async def close(self) -> None:
        """关闭驱动连接，释放资源。"""
        if self._driver:
            await self._driver.close()
            GraphStore._driver = None
            GraphStore._connected = False
            logger.info("Neo4j 驱动已关闭")


# 模块级单例，懒加载，导入时不连接 Neo4j
graph_store = GraphStore()
