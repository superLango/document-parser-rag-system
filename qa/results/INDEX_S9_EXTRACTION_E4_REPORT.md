# 结构化抽取 E4 · 端点与任务 报告

- 日期：2026-08-13
- 范围：抽取端点（列表/启动/状态/结果/历史/导出/删除）、arq/sync 任务接入、进度回调。

## 交付内容

1. 端点 [kb_extraction.py](/home/grainuser/hansonDoc_RAG/backend/app/api/v1/endpoints/kb_extraction.py)：
   - `GET /documents`：已完成解析+索引的可抽取文档列表（抽取状态/历史数/最新 Schema）；
   - `POST /{document_id}`：启动抽取（editor+，sync 模式后台执行，advisory lock 防并发重复）；
   - `GET /{document_id}/status`：任务/结果状态与进度（轮询用）；
   - `GET /{document_id}/result`：最新结果；
   - `GET /{document_id}/history`：历史版本；
   - `GET /export?document_id=`：CSV 导出（空结果也输出表头）；
   - `DELETE /{document_id}/result`：删除最新结果与全部历史（editor+，审计）。
2. [arq_worker.py](/home/grainuser/hansonDoc_RAG/backend/app/tasks/arq_worker.py)：新增 `extract_document_task` 与 outbox 分发分支。
3. [extraction_task_service.py](/home/grainuser/hansonDoc_RAG/backend/app/services/extraction/extraction_task_service.py)：启动加咨询锁；流水线进度回调实时更新结果进度。
4. [pipeline.py](/home/grainuser/hansonDoc_RAG/backend/app/services/extraction/pipeline.py)：类别抽取异常（含 LLM 不可用）→ 任务整体失败（B11 不静默吞错）。

## 测试覆盖率

| 层 | 用例数 | 覆盖内容 | 结果 |
|----|--------|----------|------|
| L2/L3 集成 | 4 | 列表→启动→状态失败→结果→导出→删除、前置拒绝、并发启动 200/409、预置结果读写 | ✅ |
| L4 边界 | 3 | 缺文档 400、空导出表头、无结果删除幂等 | ✅ |
| L5 安全 | 3 | viewer 只读、非成员 403、跨 KB 结果不可见 | ✅ |

后端全量回归：**168/168 通过**（M34+M33+全局配置+E1-E4）。并发用例：同文档并发启动仅一个成功（advisory lock）。

## 说明

- LLM 调用失败（含连接失败/非法 JSON）现在使任务 `failed` 并保留错误信息，前端可展示“重新抽取”（B11）。
- E5 前端将消费以上端点实现列表/详情/进度轮询/导出/删除。
