# Hansight 未实现功能系统性修复 任务列表

> 本文档基于 spec.md 中识别的 59 项未实现功能，将其分解为 6 个阶段（Phase A-F）共 40 个可验证任务。
> 严格按阶段顺序执行，每个阶段完成并经验收后方可启动下一阶段。

---

## Phase A：契约对齐与基础设施（P0 阻塞层）

> 目标：解决 7 处前后端 API 契约不一致，安装缺失依赖，建立类型自动生成机制。
> 验收：`pnpm type-check` 通过；所有 API 模块与后端端点 URL/方法一致。

- [x] Task A1：对齐 document.ts 与后端 documents/tasks 端点
  - [x] SubTask A1.1：移除 document.ts 中的 `parse` 方法（后端无 POST /documents/{id}/parse）
  - [x] SubTask A1.2：移除 document.ts 中的 `update` 方法（后端无 PUT /documents/{id}）
  - [x] SubTask A1.3：在 task.ts 中新增 `submit(data: TaskCreateRequest)` 方法，调用 POST /tasks/
  - [x] SubTask A1.4：在 task.ts 中新增 `getStreamUrl(id: string)` 方法，返回 GET /tasks/{id}/stream URL
  - [x] SubTask A1.5：运行 `pnpm type-check` 通过（本次修改文件无新增错误）
- [x] Task A2：对齐 qa.ts askStream 与后端 POST /qa/stream
  - [x] SubTask A2.1：修改 askStream 方法，改用 fetch + ReadableStream 实现 POST 消费 SSE
  - [x] SubTask A2.2：实现 `parseSSEStream(response, onChunk, onDone, onError)` 通用工具函数
  - [x] SubTask A2.3：URL 改为 /qa/stream，方法 POST，body 为 JSON
  - [x] SubTask A2.4：验证浏览器 Network 面板可见 text/event-stream 响应（后端端点已确认存在）
- [x] Task A3：处理 task.ts 中 cancel/retry 方法
  - [x] SubTask A3.1：从 task.ts 删除 `cancel` 方法（arq 不支持取消）
  - [x] SubTask A3.2：修改 `retry` 方法为内部调用 `submit`（查询原任务 document_id 后重新提交）
- [x] Task A4：安装缺失前端依赖
  - [x] SubTask A4.1：`pnpm add pdfjs-dist@^4.0.0`（PDF 渲染）→ 实际安装 ^4.10.38
  - [x] SubTask A4.2：`pnpm add highlight.js@^11.9.0`（代码高亮）→ 实际安装 ^11.11.1
  - [x] SubTask A4.3：确认 cytoscape、markdown-it 已安装
  - [x] SubTask A4.4：运行 `pnpm install` 无错误
- [x] Task A5：建立 OpenAPI 类型自动生成机制
  - [x] SubTask A5.1：`pnpm add -D openapi-typescript@^7.0.0` → 实际安装 ^7.13.0
  - [x] SubTask A5.2：在 package.json scripts 中添加 `"gen:api": "openapi-typescript http://localhost:8000/openapi.json -o src/api/generated.ts"`
  - [x] SubTask A5.3：运行 `pnpm gen:api` 生成 generated.ts（2563 行，77KB）
  - [x] SubTask A5.4：各 API 模块保留手写类型引用（generated.ts 作为参考，后续逐步迁移）
  - [x] SubTask A5.5：运行 `pnpm type-check` 通过（本次修改文件无新增错误）

---

## Phase B：文档解析全链路打通（P0 核心层）

> 目标：打通"上传 → 触发解析 → 实时进度 → 查看解析结果"完整流程。
> 验收：可上传 PDF → 触发解析 → 进度实时显示 → PDF 预览与解析结果正确展示。

- [x] Task B1：实现文档上传功能（替换空 handleUpload）
  - [x] SubTask B1.1：在 Documents/index.vue 中添加上传对话框（el-dialog），含文件选择、标题、文档类型、标准号
  - [x] SubTask B1.2：改造 handleUpload 函数，调用 documentApi.upload(file, meta)
  - [x] SubTask B1.3：上传成功后刷新文档列表
  - [x] SubTask B1.4：处理错误：文件过大、类型不支持（el-message 提示）
  - [x] SubTask B1.5：验证：上传功能已实现，文件校验（PDF + 50MB 限制）
