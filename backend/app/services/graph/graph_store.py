"""NebulaGraph 知识图谱存储 - 节点/边 CRUD + 子图查询 + 按 KB 分 space。

按方案 §9.2/§9.3 实现核心能力（替代原 Neo4j 实现）：

引擎迁移（Neo4j → NebulaGraph）：
    - 开源 Apache 2.0，原生多 graph space 物理隔离，无需 Enterprise 授权
    - 每 KB 一个 graph space（``kb_{kb_id_hex}``），独立 schema 与数据
    - Cypher → nGQL
    - neo4j 驱动 → nebula-python（ConnectionPool + Session）

知识库隔离（方案 §9.2 第 3 层）：
    - ``kb_id`` 为 None：使用全局 space（``settings.NEBULA_GLOBAL_SPACE``，向后兼容）
    - ``kb_id`` 不为 None：使用 KB 专属 space（``{prefix}{kb_id_hex}``）
    - ``create_kb_space`` / ``drop_kb_space`` 供 kb_lifecycle 调用

Schema 设计（每 space 统一）：
    - TAG ``Entity(name string, type string, doc_id string, label string)``
      用 ``label`` 属性承载原 Neo4j 动态标签（Material/Standard/Document/...）
    - EDGE ``RELATES(rel_type string, doc_id string)``
      用 ``rel_type`` 属性承载原 Neo4j 动态关系类型
    - VID = ``md5(f"{label}:{name}")`` 十六进制（确定性，INSERT VERTEX 天然 upsert）
    - 索引：``idx_entity_name``（name）、``idx_entity_doc``（doc_id）、``idx_entity_label``（label）

优雅降级：
    - NebulaGraph 服务不可用时，读操作返回空数据，写操作记录 WARNING
    - 避免因图服务不可用导致主流程 500

使用示例：
    from app.services.graph.graph_store import graph_store

    # 创建节点（指定 KB）
    node = await graph_store.create_node("Material", {"name": "不锈钢", "type": "材料"}, kb_id=kb_id)

    # 批量创建
    result = await graph_store.batch_create(nodes, relations, kb_id=kb_id)

    # 查询子图
    subgraph = await graph_store.get_subgraph("不锈钢", max_hops=2, kb_id=kb_id)
"""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)

# 标签与关系类型合法性校验：仅允许字母、数字、下划线
# NebulaGraph TAG/EDGE 名必须符合标识符规范，且此处拼接进 nGQL 需防注入
_LABEL_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# 每 space 统一的 TAG/EDGE 名
_ENTITY_TAG = "Entity"
_RELATES_EDGE = "RELATES"


def _vid(label: str, name: str) -> str:
    """生成确定性 VID（md5(label:name) 十六进制）。

    INSERT VERTEX 按 VID upsert，实现 MERGE 去重语义。
    """
    return hashlib.md5(f"{label}:{name}".encode("utf-8")).hexdigest()


def _nql_escape(value: str) -> str:
    """转义 nGQL 字符串字面量中的单引号（双写法）。"""
    if value is None:
        return ""
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


def _space_name(kb_id) -> str:
    """根据 kb_id 解析 graph space 名。

    - ``kb_id`` 为 None：全局 space（向后兼容）。
    - ``kb_id`` 不为 None：``{prefix}{kb_id_hex}``。
    兼容 UUID 对象和字符串两种输入。
    """
    if kb_id is None:
        return settings.NEBULA_GLOBAL_SPACE
    # 兼容 UUID 对象和字符串
    import uuid as _uuid
    if isinstance(kb_id, str):
        try:
            kb_id = _uuid.UUID(kb_id)
        except (ValueError, AttributeError):
            # 非UUID字符串时，取hash作为hex后缀（兼容旧数据）
            return f"{settings.NEBULA_SPACE_PREFIX}{kb_id.replace('-', '')}"
    return f"{settings.NEBULA_SPACE_PREFIX}{kb_id.hex}"


