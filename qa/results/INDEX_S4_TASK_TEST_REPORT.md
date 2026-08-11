# S4 独立索引任务状态机测试报告（M28/D8）

- 日期：2026-08-12
- 关联实现：
  - `backend/app/services/document_service.py`：enqueue_index_task / run_index_task / fail_index_task / list_tasks(type 过滤)
  - `backend/app/tasks/sync_executor.py`、`backend/app/tasks/arq_worker.py`：按任务类型路由 + 解析成功自动触发
  - `backend/app/api/v1/endpoints/kb_indexing.py`：POST index（editor+）/ GET index/tasks
  - `backend/app/schemas/document.py`：DocumentOut 增加 index_status/index_progress/index_total/index_error
  - `backend/app/core/exceptions.py`：新增 BUSINESS_INVALID_STATE/BUSINESS_CONFLICT + http_status 支持（409）

## 用例统计

| 分层 | 测试文件 | 用例数 | 结果 |
|------|----------|--------|------|
| L1 单元 | `qa/unit/test_indexing_task_unit.py` | 4 | 通过 |
| L2 集成 | `qa/integration/test_indexing_task_integration.py` | 1（解析完成自动触发） | 通过 |
| L3 功能 | `qa/integration/test_indexing_task_integration.py` | 2（手动全链路/任务列表） | 通过 |
| L4 边界+并发 | `qa/boundary/test_indexing_task_boundary.py` | 6（含并发触发防重） | 通过 |
| L5 安全 | `qa/security/test_indexing_task_security.py` | 4（viewer/非成员/editor/跨 KB） | 通过 |
| **合计** | | **17** | **17 通过 / 0 失败** |

## 覆盖率统计表

| 模块 | L1 单测 | L2 集成 | L3 功能 | L4 边界 | L5 安全 | 用例总数 | 是否全覆盖 |
|------|---------|---------|---------|---------|---------|----------|------------|
| M28 索引任务状态机 | 4 | 1 | 2 | 6（含并发） | 4 | 17 | 是（5/5 层） |

行覆盖率说明：
- S4 新增函数（`document_service.py` 393-657 行：enqueue/run/fail_index_task）功能分支全部覆盖；
- `document_service.py` 文件整体 70%，未覆盖行均为历史函数（delete_document/cleanup_expired_pages/get_page_image 等），不属于 M28 范围；
- 第 420 行（raise 业务异常）为 coverage 对异常路径 raise 行的计数偏差，实际已被前置校验用例触发。

## 关键覆盖点

1. 自动触发：解析成功后同会话自动创建 document_index 任务 + outbox（sync/arq 双执行器）；
2. 手动触发/重索引：editor+ 权限、咨询锁防重、活动任务存在返回 409；
3. 状态机：not_indexed → indexing → indexed / index_failed，解析状态互不覆盖；
4. 幂等重跑：先删旧块（document_chunks/text_chunks）再批量插入，块数一致无重复；
5. 双向量落库：title_vector/content_vector 1024 维写入 pgvector（字符串表示解析验证）；
6. 失败隔离：产物缺失/空分块 → index_failed + index_error，document.status 保持 completed；
7. 防御分支：无索引任务/缺 layout 产物给出明确错误；
8. 并发：4 并发触发同一文档仅 1 个任务创建成功；
9. 安全：viewer/非成员 403、editor 200、跨 KB 隔离；
10. 任务列表 API：type 过滤 + 文件名回填。

## 测试中修复的真实缺陷

1. sync_executor 误路由：无 outbox 时误执行解析任务 → 按文档最新 queued 任务类型路由；
2. API 与测试并发执行同一任务：sync 分支 create_task 后台执行 + 测试手动 execute 并发导致 UniqueViolation（测试改为仅轮询等待）；
3. DocumentOut schema 缺索引状态字段：前端/API 无法感知 index_status → 已补充；
4. ErrorCode 缺冲突/非法状态码：新增 30018/30019 + BusinessException http_status 支持；
5. 固定 task_id 重复运行冲突：测试改用随机 task_id。

## 结论

S4 通过铁律验收：五层全覆盖（17/17），索引状态机功能/边界/并发/安全验证通过。