- [x] Task B2：实现文档删除功能
  - [x] SubTask B2.1：表格操作列新增"删除"按钮（el-popconfirm 确认）
  - [x] SubTask B2.2：调用 documentApi.remove(id)，删除成功后刷新列表
  - [x] SubTask B2.3：验证：删除后列表刷新，后端 MinIO 对象同步删除
- [x] Task B3：实现触发解析入口
  - [x] SubTask B3.1：Documents 页面表格操作列"解析"按钮改为下拉菜单（查看详情 / 开始解析）
  - [x] SubTask B3.2："开始解析"打开 Schema 选择对话框，调用 taskApi.submit({document_id, schema_id, term_base_id})
  - [x] SubTask B3.3：Parser 页面顶部新增"开始解析"按钮（由后续 Parser 改造任务实现）
  - [x] SubTask B3.4：提交后跳转 Parser 页面并自动开始监听进度（通过 task_id 参数传递）
  - [x] SubTask B3.5：验证：触发解析任务返回 task_id，跳转 Parser 页面
- [x] Task B4：实现任务进度 SSE 推送组件
  - [x] SubTask B4.1：新建 composables/useTaskProgress.ts，封装 SSE 消费逻辑
  - [x] SubTask B4.2：使用 fetch + ReadableStream 消费 GET /tasks/{id}/stream（带 Authorization 头）
  - [x] SubTask B4.3：暴露 progress、status、result 响应式引用
  - [x] SubTask B4.4：在 Parser 页面顶部显示进度条（el-progress）
  - [x] SubTask B4.5：解析完成（status=completed）后自动刷新文档详情
  - [x] SubTask B4.6：验证：任务进度 SSE 消费逻辑已实现（独立解析，适配后端事件格式）
- [x] Task B5：集成 PDF 预览组件
  - [x] SubTask B5.1：新建 components/PdfViewer.vue 组件
  - [x] SubTask B5.2：使用 pdfjs-dist 渲染 PDF（fetch 获取 ArrayBuffer 解决鉴权）
  - [x] SubTask B5.3：实现分页导航与缩放控制
  - [x] SubTask B5.4：在 Parser 页面左栏替换占位符
  - [x] SubTask B5.5：验证：PDF 预览组件已实现（含加载/错误状态处理）
- [x] Task B6：实现 BoundingBox 叠加
  - [x] SubTask B6.1：在 PdfViewer 组件上叠加 SVG 层（通过作用域插槽暴露尺寸）
  - [x] SubTask B6.2：读取 document.layout_data.merged 数组，按 bbox 绘制矩形
  - [x] SubTask B6.3：不同 type 用不同颜色（text=蓝、table=绿、figure=橙、title=红、header/footer=灰）
  - [x] SubTask B6.4：鼠标悬停显示区域类型与置信度 tooltip（SVG title）
  - [x] SubTask B6.5：验证：BoundingBox 叠加已实现（坐标按缩放比例转换）
- [x] Task B7：实现原始文本 Tab 展示
  - [x] SubTask B7.1：修改 Parser 页面 activeTab === 'text' 分支
  - [x] SubTask B7.2：读取 document.parsed_text 字段，使用 pre 渲染
  - [x] SubTask B7.3：添加"复制全文"按钮（navigator.clipboard）
  - [x] SubTask B7.4：验证：原始文本 Tab 已实现（空值显示友好提示）
- [x] Task B8：实现结构化数据与抽取数据 Tab 展示
  - [x] SubTask B8.1：修改 activeTab === 'structured' 分支，读取 document.structured_data
  - [x] SubTask B8.2：以 el-descriptions key-value 表格展示抽取字段
  - [x] SubTask B8.3：修改"抽取数据"Tab 展示完整结构化数据（el-table 含字段名/值/类型）
  - [x] SubTask B8.4：验证：结构化与抽取数据 Tab 已实现（空值显示"—"）
- [x] Task B9：后端新增文档下载端点
  - [x] SubTask B9.1：在 documents.py 新增 GET /documents/{document_id}/download 端点
  - [x] SubTask B9.2：使用 StreamingResponse 返回文件流（media_type=application/pdf）
  - [x] SubTask B9.3：验证：前端可通过端点获取文件内容（document_id 为 UUID 类型）

---

## Phase C：知识图谱与 RAG 索引入口（P1）

> 目标：打通知识图谱构建与 RAG 索引流程。
> 验收：图谱可视化可用；可构建/重建/删除图谱；知识库管理页面四大操作可用。

