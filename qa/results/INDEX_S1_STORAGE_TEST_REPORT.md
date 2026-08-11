# S1 存储底座测试报告（M24 索引存储底座）

- 日期：2026-08-11
- 关联迁移：`009_vector_indexing`（pgvector + document_chunks/text_chunks/kb_bm25_stats + documents 索引状态列 + RLS）
- 测试库：`hanson_doc_rag_test`（PG18.4 独立实例，pgvector 0.8.1）
- 执行命令：`pytest unit/test_indexing_models.py integration/test_indexing_storage.py boundary/test_indexing_storage_boundary.py security/test_indexing_storage_security.py`

## 用例统计

| 分层 | 测试文件 | 用例数 | 结果 |
|------|----------|--------|------|
| L1 单元 | `qa/unit/test_indexing_models.py` | 7 | 全部通过 |
| L2 集成 | `qa/integration/test_indexing_storage.py` | 3 | 全部通过 |
| L3 功能 | `qa/integration/test_indexing_storage.py` | 2 | 全部通过 |
| L4 边界/异常（含并发） | `qa/boundary/test_indexing_storage_boundary.py` | 6 | 全部通过 |
| L5 安全渗透 | `qa/security/test_indexing_storage_security.py` | 5 | 全部通过 |
| **合计** | | **23** | **23 通过 / 0 失败** |

## 覆盖率统计表

| 模块 | L1 单测 | L2 集成 | L3 功能 | L4 边界 | L5 安全 | 用例总数 | 是否全覆盖 |
|------|---------|---------|---------|---------|---------|----------|------------|
| M24 索引存储底座 | 7 | 3 | 2 | 6（含并发） | 5 | 23 | 是（5/5 层） |

行覆盖率（coverage sysmon 核心）：
- `app/models/indexing.py`：57 语句，0 未覆盖，**100%**
- `app/models/document.py`：66 语句，0 未覆盖，**100%**

## 关键覆盖点

1. 迁移产物：vector 扩展 0.8.1、三张表、HNSW×2 + GIN + 部分索引、12 条 RLS 策略、documents 4 个索引状态列；
2. 迁移幂等：`alembic upgrade head` 重复执行无副作用；`downgrade → upgrade` 往返通过（`qa/migration/verify_migration.sh` 6/6）；
3. RLS 矩阵：无上下文拒绝、非成员拒绝、viewer 可读不可写、editor 可写、跨 KB 隔离；
4. 边界：向量维度不匹配报错、唯一约束冲突、向量可空（索引任务失败不阻塞落库契约）、软删不参与部分索引；
5. 并发：同一文档 8 并发写入不同 chunk 无冲突、重复迁移并发幂等；
6. REG-15 复测：空 `app.user_id` 时 `hansondoc_current_user()` 返回 NULL 不抛错。

## 环境变更（S1 前置）

- PostgreSQL 18.4 独立源码安装：`/home/grainuser/pgsql18`（非 conda），数据目录 `/home/grainuser/hansondoc_pgdata18`；
- 管理脚本：`scripts/pg18_start.sh` / `pg18_stop.sh` / `pg18_status.sh`；
- 旧 conda PG16 数据目录 `/home/grainuser/hansondoc_pgdata` 保留未删除（迁移完成后已停止）；
- 已迁移数据库：`hanson_doc_rag`（22 表，users=43/kb=76/documents=78/tasks=117）、`hanson_doc_rag_test`（22 表）；
- 依赖新增：`pgvector>=0.5.0`、`jieba>=0.42.1`；`qa/migration/verify_migration.sh` 已切换到 PG18 psql。

## 结论

S1 通过铁律验收：五层全覆盖（23/23，100%），行覆盖率 100%，迁移幂等与 RLS 安全验证通过。
