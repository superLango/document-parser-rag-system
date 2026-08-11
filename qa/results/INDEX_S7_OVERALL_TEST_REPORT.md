# S7 前端向量搜索 + 整体验收测试报告（M31/M32）

- 日期：2026-08-12
- 关联实现：
  - `frontend/src/views/kb/KbVectorSearchPage.tsx`：向量搜索页（输入/过滤/结果/展开全文/章节上下文/空态/错误态/移动端）
  - `frontend/src/api/modules/indexing.ts`、`frontend/src/api/types.ts`：检索/索引 API 封装
  - `frontend/src/router/index.tsx`：vector-search 路由接入真实页面
  - `frontend/src/content/help.ts`、`docs/HELP_DOCS.md`：帮助文档新增向量搜索章节
  - `backend/app/services/embedding/embedding_service.py`：单线程推理执行器（规避跨线程 CUDA 死锁）
  - `backend/app/tasks/sync_executor.py`：sync 模式解析后立即执行自动索引（修复悬挂）
  - `backend/app/services/document_service.py`：索引嵌入超时保护（INDEX_EMBED_TIMEOUT）

## M31 前端功能（Playwright E2E）

| 场景 | 结果 |
|------|------|
| S7-01 页面标题 | ✅ |
| S7-02 检索返回结果 | ✅ |
| S7-03 命中统计展示 | ✅ |
| S7-04 结果含查询内容 | ✅ |
| S7-05 章节上下文可展开 | ✅ |
| S7-06 空查询禁用检索 | ✅ |
| S7-07 帮助截图生成（frontend/public/help/vector-search.png） | ✅ |
| S7-08 移动端可用 | ✅ |

**8/8 通过**，报告 `qa/results/INDEX_S7_E2E_REPORT.md`，截图已用于帮助文档。

## M32 整体验收（真实全链路）

| 场景 | 结果 |
|------|------|
| 真实 PDF 上传→解析→自动索引→混合检索→过滤→删除回退 | ✅ |
| 越权矩阵（viewer 可搜不可索引/非成员 403） | ✅ |
| 并发（5 并发检索一致） | ✅ |

**3/3 通过**（`qa/integration/test_overall_index_acceptance.py`）。

## S1-S7 覆盖率统计表（M24-M32）

| 模块 | L1 单测 | L2 集成 | L3 功能 | L4 边界 | L5 安全 | 用例总数 | 行覆盖率 | 是否全覆盖 |
|------|---------|---------|---------|---------|---------|----------|----------|------------|
| M24 索引存储底座（S1） | 7 | 3 | 2 | 6 | 5 | 23 | 100%（models） | 是 |
| M25 层级分块器（S2） | 30 | 3 | 1 | 4 | 3 | 41 | 100% | 是 |
| M27 表格增强（S2） | 12 | 1 | 0 | 2 | 2 | 17 | 100% | 是 |
| M26 嵌入服务（S3） | 7 | 4 | 1 | 3 | 2 | 17 | 100% | 是 |
| M28 索引任务状态机（S4） | 4 | 1 | 2 | 6 | 4 | 17 | S4 函数全覆盖 | 是 |
| M29 jieba BM25（S5） | 6 | 1 | 2 | 6 | 2 | 17 | 100% | 是 |
| M30 检索服务（S6） | 7 | 1 | 2 | 4 | 4 | 18 | 100%（retrieval/reranker/bm25） | 是 |
| M31 向量搜索前端（S7） | 0 | 0 | 8（E2E） | 0 | 0 | 8 | —（E2E） | 是 |
| M32 整体验收 | 0 | 0 | 1 | 0 | 2 | 3 | — | 是 |
| **合计** | | | | | | **161** | | |

后端回归：S1-S6 全部 148 个用例一次通过（M24-M30）；M31 E2E 8/8；M32 综合 3/3。

## 本阶段修复的真实缺陷

1. sync 模式自动索引任务悬挂（无 dispatcher）→ 解析完成后立即执行；
2. BGE-M3 与版面模型同进程交替推理跨线程死锁 → 专用单线程推理执行器；
3. 测试会话 identity map 缓存旧任务状态 → populate_existing；
4. 简单 PDF 文本量不足 50 字符被分类为 OCR → 测试 PDF 结构化多行；
5. 旧后端进程未重启导致 E2E 使用旧逻辑。

## 结论

S7 通过铁律验收：M31（8/8）+ M32（3/3）+ 后端全量回归（148/148），帮助文档与截图已更新。