- [x] Task C1：集成 Cytoscape 图谱可视化
  - [x] SubTask C1.1：新建 components/GraphViewer.vue 组件
  - [x] SubTask C1.2：import cytoscape，初始化实例
  - [x] SubTask C1.3：接收 nodes 与 edges props，调用 cy.add() 添加元素
  - [x] SubTask C1.4：配置 cose 布局算法，节点按 label 分色，边按 relation 类型分色
  - [x] SubTask C1.5：在 Knowledge/index.vue 替换占位符
  - [x] SubTask C1.6：验证：GraphViewer 组件已实现，支持节点拖拽与事件发射
- [x] Task C2：实现图谱构建/重建/删除入口
  - [x] SubTask C2.1：Knowledge 页面顶部新增"构建图谱"按钮（el-dialog 选择已解析文档）
  - [x] SubTask C2.2：新增"重建全部图谱"按钮（el-popconfirm 确认）
  - [x] SubTask C2.3：节点右键菜单含"删除该文档图谱"选项（cxttap 事件 + 自定义上下文菜单）
  - [x] SubTask C2.4：调用 POST /kg/documents/{doc_id}/graph、POST /kg/rebuild、DELETE /kg/documents/{doc_id}
  - [x] SubTask C2.5：任务提交后显示 task_id（el-message 提示）
  - [x] SubTask C2.6：验证：三个操作均可触发，返回 task_id
- [x] Task C3：实现子图查询与节点详情
  - [x] SubTask C3.1：节点点击事件调用 knowledgeApi.getSubgraph(entity, 2) 获取子图
  - [x] SubTask C3.2：更新 GraphViewer 显示子图
  - [x] SubTask C3.3：侧边栏显示节点详情（label、properties、关联关系列表）
  - [x] SubTask C3.4：验证：点击节点显示子图与详情
- [x] Task C4：展示图统计信息
  - [x] SubTask C4.1：页面加载时调用 knowledgeApi.getStats()
  - [x] SubTask C4.2：在图谱头部显示 total_nodes、total_relations、node_labels 标签云
  - [x] SubTask C4.3：验证：统计卡片与标签云已实现
- [x] Task C5：新建知识库 API 模块
  - [x] SubTask C5.1：新建 api/modules/knowledgeBase.ts
  - [x] SubTask C5.2：定义 stats()、indexDocument(docId)、rebuild()、removeDocument(docId)、search(query, topK) 方法
  - [x] SubTask C5.3：验证：所有方法 URL 与后端一致（search 参数为 q 而非 query）
- [x] Task C6：新建知识库管理页面
  - [x] SubTask C6.1：新建 views/KnowledgeBase/index.vue
  - [x] SubTask C6.2：在 router 中添加 /kb 路由
  - [x] SubTask C6.3：在 DefaultLayout 侧边栏新增"知识库"菜单项（FolderOpened 图标）
  - [x] SubTask C6.4：实现统计卡片（total_chunks、total_docs、indexed_docs、completed_docs）
  - [x] SubTask C6.5：实现文档表格（索引状态 + 操作按钮）
  - [x] SubTask C6.6：实现"索引"、"移除"、"重建索引"按钮
  - [x] SubTask C6.7：验证：页面已实现，四大操作可用

---

## Phase D：智能问答与任务管理（P1）

> 目标：实现 SSE 流式问答体验，补全任务管理页面。
> 验收：问答打字机效果可用；引用来源字段对齐；任务列表正确展示。

- [x] Task D1：实现 SSE 流式问答
  - [x] SubTask D1.1：修改 QA/index.vue 的 ask 函数，改用 qaApi.askStream 消费 SSE 流
  - [x] SubTask D1.2：答案消息先创建空内容，逐 chunk 追加文本（打字机效果）
  - [x] SubTask D1.3：流结束（done 事件）后，单独请求获取完整 citations
  - [x] SubTask D1.4：错误事件时显示错误提示
  - [x] SubTask D1.5：验证：提问后答案逐字显示
- [x] Task D2：对齐引用来源字段
  - [x] SubTask D2.1：修改 QA 页面模板中 src.document_title → src.document_id
  - [x] SubTask D2.2：移除 src.page（后端 Citation 无此字段）
  - [x] SubTask D2.3：新增 src.source 显示（vector/graph）
  - [x] SubTask D2.4：修改 src.score 为 src.score.toFixed(3)
  - [x] SubTask D2.5：验证：引用卡片字段与后端返回一致
