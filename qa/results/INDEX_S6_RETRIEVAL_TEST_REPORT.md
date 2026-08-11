# S6 检索服务与 API 测试报告（M30/D6）

- 日期：2026-08-12
- 关联实现：
  - `backend/app/services/indexing/retrieval.py`：双向量 dense + BM25 + RRF 融合 + 过滤 + rerank 占位
  - `backend/app/services/indexing/reranker.py`：重排接口占位（本期直通）
  - `backend/app/services/indexing/bm25.py`：score_query 支持过滤条件
  - `backend/app/schemas/indexing.py`：SearchRequest/SearchHit/SearchResponse
  - `backend/app/api/v1/endpoints/kb_indexing.py`：POST /kb/{kb_id}/search
  - `backend/app/core/config.py`：RETRIEVAL_* 权重/候选参数

## 用例统计

| 分层 | 测试文件 | 用例数 | 结果 |
|------|----------|--------|------|
| L1 单元 | `qa/unit/test_retrieval_unit.py` | 7 | 通过 |
| L2 集成 | `qa/integration/test_retrieval_integration.py` | 1（语义/词法命中） | 通过 |
| L3 功能 | `qa/integration/test_retrieval_integration.py` | 2（过滤/API+rerank 直通） | 通过 |
| L4 边界 | `qa/boundary/test_retrieval_boundary.py` | 4（空查询/无语料/校验/未知 KB） | 通过 |
| L5 安全 | `qa/security/test_retrieval_security.py` | 4（viewer 可搜/非成员 403/跨 KB/并发一致） | 通过 |
| **合计** | | **18** | **18 通过 / 0 失败** |

## 覆盖率统计表

| 模块 | L1 单测 | L2 集成 | L3 功能 | L4 边界 | L5 安全 | 用例总数 | 是否全覆盖 |
|------|---------|---------|---------|---------|---------|----------|------------|
| M30 检索服务 | 7 | 1 | 2 | 4 | 4 | 18 | 是（5/5 层） |

行覆盖率（coverage sysmon，M29+M30 合并）：
- `retrieval.py`：101 语句 0 未覆盖，**100%**
- `reranker.py`：8 语句 0 未覆盖，**100%**
- `bm25.py`：119 语句 0 未覆盖，**100%**

## 关键覆盖点

1. 查询双路编码（title/content 同文本）→ title/content 两路 pgvector 余弦 ANN（top_k×2 候选）；
2. dense 融合：title 0.2 + content 0.8 相似度加权；
3. BM25 路同样应用过滤条件（修复：原实现 BM25 未带过滤导致混入无关块）；
4. RRF 融合（k=60，dense 1.0 / keyword 1.2），双路命中优先、top_k 限制、单路可入结果；
5. 过滤：document_id / has_table / level 全部生效；
6. API：Body 参数自动校验（空 query/top_k 越界 → 400，项目统一映射）、有效成员可搜；
7. 安全：viewer 可检索、非成员 403、跨 KB 隔离（A 库查不到 B 库独有编码）；
8. 并发：6 并发检索结果一致；
9. rerank 接口占位直通，返回字段完整（chunk_id/document_id/content/hierarchy_path/title/source_pages/has_table/score）。

## 测试中修复的缺陷

1. BM25 路未应用检索过滤条件（真实功能缺陷）→ score_query 增加 extra_where/extra_params；
2. slots dataclass 无 `__dict__` → API 用 dataclasses.asdict 序列化；
3. 手动 model_validate 不触发统一校验映射 → 改为 FastAPI Body 参数；
4. 测试 UUID 双重转换 → helper 兼容 UUID/str。

## 回归

- M28/M29 快速用例回归 46/46 通过（含并发/安全）；
- ruff 全部通过。

## 结论

S6 通过铁律验收：五层全覆盖（18/18），核心模块行覆盖率 100%，过滤/权限/并发验证通过。
