"""Neo4j 知识图谱存储封装测试模块。

测试 GraphStore 的核心功能：
- 懒加载与单例：模块导入不连接，首次调用才建立连接
- 标签合法性校验：防止 Cypher 注入
- 节点创建：MERGE 去重与属性更新
- 关系创建：双向 MERGE 节点与关系
- 批量创建：节点 + 关系批量写入统计
- 子图查询：N 跳邻居节点与关系提取
- 节点搜索：按标签/名称模糊检索
- 文档级删除：按 doc_id 清理
- 图统计：节点/关系/标签计数

测试通过 mock Neo4j AsyncDriver 与 AsyncSession 实现，不依赖真实 Neo4j 服务。
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.graph_store import GraphStore


# ---------------------------------------------------------------
# 公共 fixture 与辅助函数
# ---------------------------------------------------------------
@pytest.fixture(autouse=True)
def reset_singleton():
    """每个测试前后重置单例状态，确保测试间隔离。

    GraphStore 采用类级单例（_instance / _driver / _connected 为类属性），
    测试中需在用例前后清空，避免上一个测试的连接状态影响下一个。
    """
    GraphStore._instance = None
    GraphStore._driver = None
    GraphStore._connected = False
    yield
    GraphStore._instance = None
    GraphStore._driver = None
    GraphStore._connected = False


def make_mock_node(
    node_id: int = 1,
    labels: list[str] | None = None,
    name: str = "",
    type_: str = "",
) -> MagicMock:
    """构造模拟的 Neo4j Node 对象。

    Neo4j Node 对象包含 id（内部 ID）、labels（标签集合）、
    get(key, default)（属性访问）等方法，此处用 MagicMock 模拟。

    Args:
        node_id: 节点内部 ID。
        labels: 标签列表。
        name: 节点 name 属性值。
        type_: 节点 type 属性值。

    Returns:
        MagicMock: 模拟的 Node 对象。
    """
    node = MagicMock()
    node.id = node_id
    node.labels = frozenset(labels or [])
    props = {"name": name, "type": type_}
    node.get = MagicMock(side_effect=lambda key, default="": props.get(key, default))
    return node


def make_mock_result(
    single_value: dict | None = None,
    data_value: list | None = None,
) -> AsyncMock:
    """构造模拟的 Neo4j 结果游标。

    结果游标提供 single()（返回单条记录或 None）和
    data()（返回记录列表）两个核心方法。

    Args:
        single_value: single() 方法的返回值。
        data_value: data() 方法的返回值列表。

    Returns:
        AsyncMock: 模拟的结果游标。
    """
    result = AsyncMock()
    result.single = AsyncMock(return_value=single_value)
    if data_value is not None:
        result.data = AsyncMock(return_value=data_value)
    return result


def make_mock_session(
    run_results: list | None = None,
    run_return: AsyncMock | None = None,
) -> AsyncMock:
    """构造模拟的 Neo4j AsyncSession。

    支持两种模式：
    - run_results: session.run 多次调用返回不同结果（side_effect）
    - run_return: session.run 所有调用返回相同结果（return_value）

    Args:
        run_results: session.run 的 side_effect 列表。
        run_return: session.run 的固定返回值。

    Returns:
        AsyncMock: 模拟的 AsyncSession。
    """
    session = AsyncMock()
    if run_results is not None:
        session.run.side_effect = run_results
    elif run_return is not None:
        session.run.return_value = run_return
    return session


def make_mock_driver(session_mock: AsyncMock) -> MagicMock:
    """构造模拟的 Neo4j AsyncDriver。

    使 ``driver.session()`` 返回的异步上下文管理器 yield 给定的 session_mock，
    模拟 ``async with driver.session() as session:`` 语义。

    Args:
        session_mock: 上下文管理器 yield 的模拟会话。

    Returns:
        MagicMock: 模拟的 AsyncDriver。
    """
    driver = MagicMock()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=session_mock)
    ctx.__aexit__ = AsyncMock(return_value=None)
    driver.session.return_value = ctx
    return driver


def setup_graph_store(session_mock: AsyncMock) -> GraphStore:
    """创建已连接的 GraphStore 实例，注入模拟驱动。

    跳过懒加载连接步骤，直接设置 _driver 和 _connected，
    便于各测试专注于业务逻辑验证。

    Args:
        session_mock: 注入的模拟会话。

    Returns:
        GraphStore: 已配置完成的实例。
    """
    store = GraphStore()
    store._driver = make_mock_driver(session_mock)
    store._connected = True
    return store


# ---------------------------------------------------------------
# 懒加载与单例测试（不连接 Neo4j）
# ---------------------------------------------------------------
class TestLazyLoading:
    """GraphStore 懒加载与单例模式测试。"""

    def test_init_does_not_connect(self):
        """测试 __init__ 不连接 Neo4j。

        构造 GraphStore 后，_connected 应为 False，_driver 应为 None。
        """
        store = GraphStore()

        assert store._connected is False
        assert store._driver is None

    def test_singleton_returns_same_instance(self):
        """测试单例模式返回同一实例。"""
        s1 = GraphStore()
        s2 = GraphStore()

        assert s1 is s2

    def test_ensure_connected_calls_connect(self):
        """测试 _ensure_connected 触发连接。"""
        store = GraphStore()

        with patch.object(GraphStore, "_connect") as mock_connect:
            store._ensure_connected()
            mock_connect.assert_called_once()

    def test_ensure_connected_skipped_when_already_connected(self):
        """测试已连接时 _ensure_connected 不重复连接。"""
        store = GraphStore()
        store._connected = True

        with patch.object(GraphStore, "_connect") as mock_connect:
            store._ensure_connected()
            mock_connect.assert_not_called()


# ---------------------------------------------------------------
# 标签合法性校验测试
# ---------------------------------------------------------------
class TestLabelValidation:
    """_validate_label 标签合法性校验测试。

    防止 Cypher 注入：标签和关系类型拼接进 Cypher 语句前必须校验。
    """

    def test_valid_label(self):
        """测试合法标签通过校验。"""
        assert GraphStore._validate_label("Material") == "Material"
        assert GraphStore._validate_label("Standard") == "Standard"
        assert GraphStore._validate_label("EXECUTES") == "EXECUTES"
        assert GraphStore._validate_label("Entity_1") == "Entity_1"
        assert GraphStore._validate_label("_Private") == "_Private"

    def test_invalid_label_with_special_chars(self):
        """测试含特殊字符的标签被拒绝。"""
        with pytest.raises(ValueError, match="非法的标签"):
            GraphStore._validate_label("Material; DROP")

    def test_invalid_label_with_space(self):
        """测试含空格的标签被拒绝。"""
        with pytest.raises(ValueError, match="非法的标签"):
            GraphStore._validate_label("Bad Label")

    def test_invalid_label_starting_with_digit(self):
        """测试以数字开头的标签被拒绝。"""
        with pytest.raises(ValueError, match="非法的标签"):
            GraphStore._validate_label("1Label")

    def test_empty_label(self):
        """测试空标签被拒绝。"""
        with pytest.raises(ValueError, match="非法的标签"):
            GraphStore._validate_label("")

    def test_invalid_label_injection_attempt(self):
        """测试 Cypher 注入尝试被拒绝。"""
        with pytest.raises(ValueError, match="非法的标签"):
            GraphStore._validate_label("n}) RETURN n //")


# ---------------------------------------------------------------
# 节点创建测试
# ---------------------------------------------------------------
class TestCreateNode:
    """create_node 节点创建测试。"""

    @pytest.mark.asyncio
    async def test_create_node_returns_node_info(self):
        """测试创建节点返回正确的节点信息。"""
        mock_result = make_mock_result(single_value={"node_id": 42})
        session = make_mock_session(run_return=mock_result)
        store = setup_graph_store(session)

        result = await store.create_node(
            "Material", {"name": "不锈钢", "type": "材料", "doc_id": "doc_001"}
        )

        assert result["id"] == 42
        assert result["label"] == "Material"
        assert result["name"] == "不锈钢"
        assert result["type"] == "材料"
        assert result["doc_id"] == "doc_001"

    @pytest.mark.asyncio
    async def test_create_node_calls_session_run(self):
        """测试 create_node 调用 session.run。"""
        mock_result = make_mock_result(single_value={"node_id": 1})
        session = make_mock_session(run_return=mock_result)
        store = setup_graph_store(session)

        await store.create_node("Material", {"name": "碳钢"})

        session.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_node_passes_name_and_properties(self):
        """测试 create_node 正确传递 name 和 properties 参数。"""
        mock_result = make_mock_result(single_value={"node_id": 1})
        session = make_mock_session(run_return=mock_result)
        store = setup_graph_store(session)

        props = {"name": "铝合金", "type": "材料"}
        await store.create_node("Material", props)

        call_kwargs = session.run.call_args.kwargs
        assert call_kwargs["name"] == "铝合金"
        assert call_kwargs["properties"] == props

    @pytest.mark.asyncio
    async def test_create_node_rejects_invalid_label(self):
        """测试 create_node 拒绝非法标签。"""
        store = GraphStore()
        store._connected = True  # 跳过连接检查

        with pytest.raises(ValueError, match="非法的标签"):
            await store.create_node("Bad Label", {"name": "test"})


# ---------------------------------------------------------------
# 关系创建测试
# ---------------------------------------------------------------
class TestCreateRelation:
    """create_relation 关系创建测试。"""

    @pytest.mark.asyncio
    async def test_create_relation_returns_relation_info(self):
        """测试创建关系返回正确的关系信息。"""
        mock_result = make_mock_result(
            single_value={"head": "不锈钢", "relation": "EXECUTES", "tail": "GB/T 1220"}
        )
        session = make_mock_session(run_return=mock_result)
        store = setup_graph_store(session)

        result = await store.create_relation(
            "Material", "不锈钢", "EXECUTES", "Standard", "GB/T 1220"
        )

        assert result["head"] == "不锈钢"
        assert result["relation"] == "EXECUTES"
        assert result["tail"] == "GB/T 1220"

    @pytest.mark.asyncio
    async def test_create_relation_with_properties(self):
        """测试创建关系时传递关系属性。"""
        mock_result = make_mock_result(
            single_value={"head": "A", "relation": "KNOWS", "tail": "B"}
        )
        session = make_mock_session(run_return=mock_result)
        store = setup_graph_store(session)

        await store.create_relation(
            "Entity", "A", "KNOWS", "Entity", "B",
            properties={"weight": 0.9},
        )

        call_kwargs = session.run.call_args.kwargs
        assert call_kwargs["props"] == {"weight": 0.9}

    @pytest.mark.asyncio
    async def test_create_relation_without_properties(self):
        """测试不传关系属性时默认为空字典。"""
        mock_result = make_mock_result(
            single_value={"head": "A", "relation": "KNOWS", "tail": "B"}
        )
        session = make_mock_session(run_return=mock_result)
        store = setup_graph_store(session)

        await store.create_relation("Entity", "A", "KNOWS", "Entity", "B")

        call_kwargs = session.run.call_args.kwargs
        assert call_kwargs["props"] == {}

    @pytest.mark.asyncio
    async def test_create_relation_rejects_invalid_rel_type(self):
        """测试 create_relation 拒绝非法关系类型。"""
        store = GraphStore()
        store._connected = True

        with pytest.raises(ValueError, match="非法的标签"):
            await store.create_relation(
                "Entity", "A", "KNOWS; DROP", "Entity", "B"
            )


# ---------------------------------------------------------------
# 批量创建测试
# ---------------------------------------------------------------
class TestBatchCreate:
    """batch_create 批量创建测试。"""

    @pytest.mark.asyncio
    async def test_batch_create_returns_counts(self):
        """测试批量创建返回正确的创建计数。"""
        # 3 次节点创建返回 node_id，1 次关系创建返回 head/tail
        node_result = make_mock_result(single_value={"node_id": 1})
        rel_result = make_mock_result(
            single_value={"head": "不锈钢", "relation": "EXECUTES", "tail": "GB/T 1220"}
        )
        session = make_mock_session(
            run_results=[node_result, node_result, node_result, rel_result]
        )
        store = setup_graph_store(session)

        nodes = [
            {"label": "Material", "properties": {"name": "不锈钢"}},
            {"label": "Material", "properties": {"name": "碳钢"}},
            {"label": "Standard", "properties": {"name": "GB/T 1220"}},
        ]
        relations = [
            {
                "head_label": "Material",
                "head_name": "不锈钢",
                "relation": "EXECUTES",
                "tail_label": "Standard",
                "tail_name": "GB/T 1220",
            },
        ]

        result = await store.batch_create(nodes, relations)

        assert result["nodes_created"] == 3
        assert result["relations_created"] == 1
        # 3 次节点创建 + 1 次关系创建 = 4 次 session.run
        assert session.run.call_count == 4

    @pytest.mark.asyncio
    async def test_batch_create_empty_lists(self):
        """测试空列表批量创建返回零计数。"""
        mock_result = make_mock_result(single_value={"node_id": 1})
        session = make_mock_session(run_return=mock_result)
        store = setup_graph_store(session)

        result = await store.batch_create([], [])

        assert result["nodes_created"] == 0
        assert result["relations_created"] == 0
        session.run.assert_not_called()


# ---------------------------------------------------------------
# 子图查询测试
# ---------------------------------------------------------------
class TestGetSubgraph:
    """get_subgraph 子图查询测试。"""

    @pytest.mark.asyncio
    async def test_get_subgraph_returns_nodes_and_edges(self):
        """测试子图查询返回正确的节点和边。"""
        # 构造模拟节点
        node1 = make_mock_node(node_id=1, labels=["Material"], name="不锈钢", type_="材料")
        node2 = make_mock_node(node_id=2, labels=["Standard"], name="GB/T 1220", type_="标准")

        # 第一次 run 返回节点，第二次返回关系
        nodes_result = make_mock_result(single_value={"nodes": [node1, node2]})
        rels_result = make_mock_result(
            single_value={
                "rels": [
                    {"source": "不锈钢", "target": "GB/T 1220", "type": "EXECUTES"}
                ]
            }
        )
        session = make_mock_session(run_results=[nodes_result, rels_result])
        store = setup_graph_store(session)

        result = await store.get_subgraph("不锈钢", max_hops=2)

        assert len(result["nodes"]) == 2
        assert result["nodes"][0]["id"] == 1
        assert result["nodes"][0]["name"] == "不锈钢"
        assert "Material" in result["nodes"][0]["labels"]
        assert result["nodes"][1]["name"] == "GB/T 1220"

        assert len(result["edges"]) == 1
        assert result["edges"][0]["source"] == "不锈钢"
        assert result["edges"][0]["target"] == "GB/T 1220"
        assert result["edges"][0]["type"] == "EXECUTES"

    @pytest.mark.asyncio
    async def test_get_subgraph_empty_when_not_found(self):
        """测试实体不存在时返回空子图。"""
        # 实体不存在，两个查询均返回 None
        nodes_result = make_mock_result(single_value=None)
        rels_result = make_mock_result(single_value=None)
        session = make_mock_session(run_results=[nodes_result, rels_result])
        store = setup_graph_store(session)

        result = await store.get_subgraph("不存在的实体")

        assert result["nodes"] == []
        assert result["edges"] == []

    @pytest.mark.asyncio
    async def test_get_subgraph_empty_when_nodes_empty(self):
        """测试查询返回空列表时返回空子图。"""
        nodes_result = make_mock_result(single_value={"nodes": []})
        rels_result = make_mock_result(single_value={"rels": []})
        session = make_mock_session(run_results=[nodes_result, rels_result])
        store = setup_graph_store(session)

        result = await store.get_subgraph("孤立实体")

        assert result["nodes"] == []
        assert result["edges"] == []

    @pytest.mark.asyncio
    async def test_get_subgraph_max_hops_clamped(self):
        """测试 max_hops 超过上限时被限制为 5。"""
        nodes_result = make_mock_result(single_value={"nodes": []})
        rels_result = make_mock_result(single_value={"rels": []})
        session = make_mock_session(run_results=[nodes_result, rels_result])
        store = setup_graph_store(session)

        await store.get_subgraph("实体", max_hops=100)

        # 验证查询语句中的跳数被限制为 5
        first_call_args = session.run.call_args_list[0]
        query_text = first_call_args.args[0]
        assert "[*1..5]" in query_text

    @pytest.mark.asyncio
    async def test_get_subgraph_max_hops_minimum_one(self):
        """测试 max_hops 小于 1 时被限制为 1。"""
        nodes_result = make_mock_result(single_value={"nodes": []})
        rels_result = make_mock_result(single_value={"rels": []})
        session = make_mock_session(run_results=[nodes_result, rels_result])
        store = setup_graph_store(session)

        await store.get_subgraph("实体", max_hops=0)

        first_call_args = session.run.call_args_list[0]
        query_text = first_call_args.args[0]
        assert "[*1..1]" in query_text


# ---------------------------------------------------------------
# 节点搜索测试
# ---------------------------------------------------------------
class TestSearchNodes:
    """search_nodes 节点搜索测试。"""

    @pytest.mark.asyncio
    async def test_search_nodes_no_filter(self):
        """测试无过滤条件时返回全部节点（受 limit 限制）。"""
        mock_data = [
            {"node_id": 1, "name": "不锈钢", "labels": ["Material"]},
            {"node_id": 2, "name": "碳钢", "labels": ["Material"]},
        ]
        mock_result = make_mock_result(data_value=mock_data)
        session = make_mock_session(run_return=mock_result)
        store = setup_graph_store(session)

        results = await store.search_nodes()

        assert len(results) == 2
        assert results[0]["id"] == 1
        assert results[0]["name"] == "不锈钢"
        assert results[0]["labels"] == ["Material"]

    @pytest.mark.asyncio
    async def test_search_nodes_by_label(self):
        """测试按标签过滤节点。"""
        mock_data = [{"node_id": 1, "name": "不锈钢", "labels": ["Material"]}]
        mock_result = make_mock_result(data_value=mock_data)
        session = make_mock_session(run_return=mock_result)
        store = setup_graph_store(session)

        results = await store.search_nodes(label="Material")

        # 验证查询语句包含标签
        query_text = session.run.call_args.args[0]
        assert ":Material" in query_text
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_nodes_by_name(self):
        """测试按名称模糊检索节点。"""
        mock_data = [{"node_id": 1, "name": "不锈钢板", "labels": ["Material"]}]
        mock_result = make_mock_result(data_value=mock_data)
        session = make_mock_session(run_return=mock_result)
        store = setup_graph_store(session)

        results = await store.search_nodes(name="不锈钢")

        # 验证查询参数包含 name
        call_kwargs = session.run.call_args.kwargs
        assert call_kwargs["name"] == "不锈钢"
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_nodes_by_label_and_name(self):
        """测试同时按标签和名称过滤。"""
        mock_data = [{"node_id": 1, "name": "不锈钢", "labels": ["Material"]}]
        mock_result = make_mock_result(data_value=mock_data)
        session = make_mock_session(run_return=mock_result)
        store = setup_graph_store(session)

        results = await store.search_nodes(label="Material", name="不锈钢")

        query_text = session.run.call_args.args[0]
        assert ":Material" in query_text
        assert "CONTAINS" in query_text
        call_kwargs = session.run.call_args.kwargs
        assert call_kwargs["name"] == "不锈钢"

    @pytest.mark.asyncio
    async def test_search_nodes_limit_param(self):
        """测试 limit 参数传递正确。"""
        mock_result = make_mock_result(data_value=[])
        session = make_mock_session(run_return=mock_result)
        store = setup_graph_store(session)

        await store.search_nodes(limit=10)

        call_kwargs = session.run.call_args.kwargs
        assert call_kwargs["limit"] == 10

    @pytest.mark.asyncio
    async def test_search_nodes_empty_result(self):
        """测试搜索无结果时返回空列表。"""
        mock_result = make_mock_result(data_value=[])
        session = make_mock_session(run_return=mock_result)
        store = setup_graph_store(session)

        results = await store.search_nodes(name="不存在的")

        assert results == []


# ---------------------------------------------------------------
# 文档级删除测试
# ---------------------------------------------------------------
class TestDeleteByDoc:
    """delete_by_doc 文档级删除测试。"""

    @pytest.mark.asyncio
    async def test_delete_by_doc_returns_count(self):
        """测试删除返回实际删除的节点数。"""
        mock_result = make_mock_result(single_value={"deleted": 5})
        session = make_mock_session(run_return=mock_result)
        store = setup_graph_store(session)

        deleted = await store.delete_by_doc("doc_001")

        assert deleted == 5

    @pytest.mark.asyncio
    async def test_delete_by_doc_passes_doc_id(self):
        """测试删除操作传递正确的 doc_id 参数。"""
        mock_result = make_mock_result(single_value={"deleted": 1})
        session = make_mock_session(run_return=mock_result)
        store = setup_graph_store(session)

        await store.delete_by_doc("target_doc")

        call_kwargs = session.run.call_args.kwargs
        assert call_kwargs["doc_id"] == "target_doc"

    @pytest.mark.asyncio
    async def test_delete_by_doc_returns_zero_when_not_found(self):
        """测试文档不存在时返回 0。"""
        mock_result = make_mock_result(single_value={"deleted": 0})
        session = make_mock_session(run_return=mock_result)
        store = setup_graph_store(session)

        deleted = await store.delete_by_doc("nonexistent")

        assert deleted == 0

    @pytest.mark.asyncio
    async def test_delete_by_doc_returns_zero_when_record_none(self):
        """测试查询返回 None 时返回 0。"""
        mock_result = make_mock_result(single_value=None)
        session = make_mock_session(run_return=mock_result)
        store = setup_graph_store(session)

        deleted = await store.delete_by_doc("empty")

        assert deleted == 0


# ---------------------------------------------------------------
# 图统计测试
# ---------------------------------------------------------------
class TestGetStats:
    """get_stats 图统计信息测试。"""

    @pytest.mark.asyncio
    async def test_get_stats_returns_all_counts(self):
        """测试返回完整的统计信息。"""
        result1 = make_mock_result(single_value={"c": 100})
        result2 = make_mock_result(single_value={"c": 250})
        result3 = make_mock_result(single_value={"labels": ["Material", "Standard", "Document"]})
        session = make_mock_session(run_results=[result1, result2, result3])
        store = setup_graph_store(session)

        stats = await store.get_stats()

        assert stats["total_nodes"] == 100
        assert stats["total_relations"] == 250
        assert "Material" in stats["node_labels"]
        assert "Standard" in stats["node_labels"]
        assert "Document" in stats["node_labels"]

    @pytest.mark.asyncio
    async def test_get_stats_zero_on_empty_graph(self):
        """测试空图返回零统计。"""
        result1 = make_mock_result(single_value={"c": 0})
        result2 = make_mock_result(single_value={"c": 0})
        result3 = make_mock_result(single_value={"labels": []})
        session = make_mock_session(run_results=[result1, result2, result3])
        store = setup_graph_store(session)

        stats = await store.get_stats()

        assert stats["total_nodes"] == 0
        assert stats["total_relations"] == 0
        assert stats["node_labels"] == []

    @pytest.mark.asyncio
    async def test_get_stats_zero_when_records_none(self):
        """测试查询返回 None 时统计为零/空。"""
        result1 = make_mock_result(single_value=None)
        result2 = make_mock_result(single_value=None)
        result3 = make_mock_result(single_value=None)
        session = make_mock_session(run_results=[result1, result2, result3])
        store = setup_graph_store(session)

        stats = await store.get_stats()

        assert stats["total_nodes"] == 0
        assert stats["total_relations"] == 0
        assert stats["node_labels"] == []

    @pytest.mark.asyncio
    async def test_get_stats_calls_run_three_times(self):
        """测试 get_stats 调用三次 session.run。"""
        # 三次调用分别返回节点数、关系数、标签列表
        result1 = make_mock_result(single_value={"c": 10})
        result2 = make_mock_result(single_value={"c": 20})
        result3 = make_mock_result(single_value={"labels": ["Material"]})
        session = make_mock_session(run_results=[result1, result2, result3])
        store = setup_graph_store(session)

        await store.get_stats()

        assert session.run.call_count == 3


# ---------------------------------------------------------------
# 驱动关闭测试
# ---------------------------------------------------------------
class TestClose:
    """close 驱动关闭测试。"""

    @pytest.mark.asyncio
    async def test_close_calls_driver_close(self):
        """测试 close 调用 driver.close()。"""
        store = GraphStore()
        mock_driver = MagicMock()
        mock_driver.close = AsyncMock()
        store._driver = mock_driver
        store._connected = True

        await store.close()

        mock_driver.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_resets_state(self):
        """测试 close 重置连接状态。"""
        store = GraphStore()
        mock_driver = MagicMock()
        mock_driver.close = AsyncMock()
        store._driver = mock_driver
        store._connected = True

        await store.close()

        assert GraphStore._driver is None
        assert GraphStore._connected is False

    @pytest.mark.asyncio
    async def test_close_noop_when_driver_none(self):
        """测试无驱动时 close 不报错。"""
        store = GraphStore()
        store._driver = None
        store._connected = False

        # 不应抛出异常
        await store.close()

        assert GraphStore._driver is None
        assert GraphStore._connected is False


# ---------------------------------------------------------------
# 连接错误处理测试
# ---------------------------------------------------------------
class TestConnectionError:
    """连接错误处理测试。"""

    def test_connect_raises_runtime_error_on_failure(self):
        """测试 Neo4j 连接失败时抛出 RuntimeError。"""
        store = GraphStore()

        with patch(
            "app.services.graph_store.AsyncGraphDatabase.driver",
            side_effect=ConnectionError("Connection refused"),
        ):
            with pytest.raises(RuntimeError, match="无法连接 Neo4j"):
                store._connect()

        assert store._connected is False

    def test_ensure_connected_propagates_connection_error(self):
        """测试 _ensure_connected 传播连接错误。"""
        store = GraphStore()

        with patch.object(GraphStore, "_connect") as mock_connect:
            mock_connect.side_effect = RuntimeError("无法连接 Neo4j")
            with pytest.raises(RuntimeError, match="无法连接 Neo4j"):
                store._ensure_connected()