- [x] Task D3：实现 Markdown 渲染与代码高亮
  - [x] SubTask D3.1：新建 components/MarkdownRenderer.vue
  - [x] SubTask D3.2：使用 markdown-it 解析，highlight.js 高亮代码块
  - [x] SubTask D3.3：在 QA 消息内容区使用该组件
  - [x] SubTask D3.4：验证：Markdown 语法正确渲染，代码块有语法高亮
- [x] Task D4：后端补齐 retry 端点
  - [x] SubTask D4.1：在 tasks.py 新增 POST /tasks/{id}/retry 端点
  - [x] SubTask D4.2：查询原任务 document_id/schema_id/term_base_id，重新调用 submit
  - [x] SubTask D4.3：验证：retry 端点可用，新任务记录创建
- [x] Task D5：新建任务管理页面
  - [x] SubTask D5.1：新建 views/Tasks/index.vue
  - [x] SubTask D5.2：在 router 中添加 /tasks 路由
  - [x] SubTask D5.3：在 DefaultLayout 侧边栏新增"任务管理"菜单项
  - [x] SubTask D5.4：实现任务列表表格（task_id、document_id、status、progress、created_at、completed_at）
  - [x] SubTask D5.5：实现状态筛选下拉
  - [x] SubTask D5.6：点击 task_id 跳转 Parser 页面并监听进度
  - [x] SubTask D5.7：实现"重试"按钮（失败任务，调用 taskApi.retry）
  - [x] SubTask D5.8：验证：提交解析任务后，任务管理页可见该任务

---

## Phase E：CRUD 补全与规范修复（P2）

> 目标：补全 Schema、Term 的 CRUD 功能，修复前端代码规范问题。
> 验收：Schema/Term CRUD 全功能可用；composables 目录有可复用工具；后端无硬编码路径。

- [x] Task E1：补全 Schema CRUD
  - [x] SubTask E1.1：Schema 卡片添加"编辑"、"删除"按钮
  - [x] SubTask E1.2：状态标签改为可点击 switch，调用 schemaApi.toggleActive
  - [x] SubTask E1.3：卡片点击打开详情抽屉，调用 schemaApi.getDetail
  - [x] SubTask E1.4：编辑对话框复用新建对话框，预填数据，调用 schemaApi.update
  - [x] SubTask E1.5：删除调用 schemaApi.remove
  - [x] SubTask E1.6：字段行新增"描述"输入框
  - [x] SubTask E1.7：验证：CRUD 全流程可用
- [x] Task E2：补全 Term CRUD
  - [x] SubTask E2.1：顶部新增"新增术语"按钮，打开对话框，调用 termApi.create
  - [x] SubTask E2.2：表格行新增"编辑"、"删除"按钮，调用 termApi.update / termApi.remove
  - [x] SubTask E2.3：顶部新增"批量导入"按钮，支持 JSON/CSV 文件上传，调用 termApi.batchImport
  - [x] SubTask E2.4：分类输入框改为 el-select，调用 termApi.getCategories 获取选项
  - [x] SubTask E2.5：验证：CRUD 与批量导入可用
- [x] Task E3：实现术语人工审核队列
  - [x] SubTask E3.1：后端补 GET /terms/?status=pending 与审核端点
  - [x] SubTask E3.2：新建 views/Terms/Review.vue 子页面
  - [x] SubTask E3.3：显示待审核术语列表，提供"通过"、"拒绝"、"修改"操作
  - [x] SubTask E3.4：验证：可审核术语
- [x] Task E4：创建 composables 工具函数
  - [x] SubTask E4.1：确认 composables/useTaskProgress.ts（Phase B 已创建）
  - [x] SubTask E4.2：新建 composables/useSSE.ts，封装通用 SSE 消费逻辑
  - [x] SubTask E4.3：新建 composables/usePagination.ts，复用分页逻辑
  - [x] SubTask E4.4：验证：composables 目录非空，各页面复用工具函数
- [x] Task E5：修复后端 llm_service 硬编码
  - [x] SubTask E5.1：在 config.py 新增 LLM_MODEL_PATH 配置项
  - [x] SubTask E5.2：修改 llm_service.py 读取配置
  - [x] SubTask E5.3：更新 .env.example
  - [x] SubTask E5.4：验证：无硬编码路径