class GraphStore:
    """NebulaGraph 知识图谱存储封装。

    采用单例模式：ConnectionPool 在首次实际调用时建立并复用。
    每次操作从池中借出 Session，执行 nGQL 后归还。
    模块导入时不连接 NebulaGraph，确保不依赖服务可用性。

    Attributes:
        _instance: 单例实例。
        _pool: NebulaGraph ConnectionPool，懒加载。
        _connected: 是否已建立连接池。
    """

    _instance: GraphStore | None = None
    _pool: Any = None
    _connected: bool = False
    # 已初始化 schema 的 space 集合，避免重复建表
    _schema_initialized: set[str] = set()

    def __new__(cls) -> GraphStore:
        """单例模式 - ConnectionPool 仅创建一次。"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化图谱存储封装，不连接 NebulaGraph（懒加载）。"""

    # ============================================================
    # 连接管理
    # ============================================================
    def _ensure_connected(self) -> None:
        """确保已建立 NebulaGraph 连接池（懒加载入口）。"""
        if not self._connected:
            self._connect()

    def _try_connect(self) -> bool:
        """尝试连接 NebulaGraph，失败时返回 False 而非抛出异常。

        用于读操作的优雅降级：服务不可用时返回空数据，避免 500 错误。
        """
        try:
            self._ensure_connected()
            return True
        except RuntimeError as exc:
            logger.warning("NebulaGraph 不可用，返回空数据", error=str(exc))
            return False

    def _connect(self) -> None:
        """建立 NebulaGraph ConnectionPool。

        Raises:
            RuntimeError: 连接池初始化失败时抛出。
        """
        try:
            from nebula3.gclient.net import ConnectionPool
            from nebula3.Config import Config as NConfig
        except ImportError as exc:
            raise RuntimeError(
                "nebula3-python 未安装，无法连接 NebulaGraph。"
                "请执行 pip install nebula3-python"
            ) from exc

        nconfig = NConfig()
        nconfig.max_connection_pool_size = 10
        nconfig.timeout = 30000  # ms，LOOKUP/DELETE 等操作可能较慢

        pool = ConnectionPool()
        ok = pool.init(
            [(settings.NEBULA_GRAPHD_HOST, settings.NEBULA_GRAPHD_PORT)],
            nconfig,
        )
        if not ok:
            raise RuntimeError(
                f"NebulaGraph 连接池初始化失败: {settings.NEBULA_GRAPHD_HOST}:{settings.NEBULA_GRAPHD_PORT}"
            )

        # 验证连接有效性
        try:
            session = pool.get_session(
                settings.NEBULA_USER, settings.NEBULA_PASSWORD
            )
            session.release()
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"NebulaGraph 认证失败({settings.NEBULA_USER}): {exc}"
            ) from exc

        GraphStore._pool = pool
        GraphStore._connected = True
        logger.info(
            "已连接 NebulaGraph",
            host=settings.NEBULA_GRAPHD_HOST,
            port=settings.NEBULA_GRAPHD_PORT,
            user=settings.NEBULA_USER,
        )

    def _get_session(self) -> Any:
        """从连接池借出一个 Session（调用方负责 release）。"""
        self._ensure_connected()
        return self._pool.get_session(settings.NEBULA_USER, settings.NEBULA_PASSWORD)

    @staticmethod
    def _validate_label(label: str) -> str:
        """校验节点标签或关系类型非空。

        实体类型（如"材质"、"材料"）存储为 Entity.label/RELATES.rel_type
        字符串属性，支持中文等Unicode字符。TAG/EDGE名固定为 Entity/RELATES。
        """
        if not label or not str(label).strip():
            raise ValueError(f"标签或关系类型不能为空: {label!r}")
        return str(label).strip()

    # ============================================================
    # Schema 初始化（每 space 一次）
    # ============================================================
    def _ensure_schema(self, space: str) -> None:
        """确保指定 space 已创建并初始化 schema（幂等）。

        若 space 不存在则创建；若 schema 未初始化则建 TAG/EDGE/索引。
        """
        if space in self._schema_initialized:
            return
        self._ensure_connected()

        session = self._get_session()
        try:
            # 1. 创建 space（若不存在）。vid_type=FIXED_STRING(64) 容纳 md5 hex(32)
            create_space_nql = (
                f"CREATE SPACE IF NOT EXISTS `{space}` "
                f"(vid_type=FIXED_STRING(64), partition_num=10, replica_factor=1);"
            )
            self._exec(session, create_space_nql)
            # 等待 space 生效：CREATE SPACE 是异步操作，需轮询直到 USE 成功
            # 生产级保护：最多等待 10 秒（20 × 0.5s），超时抛出明确异常
            import time
            use_ok = False
            for attempt in range(20):
                resp = session.execute(f"USE `{space}`;")
                if resp.is_succeeded():
                    use_ok = True
                    break
                time.sleep(0.5)
            if not use_ok:
                last_err = resp.error_msg() if resp else "unknown"
                raise RuntimeError(
                    f"Space `{space}` 创建后等待生效超时（10s）: {last_err}"
                )
            if attempt > 0:
                logger.info("Space 等待生效完成", space=space, attempts=attempt + 1)

            # 2. 建 TAG / EDGE / 索引（IF NOT EXISTS 幂等）
            self._exec(
                session,
                f"CREATE TAG IF NOT EXISTS {_ENTITY_TAG}"
                f"(name string, type string, doc_id string, label string);",
            )
            self._exec(
                session,
                f"CREATE EDGE IF NOT EXISTS {_RELATES_EDGE}"
                f"(rel_type string, doc_id string);",
            )
            # NebulaGraph DDL 异步生效：必须显式 USE space 后轮询 DESC TAG
            # DROP SPACE 后重建时同步延迟更长；
            # DESC TAG 在 graphd 层成功不代表 storaged 已同步（会导致 INSERT 报
            # "No schema found" 或属性读取返回 NULL），因此需要更长等待 + INSERT 轮询验证
            import time
            time.sleep(5.0)
            tag_ready = False
            for _ in range(30):
                resp = session.execute(f"USE `{space}`; DESC TAG {_ENTITY_TAG};")
                if resp.is_succeeded():
                    tag_ready = True
                    break
                time.sleep(1.0)
            if not tag_ready:
                logger.warning("TAG Entity DESC 等待超时", space=space)
                time.sleep(5.0)
            # DESC 成功后再等待 schema 同步到 storaged（心跳间隔默认 10s），并用实际 INSERT 验证
            if tag_ready:
                time.sleep(8.0)
                for _ in range(5):
                    verify = session.execute(
                        f'USE `{space}`; INSERT VERTEX {_ENTITY_TAG}(name) '
                        f'VALUES "_schema_probe":("_probe");'
                    )
                    if verify.is_succeeded():
                        # 验证INSERT后能用正确语法读回属性
                        check = session.execute(
                            f'USE `{space}`; FETCH PROP ON {_ENTITY_TAG} "_schema_probe" '
                            f'YIELD {_ENTITY_TAG}.name AS n;'
                        )
                        if check.is_succeeded() and check.rows():
                            val = check.rows()[0].values[0]
                            try:
                                if val.get_sVal().decode() == "_probe":
                                    logger.info("schema 同步验证通过", space=space)
                                    break
                            except Exception:
                                pass
                    time.sleep(2.0)

            self._exec(
                session,
                f"CREATE TAG INDEX IF NOT EXISTS idx_entity_name "
                f"ON {_ENTITY_TAG}(name(64));",
            )
            self._exec(
                session,
                f"CREATE TAG INDEX IF NOT EXISTS idx_entity_doc "
                f"ON {_ENTITY_TAG}(doc_id(64));",
            )
            self._exec(
                session,
                f"CREATE TAG INDEX IF NOT EXISTS idx_entity_label "
                f"ON {_ENTITY_TAG}(label(64));",
            )
            # 等待索引生效后重建（幂等）
            time.sleep(1.0)
            try:
                self._exec(session, f"REBUILD TAG INDEX idx_entity_name;")
                self._exec(session, f"REBUILD TAG INDEX idx_entity_doc;")
                self._exec(session, f"REBUILD TAG INDEX idx_entity_label;")
            except Exception as err:  # noqa: BLE001
                logger.debug("索引重建提交（可能进行中）", space=space, error=str(err))

            GraphStore._schema_initialized.add(space)
            logger.info("NebulaGraph space schema 已初始化", space=space)
        finally:
            session.release()

    @staticmethod
    def _exec(session: Any, nql: str) -> Any:
        """执行 nGQL 并返回 ResultSet；失败时抛 RuntimeError。"""
        resp = session.execute(nql)
        if not resp.is_succeeded():
            raise RuntimeError(
                f"nGQL 执行失败: {resp.error_msg()} | nql={nql[:200]}"
            )
        return resp

    # ============================================================
    # KB 生命周期（供 kb_lifecycle 调用）
    # ============================================================
    async def create_kb_space(self, kb_id: uuid.UUID) -> None:
        """创建 KB 专属 graph space 并初始化 schema（幂等）。

        NebulaGraph 不可用时优雅降级：记录警告并返回，不抛异常。
        KB 创建流程的其他步骤（Milvus/MinIO/Redis）不受影响，
        后续图谱读写时若服务恢复会自动创建 schema。
        """
        space = _space_name(kb_id)
        if not self._try_connect():
            logger.warning(
                "NebulaGraph 不可用，跳过 KB graph space 创建（优雅降级）",
                kb_id=str(kb_id), space=space,
            )
            return
        self._ensure_schema(space)
        logger.info("KB graph space 已就绪", kb_id=str(kb_id), space=space)

    async def drop_kb_space(self, kb_id: uuid.UUID) -> None:
        """删除 KB 专属 graph space（合规销毁，幂等）。

        NebulaGraph 不可用时优雅降级：记录警告并返回，不抛异常。
        """
        space = _space_name(kb_id)
        if not self._try_connect():
            logger.warning(
                "NebulaGraph 不可用，跳过 KB graph space 删除（优雅降级）",
                kb_id=str(kb_id), space=space,
            )
            return
        session = self._get_session()
        try:
            try:
                self._exec(session, f"DROP SPACE IF EXISTS `{space}`;")
            except RuntimeError as err:
                logger.warning("KB graph space 删除失败", space=space, error=str(err))
            GraphStore._schema_initialized.discard(space)
            logger.warning("KB graph space 已删除", kb_id=str(kb_id), space=space)
        finally:
            session.release()

    async def verify_kb_space(self, kb_id: uuid.UUID) -> dict:
        """校验 KB 专属 graph space 是否存在。"""
        space = _space_name(kb_id)
        if not self._try_connect():
            return {"space": space, "status": "nebula_unavailable"}
        session = self._get_session()
        try:
            resp = session.execute("SHOW SPACES;")
            spaces = []
            if resp.is_succeeded():
                for row in resp.rows():
                    for v in row.values:
                        try:
                            spaces.append(v.get_sVal().decode())
                        except Exception:  # noqa: BLE001
                            pass
            exists = space in spaces
            return {"space": space, "status": "exists" if exists else "missing"}
        finally:
            session.release()

    # ============================================================
    # 节点/边 CRUD
    # ============================================================
    async def create_node(
        self, label: str, properties: dict, kb_id=None
    ) -> dict:
        """创建节点（INSERT VERTEX upsert 去重）。

        Args:
            label: 节点标签（存为 Entity.label 属性）。
            properties: 节点属性，必须包含 ``name``，可含 ``type``、``doc_id``。
            kb_id: 知识库 ID。None 时写入全局 space（向后兼容）。

        Returns:
            dict: 节点信息，含 vid、label 及属性。
        """
        safe_label = self._validate_label(label)
        name = properties.get("name", "")
        if not name:
            raise ValueError("properties 必须包含非空 name 字段")

        # NebulaGraph 不可用时优雅降级：记录警告并返回空结果，不阻断主流程
        if not self._try_connect():
            logger.warning(
                "NebulaGraph 不可用，跳过节点创建",
                label=safe_label, name=name,
            )
            return {"id": "", "label": safe_label, **properties, "_skipped": True}

        space = _space_name(kb_id)
        self._ensure_schema(space)
        vid = _vid(safe_label, name)
        ntype = _nql_escape(properties.get("type", ""))
        doc_id = _nql_escape(properties.get("doc_id", ""))
        name_esc = _nql_escape(name)
        label_esc = _nql_escape(safe_label)

        nql = (
            f'USE `{space}`; INSERT VERTEX {_ENTITY_TAG}'
            f'(name, type, doc_id, label) VALUES '
            f'"{vid}":("{name_esc}","{ntype}","{doc_id}","{label_esc}");'
        )
        session = self._get_session()
        try:
            self._exec(session, nql)
        finally:
            session.release()

        logger.info("节点创建/更新完成", label=safe_label, name=name, space=space)
        return {"id": vid, "label": safe_label, **properties}

    async def create_relation(
        self,
        head_label: str,
        head_name: str,
        relation_type: str,
        tail_label: str,
        tail_name: str,
        properties: dict | None = None,
        kb_id=None,
    ) -> dict:
        """创建关系（先 upsert 两端节点，再 upsert 边）。

        Args:
            head_label: 头节点标签。
            head_name: 头节点名称。
            relation_type: 关系类型（存为 RELATES.rel_type）。
            tail_label: 尾节点标签。
            tail_name: 尾节点名称。
            properties: 关系属性，可含 ``doc_id``。
            kb_id: 知识库 ID。None 时写入全局 space。

        Returns:
            dict: 关系信息。
        """
        safe_head_label = self._validate_label(head_label)
        safe_tail_label = self._validate_label(tail_label)
        safe_rel_type = self._validate_label(relation_type)

        props = properties or {}

        # NebulaGraph 不可用时优雅降级
        if not self._try_connect():
            logger.warning(
                "NebulaGraph 不可用，跳过关系创建",
                head=head_name, relation=safe_rel_type, tail=tail_name,
            )
            return {
                "head": head_name,
                "relation": safe_rel_type,
                "tail": tail_name,
                "_skipped": True,
            }

        space = _space_name(kb_id)
        self._ensure_schema(space)

        head_vid = _vid(safe_head_label, head_name)
        tail_vid = _vid(safe_tail_label, tail_name)
        rel_doc = _nql_escape(props.get("doc_id", ""))
        head_label_esc = _nql_escape(safe_head_label)
        tail_label_esc = _nql_escape(safe_tail_label)
        rel_type_esc = _nql_escape(safe_rel_type)

        nql = (
            f'USE `{space}`; '
            f'INSERT VERTEX {_ENTITY_TAG}(name, type, doc_id, label) VALUES '
            f'"{head_vid}":("{_nql_escape(head_name)}","","","{head_label_esc}"),'
            f'"{tail_vid}":("{_nql_escape(tail_name)}","","","{tail_label_esc}"); '
            f'INSERT EDGE {_RELATES_EDGE}(rel_type, doc_id) VALUES '
            f'"{head_vid}"->"{tail_vid}":("{rel_type_esc}","{rel_doc}");'
        )
        session = self._get_session()
        try:
            self._exec(session, nql)
        finally:
            session.release()

        logger.info(
            "关系创建/更新完成",
            head=head_name, relation=safe_rel_type, tail=tail_name, space=space,
        )
        return {"head": head_name, "relation": safe_rel_type, "tail": tail_name}

    async def batch_create(
        self,
        nodes: list[dict],
        relations: list[dict],
        kb_id=None,
    ) -> dict:
        """批量创建节点和关系。

        Args:
            nodes: 节点列表，每项 ``{"label": str, "properties": {...}}``。
            relations: 关系列表，每项含 head_label/head_name/relation/
                tail_label/tail_name/properties。
            kb_id: 知识库 ID。None 时写入全局 space。

        Returns:
            dict: 创建统计。
        """
        space = _space_name(kb_id)

        # NebulaGraph 不可用时优雅降级：返回零统计，不阻断解析流程
        if not self._try_connect():
            logger.warning(
                "NebulaGraph 不可用，跳过批量创建",
                space=space,
                nodes=len(nodes), relations=len(relations),
            )
            return {
                "nodes_created": 0,
                "relations_created": 0,
                "_skipped": True,
            }

        self._ensure_schema(space)

        node_count = 0
        rel_count = 0
        session = self._get_session()
        try:
            # 批量插入节点
            if nodes:
                vertex_values: list[str] = []
                for n in nodes:
                    label = self._validate_label(n["label"])
                    props = n["properties"]
                    name = props.get("name", "")
                    if not name:
                        continue
                    vid = _vid(label, name)
                    vertex_values.append(
                        f'"{vid}":("{_nql_escape(name)}",'
                        f'"{_nql_escape(props.get("type", ""))}",'
                        f'"{_nql_escape(props.get("doc_id", ""))}",'
                        f'"{_nql_escape(label)}")'
                    )
                    node_count += 1
                if vertex_values:
                    nql = (
                        f'USE `{space}`; INSERT VERTEX {_ENTITY_TAG}'
                        f'(name, type, doc_id, label) VALUES '
                        f'{",".join(vertex_values)};'
                    )
                    self._exec(session, nql)

            # 批量插入边
            if relations:
                edge_values: list[str] = []
                for r in relations:
                    hl = self._validate_label(r["head_label"])
                    tl = self._validate_label(r["tail_label"])
                    rt = self._validate_label(r["relation"])
                    hvid = _vid(hl, r["head_name"])
                    tvid = _vid(tl, r["tail_name"])
                    rdoc = _nql_escape((r.get("properties") or {}).get("doc_id", ""))
                    edge_values.append(
                        f'"{hvid}"->"{tvid}":("{_nql_escape(rt)}","{rdoc}")'
                    )
                    rel_count += 1
                if edge_values:
                    nql = (
                        f'USE `{space}`; INSERT EDGE {_RELATES_EDGE}'
                        f'(rel_type, doc_id) VALUES '
                        f'{",".join(edge_values)};'
                    )
                    self._exec(session, nql)
        finally:
            session.release()

        logger.info(
            "批量创建完成",
            nodes_created=node_count, relations_created=rel_count, space=space,
        )
        return {"nodes_created": node_count, "relations_created": rel_count}

    # ============================================================
    # 查询接口
    # ============================================================
    async def get_subgraph(
        self, entity_name: str, max_hops: int = 2, kb_id=None
    ) -> dict:
        """获取实体周边子图（GET SUBGRAPH）。

        Args:
            entity_name: 中心实体名称。
            max_hops: 最大跳数，默认 2（限制 1-5）。
            kb_id: 知识库 ID。None 时查询全局 space。

        Returns:
            dict: ``{"nodes": [...], "edges": [...]}``，服务不可用时返回空子图。
        """
        if not self._try_connect():
            return {"nodes": [], "edges": []}

        hops = max(1, min(max_hops, 5))
        space = _space_name(kb_id)
        self._ensure_schema(space)

        # 中心实体 VID 难以从 name 反推（label 未知），用 name 索引查找
        session = self._get_session()
        try:
            # 先查中心节点 vid
            lookup_nql = (
                f'USE `{space}`; LOOKUP ON {_ENTITY_TAG} '
                f'WHERE {_ENTITY_TAG}.name == "{_nql_escape(entity_name)}" '
                f'YIELD id(vertex) AS vid, {_ENTITY_TAG}.name AS name, '
                f'{_ENTITY_TAG}.label AS label, {_ENTITY_TAG}.type AS type;'
            )
            resp = session.execute(lookup_nql)
            if not resp.is_succeeded() or not resp.rows():
                return {"nodes": [], "edges": []}

            center_vid = self._cell_str(resp.rows()[0].values[0])
            center_node = self._row_to_node(resp.rows()[0], None)

            # GET SUBGRAPH 取 N 跳子图
            sub_nql = (
                f'USE `{space}`; GET SUBGRAPH {hops} STEPS FROM "{center_vid}" '
                f'BOTH {_RELATES_EDGE} YIELD VERTICES AS nodes, EDGES AS edges;'
            )
            resp = session.execute(sub_nql)

            nodes: list[dict] = [center_node]
            edges: list[dict] = []
            seen_vids: set[str] = {center_vid}

            if resp.is_succeeded():
                for row in resp.rows():
                    nodes_raw = self._cell_list(row.values[0])
                    edges_raw = self._cell_list(row.values[1])
                    for v in nodes_raw:
                        node = self._vertex_to_node(v)
                        if node and node["id"] not in seen_vids:
                            seen_vids.add(node["id"])
                            nodes.append(node)
                    for e in edges_raw:
                        edge = self._edge_to_dict(e)
                        if edge:
                            edges.append(edge)
        finally:
            session.release()

        logger.info(
            "子图查询完成",
            entity=entity_name, max_hops=hops,
            node_count=len(nodes), edge_count=len(edges), space=space,
        )
        return {"nodes": nodes, "edges": edges}

    async def search_nodes(
        self,
        label: str | None = None,
        name: str | None = None,
        limit: int = 50,
        kb_id=None,
    ) -> list[dict]:
        """搜索节点（LOOKUP + 可选 name CONTAINS）。

        Args:
            label: 节点标签过滤，None 时不限。
            name: 名称模糊匹配关键词，None 时不限。
            limit: 返回最大数量。
            kb_id: 知识库 ID。None 时查询全局 space。

        Returns:
            list[dict]: 匹配节点列表，每项含 id、name、labels、type。
        """
        if not self._try_connect():
            return []

        space = _space_name(kb_id)
        self._ensure_schema(space)
        safe_label = self._validate_label(label) if label else None

        # 构造 LOOKUP 条件
        # NebulaGraph 不支持 CONTAINS/LIKE 模糊匹配，用 STARTS WITH 实现前缀匹配；
        # 若需全文搜索需集成 Elasticsearch 全文索引（后续增强）
        conds: list[str] = []
        if safe_label:
            conds.append(f'{_ENTITY_TAG}.label == "{safe_label}"')
        if name:
            conds.append(f'{_ENTITY_TAG}.name STARTS WITH "{_nql_escape(name)}"')
        where = f"WHERE {' AND '.join(conds)}" if conds else ""

        nql = (
            f'USE `{space}`; LOOKUP ON {_ENTITY_TAG} {where} '
            f'YIELD id(vertex) AS vid, {_ENTITY_TAG}.name AS name, '
            f'{_ENTITY_TAG}.label AS label, {_ENTITY_TAG}.type AS type '
            f'| ORDER BY $-.name | LIMIT {int(limit)};'
        )
        session = self._get_session()
        try:
            resp = session.execute(nql)
            if not resp.is_succeeded():
                logger.warning("search_nodes 执行失败", error=resp.error_msg())
                return []
            results: list[dict] = []
            for row in resp.rows():
                results.append(self._row_to_node(row, None))
        finally:
            session.release()

        return results

    async def delete_by_doc(self, doc_id: str, kb_id=None) -> int:
        """删除文档相关的所有节点和边（LOOKUP + DELETE VERTEX WITH EDGE）。

        NebulaGraph 不可用时优雅降级（返回 0），不抛出异常，
        确保文档删除流程不被图谱服务中断阻断。

        Args:
            doc_id: 待删除的文档 ID。
            kb_id: 知识库 ID。None 时操作全局 space。

        Returns:
            int: 删除的节点数（近似），服务不可用时返回 0。
        """
        if not self._try_connect():
            logger.warning(
                "NebulaGraph 不可用，跳过图谱节点删除",
                doc_id=doc_id,
            )
            return 0

        space = _space_name(kb_id)
        self._ensure_schema(space)

        # 先统计待删除节点数
        count_nql = (
            f'USE `{space}`; LOOKUP ON {_ENTITY_TAG} '
            f'WHERE {_ENTITY_TAG}.doc_id == "{_nql_escape(doc_id)}" '
            f'YIELD id(vertex) AS vid | YIELD count($-.vid) AS c;'
        )
        del_nql = (
            f'USE `{space}`; LOOKUP ON {_ENTITY_TAG} '
            f'WHERE {_ENTITY_TAG}.doc_id == "{_nql_escape(doc_id)}" '
            f'YIELD id(vertex) AS vid | DELETE VERTEX $-.vid WITH EDGE;'
        )
        # 生产级保护：LOOKUP 可能因 schema 刚创建未同步而报 "Schema not exist"
        # 重试 3 次，每次间隔 2 秒，确保 schema 在 storaged 同步后能正常删除
        import time
        deleted = 0
        for attempt in range(3):
            session = self._get_session()
            try:
                resp = session.execute(count_nql)
                if not resp.is_succeeded() and "Schema not exist" in (resp.error_msg() or ""):
                    logger.warning(
                        "LOOKUP 等待 schema 同步重试",
                        doc_id=doc_id, attempt=attempt + 1, space=space,
                    )
                    session.release()
                    time.sleep(2.0)
                    continue
                if resp.is_succeeded() and resp.rows():
                    deleted = self._cell_int(resp.rows()[0].values[0])
                # 执行删除（即使 count=0 也执行，确保幂等）
                del_resp = session.execute(del_nql)
                if not del_resp.is_succeeded() and "Schema not exist" in (del_resp.error_msg() or ""):
                    session.release()
                    time.sleep(2.0)
                    continue
                break
            finally:
                session.release()

        logger.info("按 doc_id 删除节点完成", doc_id=doc_id, deleted=deleted, space=space)
        return deleted

    async def get_stats(self, kb_id=None) -> dict:
        """获取图统计信息（节点/关系/标签）。

        Args:
            kb_id: 知识库 ID。None 时统计全局 space。

        Returns:
            dict: ``{"total_nodes", "total_relations", "node_labels"}``，
                服务不可用时返回零值。
        """
        if not self._try_connect():
            return {"total_nodes": 0, "total_relations": 0, "node_labels": []}

        space = _space_name(kb_id)
        self._ensure_schema(space)
        stats: dict[str, Any] = {"total_nodes": 0, "total_relations": 0, "node_labels": []}

        session = self._get_session()
        try:
            # 节点数
            resp = session.execute(
                f'USE `{space}`; LOOKUP ON {_ENTITY_TAG} YIELD id(vertex) AS vid '
                f'| YIELD count($-.vid) AS c;'
            )
            if resp.is_succeeded() and resp.rows():
                stats["total_nodes"] = self._cell_int(resp.rows()[0].values[0])

            # 关系数
            resp = session.execute(
                f'USE `{space}`; LOOKUP ON {_RELATES_EDGE} YIELD edge AS e '
                f'| YIELD count($-.e) AS c;'
            )
            if resp.is_succeeded() and resp.rows():
                stats["total_relations"] = self._cell_int(resp.rows()[0].values[0])

            # 标签（distinct label 属性）
            resp = session.execute(
                f'USE `{space}`; LOOKUP ON {_ENTITY_TAG} '
                f'YIELD {_ENTITY_TAG}.label AS label | YIELD distinct($-.label) AS label;'
            )
            if resp.is_succeeded():
                labels: list[str] = []
                for row in resp.rows():
                    labels.append(self._cell_str(row.values[0]))
                stats["node_labels"] = labels
        finally:
            session.release()

        return stats

    async def get_graph(self, limit: int = 50, kb_id=None) -> dict:
        """获取知识图谱（限制节点数，MATCH 查询）。

        Args:
            limit: 最大返回节点数。
            kb_id: 知识库 ID。None 时查询全局 space。

        Returns:
            dict: ``{"nodes": [...], "edges": [...]}``，服务不可用时返回空。
        """
        if not self._try_connect():
            return {"nodes": [], "edges": []}

        space = _space_name(kb_id)
        self._ensure_schema(space)
        nlimit = max(1, int(limit))

        nodes: list[dict] = []
        edges: list[dict] = []
        session = self._get_session()
        try:
            # 节点：NebulaGraph 3.x 必须用 n.TagName.prop 访问属性，否则返回 NULL
            resp = session.execute(
                f'USE `{space}`; MATCH (n:{_ENTITY_TAG}) RETURN id(n) AS vid, '
                f'n.{_ENTITY_TAG}.name AS name, n.{_ENTITY_TAG}.label AS label, '
                f'n.{_ENTITY_TAG}.type AS type '
                f'LIMIT {nlimit};'
            )
            if resp.is_succeeded():
                for row in resp.rows():
                    vid = self._cell_str(row.values[0])
                    name = self._cell_str(row.values[1])
                    label = self._cell_str(row.values[2])
                    ntype = self._cell_str(row.values[3])
                    if not name:
                        continue
                    nodes.append({
                        "id": vid,
                        "name": name,
                        "labels": [label] if label else [_ENTITY_TAG],
                        "type": ntype,
                    })

            # 关系：边属性用 r.prop（NebulaGraph 3.x 中边只有一个 EDGE type，
            # 不能用 r.EdgeName.prop 前缀，必须直接 r.prop）；节点属性需要 n.TagName.prop
            resp = session.execute(
                f'USE `{space}`; MATCH (a:{_ENTITY_TAG})-[r:{_RELATES_EDGE}]->(b:{_ENTITY_TAG}) '
                f'RETURN a.{_ENTITY_TAG}.name AS source, b.{_ENTITY_TAG}.name AS target, '
                f'r.rel_type AS rel_type '
                f'LIMIT {nlimit};'
            )
            if resp.is_succeeded():
                for row in resp.rows():
                    source = self._cell_str(row.values[0])
                    target = self._cell_str(row.values[1])
                    rel_type = self._cell_str(row.values[2])
                    if not source or not target:
                        continue
                    edges.append({
                        "source": source,
                        "target": target,
                        "type": rel_type or "RELATED_TO",
                    })
        finally:
            session.release()

        logger.info(
            "全局图谱查询完成",
            node_count=len(nodes), edge_count=len(edges), space=space,
        )
        return {"nodes": nodes, "edges": edges}

    async def insert_document_graph(
        self,
        doc_id: str,
        kb_id,
        entities: list,
        relations: list,
    ) -> dict:
        """将单文档的实体和关系批量写入图谱。

        Args:
            doc_id: 文档 ID。
            kb_id: 知识库 ID（UUID 对象或字符串）。
            entities: Entity 对象列表（来自 entity_extractor）。
            relations: Relation 对象列表（来自 entity_extractor）。

        Returns:
            dict: 创建统计。
        """
        kb_id_str = str(kb_id) if kb_id is not None else None

        nodes = []
        seen_entities: set[str] = set()
        for ent in entities:
            name = getattr(ent, "text", "") if hasattr(ent, "text") else ent.get("text", "")
            etype = getattr(ent, "type", "") if hasattr(ent, "type") else ent.get("type", "")
            if not name or name in seen_entities:
                continue
            seen_entities.add(name)
            nodes.append({
                "label": "Entity",
                "properties": {
                    "name": name,
                    "type": etype,
                    "doc_id": doc_id,
                },
            })

        rels = []
        for rel in relations:
            head = getattr(rel, "head", "") if hasattr(rel, "head") else rel.get("head", "")
            rel_type = getattr(rel, "relation", "") if hasattr(rel, "relation") else rel.get("relation", "")
            tail = getattr(rel, "tail", "") if hasattr(rel, "tail") else rel.get("tail", "")
            if not head or not tail or not rel_type:
                continue
            rels.append({
                "head_label": "Entity",
                "head_name": head,
                "relation": rel_type,
                "tail_label": "Entity",
                "tail_name": tail,
                "properties": {"doc_id": doc_id},
            })

        result = await self.batch_create(nodes, rels, kb_id=kb_id_str)
        logger.info(
            "文档图谱写入完成",
            doc_id=doc_id,
            kb_id=kb_id_str,
            nodes=result.get("nodes_created", 0),
            rels=result.get("relations_created", 0),
        )
        return result

    async def close(self) -> None:
        """关闭连接池，释放资源。"""
        if self._pool is not None:
            self._pool.close()
            GraphStore._pool = None
            GraphStore._connected = False
            GraphStore._schema_initialized.clear()
            logger.info("NebulaGraph 连接池已关闭")

    # ============================================================
    # ResultSet 值提取辅助
    # ============================================================
    @staticmethod
    def _cell_str(val: Any) -> str:
        """从 nebula Value 提取字符串。"""
        try:
            return val.get_sVal().decode()
        except Exception:  # noqa: BLE001
            try:
                return str(val.get_iVal())
            except Exception:  # noqa: BLE001
                return ""

    @staticmethod
    def _cell_int(val: Any) -> int:
        """从 nebula Value 提取整数。"""
        try:
            return int(val.get_iVal())
        except Exception:  # noqa: BLE001
            return 0

    @staticmethod
    def _cell_list(val: Any) -> list:
        """从 nebula Value 提取列表（Value 中的 list/set）。"""
        try:
            raw = val.get_lVal() or val.get_sVal()
            return list(raw) if raw else []
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def _cell_list_str(val: Any) -> list[str]:
        """从 nebula Value 提取字符串列表（tags(n) 返回 set）。"""
        try:
            raw = val.get_sVal() or val.get_lVal()
            if not raw:
                return []
            if isinstance(raw, (set, list, tuple)):
                return [GraphStore._cell_str(v) for v in raw]
            return [raw.decode() if isinstance(raw, bytes) else str(raw)]
        except Exception:  # noqa: BLE001
            return []

    def _row_to_node(self, row: Any, col_names: Any) -> dict:
        """将 LOOKUP 结果行转换为节点 dict。"""
        vals = row.values
        # 列顺序：vid, name, label, type（依 YIELD 子句）
        return {
            "id": self._cell_str(vals[0]) if len(vals) > 0 else "",
            "name": self._cell_str(vals[1]) if len(vals) > 1 else "",
            "labels": [self._cell_str(vals[2])] if len(vals) > 2 and self._cell_str(vals[2]) else [],
            "type": self._cell_str(vals[3]) if len(vals) > 3 else "",
        }

    @staticmethod
    def _vertex_to_node(v: Any) -> dict | None:
        """将 GET SUBGRAPH 返回的 vertex 转换为节点 dict。"""
        try:
            vid = v.get_id().get_string() if hasattr(v, "get_id") else str(v)
            props = v.get_properties() if hasattr(v, "get_properties") else {}
            tags = v.get_tags() if hasattr(v, "get_tags") else []
            tag_names = []
            for t in tags:
                try:
                    tag_names.append(t.get_name())
                except Exception:  # noqa: BLE001
                    pass
            name = ""
            ntype = ""
            label = ""
            for p in props:
                try:
                    k = p.get_key()
                    val = p.get_value()
                    if k == "name":
                        name = val.get_sVal().decode()
                    elif k == "type":
                        ntype = val.get_sVal().decode()
                    elif k == "label":
                        label = val.get_sVal().decode()
                except Exception:  # noqa: BLE001
                    pass
            return {
                "id": vid,
                "name": name,
                "labels": [label] if label else tag_names,
                "type": ntype,
            }
        except Exception as err:  # noqa: BLE001
            logger.debug("vertex 转换失败", error=str(err))
            return None

    @staticmethod
    def _edge_to_dict(e: Any) -> dict | None:
        """将 GET SUBGRAPH 返回的 edge 转换为关系 dict。"""
        try:
            src = e.get_src().get_string() if hasattr(e, "get_src") else ""
            dst = e.get_dst().get_string() if hasattr(e, "get_dst") else ""
            props = e.get_props() if hasattr(e, "get_props") else []
            rel_type = ""
            for p in props:
                try:
                    if p.get_key() == "rel_type":
                        rel_type = p.get_value().get_sVal().decode()
                except Exception:  # noqa: BLE001
                    pass
            return {"source": src, "target": dst, "type": rel_type}
        except Exception as err:  # noqa: BLE001
            logger.debug("edge 转换失败", error=str(err))
            return None


# 模块级单例，懒加载，导入时不连接 NebulaGraph
graph_store = GraphStore()