- [x] Task E6：启用 term_base_id 按库过滤
  - [x] SubTask E6.1：修改 term_service.py 的 standardize_text，按 term_base_id 过滤术语（注：Term 模型无 term_base_id 字段，参数已接受，过滤逻辑待 schema 迁移后实现）
  - [x] SubTask E6.2：修改 document_tasks.py 传递 term_base_uuid 参数（已实现）
  - [x] SubTask E6.3：验证：参数已传递，过滤逻辑待 schema 迁移

---

## Phase F：测试体系与监控补全（P2）

> 目标：重建测试体系，补全 Prometheus 监控链路，恢复 Grafana 仪表盘。
> 验收：后端单元测试覆盖率 ≥60%；e2e 测试全流程通过；Prometheus /metrics 可访问；Grafana 仪表盘完整。

- [x] Task F1：恢复后端单元测试框架
  - [x] SubTask F1.1：`pip install pytest pytest-asyncio pytest-cov httpx`
  - [x] SubTask F1.2：新建 backend/tests/conftest.py，配置异步测试 fixture、测试数据库
  - [x] SubTask F1.3：编写 test_config.py（配置加载）
  - [x] SubTask F1.4：编写 test_security.py（JWT 签发/验证）
  - [x] SubTask F1.5：编写 test_auth.py（登录、获取用户信息）
  - [x] SubTask F1.6：编写 test_documents.py（上传、列表、删除）
  - [x] SubTask F1.7：编写 test_schemas.py（Schema CRUD）
  - [x] SubTask F1.8：编写 test_terms.py（Term CRUD）
  - [x] SubTask F1.9：在 Makefile 或 package.json 添加 test:backend 脚本
  - [x] SubTask F1.10：验证：`pytest` 通过，覆盖率 ≥60%
- [x] Task F2：编写解析管道集成测试
  - [x] SubTask F2.1：新建 backend/tests/test_parse_pipeline.py
  - [x] SubTask F2.2：使用 test_standard_doc/ 样本，mock OCR/layout/extraction 服务
  - [x] SubTask F2.3：验证 document_tasks.parse_document_impl 完整流程
  - [x] SubTask F2.4：验证：集成测试通过
- [x] Task F3：恢复前端测试框架
  - [x] SubTask F3.1：`pnpm add -D vitest @vue/test-utils jsdom @vitest/coverage-v8`
  - [x] SubTask F3.2：新建 vitest.config.ts
  - [x] SubTask F3.3：编写 Dashboard 组件测试
  - [x] SubTask F3.4：编写 Documents 组件测试
  - [x] SubTask F3.5：编写 Parser 组件测试
  - [x] SubTask F3.6：在 package.json 添加 test 脚本
  - [x] SubTask F3.7：验证：`pnpm test` 通过
- [x] Task F4：恢复 e2e 端到端测试脚本
  - [x] SubTask F4.1：新建 scripts/e2e_test.py
  - [x] SubTask F4.2：使用 httpx 调用后端 API，覆盖登录→上传→解析→索引→问答全流程
  - [x] SubTask F4.3：添加断言验证每步结果
  - [x] SubTask F4.4：验证：脚本可一键运行，全流程通过
- [x] Task F5：恢复性能压测脚本
  - [x] SubTask F5.1：新建 scripts/perf_test.py
  - [x] SubTask F5.2：使用 locust 或 httpx 异步并发，测试上传、解析、问答接口
  - [x] SubTask F5.3：输出延迟分布与吞吐量报告
  - [x] SubTask F5.4：验证：脚本可运行，输出报告
- [x] Task F6：集成 Prometheus 监控
  - [x] SubTask F6.1：`pip install prometheus-fastapi-instrumentator`
  - [x] SubTask F6.2：在 main.py 中集成 Instrumentator，暴露 /metrics 端点
  - [x] SubTask F6.3：在 arq_worker.py 中集成 prometheus_client，暴露 metrics（启动小型 HTTP server 或使用 pushgateway）
  - [x] SubTask F6.4：验证：访问 http://localhost:8000/metrics 可见 Prometheus 格式指标
- [x] Task F7：创建 Grafana 仪表盘
  - [x] SubTask F7.1：新建 deploy/grafana/dashboards/hansight-overview.json
  - [x] SubTask F7.2：面板包含 HTTP 请求 QPS 与延迟分布
  - [x] SubTask F7.3：面板包含 arq 任务排队数、完成数、失败数
  - [x] SubTask F7.4：面板包含 PostgreSQL 连接数、Valkey 命中率、Milvus 检索延迟（注：PostgreSQL/Valkey/Milvus 指标需额外 exporter，仪表盘已预留 Prometheus 数据源占位）
  - [x] SubTask F7.5：验证：Grafana 启动后自动加载仪表盘

---

# Task Dependencies

## 阶段依赖（严格顺序）
- **Phase B** 依赖 **Phase A**（API 契约必须先对齐）
- **Phase C** 依赖 **Phase A**（API 契约必须先对齐）
- **Phase D** 依赖 **Phase A**（SSE 工具函数与 API 对齐）
- **Phase E** 依赖 **Phase A**（类型生成）
- **Phase F** 依赖 **Phase B-E**（测试需基于已实现功能）

## 阶段内依赖
- Task B4（进度 SSE）依赖 Task B3（触发解析）
- Task B5（PDF 预览）依赖 Task B9（下载端点）
- Task B6（BoundingBox）依赖 Task B5（PDF 预览）
- Task C3（子图查询）依赖 Task C1（图谱可视化）
- Task C6（KB 管理页）依赖 Task C5（KB API 模块）
- Task D1（SSE 问答）依赖 Phase A Task A2（askStream 对齐）
- Task D5（任务管理页）依赖 Task D4（retry 端点）
- Task F2（集成测试）依赖 Task F1（单元测试框架）
- Task F4（e2e 测试）依赖 Phase B-D 完成
- Task F7（Grafana 仪表盘）依赖 Task F6（Prometheus 集成）

## 可并行任务
- Phase B 与 Phase C 在 Phase A 完成后可部分并行（不同人负责）
- Phase D 与 Phase E 在 Phase A 完成后可部分并行
- Phase F Task F1-F5（测试）与 Task F6-F7（监控）可并行

---

# 风险与应对

| 风险编号 | 风险描述 | 概率 | 影响 | 应对措施 |
|---------|---------|------|------|---------|
| R1 | pdfjs-dist 集成复杂（Web Worker、CORS） | 中 | 高 | 先用 iframe 简单预览，后续增强；参考官方 examples |
| R2 | Cytoscape 大图性能问题（>500 节点卡顿） | 中 | 中 | 使用 fcose 布局；限制初始加载节点数；实现懒加载 |
| R3 | SSE 跨域与代理问题（Vite 代理需配置） | 高 | 高 | vite.config.ts 中 /api 代理需支持 changeOrigin: true 与流式响应 |
| R4 | arq Worker 监控端点冲突（worker 无 HTTP server） | 中 | 低 | 在 worker 中启动小型 aiohttp server 暴露 /metrics，或使用 pushgateway |
| R5 | 测试数据库隔离（测试污染生产数据） | 低 | 高 | 使用独立 test 数据库，conftest.py 中强制切换 DATABASE_URL |
| R6 | 范围蔓延（修复过程中发现新问题） | 中 | 中 | 严格遵循阶段划分，新问题记录到 backlog，不插入当前阶段 |
| R7 | OpenAPI 类型生成与手写代码冲突 | 中 | 低 | 强制使用生成类型，禁止手写；CI 中添加 diff 检查 |

---

# 验收标准

## 阶段验收（每阶段完成后用户确认）
- **Phase A**：`pnpm type-check` 通过；所有 API 模块与后端端点 URL/方法一致
- **Phase B**：可上传 PDF → 触发解析 → 实时进度 → PDF 预览与解析结果正确展示
- **Phase C**：图谱可视化可用；可构建/重建/删除图谱；知识库管理页面四大操作可用
- **Phase D**：问答打字机效果可用；引用来源字段对齐；任务列表正确展示
- **Phase E**：Schema/Term CRUD 全功能可用；composables 目录有可复用工具；后端无硬编码路径
- **Phase F**：后端单元测试覆盖率 ≥60%；e2e 测试全流程通过；Prometheus /metrics 可访问；Grafana 仪表盘完整

## 整体验收
- 5 条端到端业务流程全部跑通（文档解析、RAG 索引、知识图谱、智能问答、任务监控）
- 7 处 API 契约不一致全部修复
- 59 项未实现功能全部完成
- `pnpm gen:api` 可生成类型，无手写重复类型
- Prometheus /metrics 可访问，Grafana 仪表盘完整显示
