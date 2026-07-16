# Hansight 未实现功能系统性修复 Spec

## Why

经对项目全部文档资料（README、tasks.md、spec、checklist、API 契约、迁移计划）与实际代码的系统性对照分析，识别出 59 项未实现或功能不完整的问题点，覆盖前端 UI 占位、前后端 API 契约不一致、后端监控缺失、测试体系完全删除、5 条端到端业务流程断裂等多个层面。当前前端功能完整度仅约 30%，所有核心交互功能（文档上传、解析触发、图谱可视化、SSE 流式、任务管理）均为占位符或完全缺失，导致系统虽后端能力齐备但用户无法通过 UI 完成任何端到端业务操作。本 Spec 旨在系统性修复全部已识别问题，使系统达到可交付、可验收的生产可用状态。

## What Changes

### 契约对齐与基础设施层（Phase A）
- 修复 7 处前后端 API 契约不一致（document.ts、qa.ts、task.ts）
- 安装缺失前端依赖（pdfjs-dist、highlight.js、openapi-typescript）
- 建立 OpenAPI 类型自动生成机制，替代手写类型
- **BREAKING**：移除 document.ts 的 parse/update 方法、task.ts 的 cancel 方法

### 文档解析全链路打通（Phase B）
- 实现文档上传功能（替换空 handleUpload 函数）
- 实现文档删除、触发解析入口
- 实现任务进度 SSE 实时推送（新建 useTaskProgress 组合式函数）
- 集成 pdfjs-dist 实现 PDF 预览
- 实现 BoundingBox 版面区域叠加
- 实现原始文本、结构化数据、抽取数据 Tab 真实内容展示
- 后端新增文档下载端点

### 知识图谱与 RAG 索引入口（Phase C）
- 集成 Cytoscape.js 实现图谱可视化（替换占位符）
- 实现图谱构建/重建/删除操作入口
- 实现子图查询、节点详情面板、图统计展示
- 新建知识库管理页面（views/KnowledgeBase/）
- 新建知识库 API 模块（api/modules/knowledgeBase.ts）

### 智能问答与任务管理（Phase D）
- 实现 SSE 流式问答（替换非流式 ask 调用）
- 对齐引用来源字段（document_id/chunk_id/content/score/source）
- 实现 Markdown 渲染与代码高亮
- 新建任务管理页面（views/Tasks/）

### CRUD 补全与规范修复（Phase E）
- 补全 Schema CRUD（编辑、删除、启用/停用、详情）
- 补全 Term CRUD（创建、编辑、删除、批量导入、分类下拉）
- 实现术语人工审核队列
- 创建 composables 工具函数（useSSE、usePagination）
- 修复后端 llm_service 硬编码模型路径
- 启用 term_base_id 按库过滤

### 测试体系与监控补全（Phase F）
- 恢复后端单元测试框架与核心测试
- 编写解析管道集成测试
- 恢复前端测试框架与组件测试
- 恢复 e2e 端到端测试脚本
- 恢复性能压测脚本
- 集成 Prometheus 监控（/metrics 端点）
- 创建 Grafana 仪表盘 JSON 文件

## Impact

- Affected specs: 全系统（前端 UI、前端 API 层、后端端点、测试、监控、部署）
- Affected code:
  - 前端：`frontend/src/views/` 全部页面、`frontend/src/api/modules/` 全部模块、`frontend/src/components/`、`frontend/src/composables/`、`frontend/package.json`
  - 后端：`backend/app/main.py`（Prometheus）、`backend/app/api/v1/endpoints/documents.py`（下载端点）、`backend/app/api/v1/endpoints/tasks.py`（retry 端点）、`backend/app/services/llm_service.py`（配置项）、`backend/app/services/term_service.py`（term_base_id）、`backend/app/core/config.py`（LLM_MODEL_PATH）、`backend/app/tasks/arq_worker.py`（metrics）
  - 测试：`backend/tests/`（重建）、`frontend/src/__tests__/`（重建）、`scripts/e2e_test.py`、`scripts/perf_test.py`
  - 部署：`deploy/grafana/dashboards/`（新增 JSON）、`deploy/docker-compose.yml`（Prometheus 依赖）
- Affected docs: `tasks.md`、`checklist.md`、`README.md`（功能更新）

---

## ADDED Requirements

### Requirement: 前后端 API 契约一致性

系统 SHALL 保持前端 API 模块与后端端点的 URL、HTTP 方法、请求体、响应体完全一致，且通过 OpenAPI 自动生成类型确保同步。

#### Scenario: API 模块与端点对齐
- **GIVEN** 前端 `api/modules/` 下任意 API 模块
- **WHEN** 调用某方法（如 `taskApi.submit`）
- **THEN** 该方法 SHALL 调用后端实际存在的端点（如 `POST /tasks/`）
- **AND** HTTP 方法与请求体结构 SHALL 与后端定义一致
- **AND** 不存在前端调用但后端未实现的端点

#### Scenario: OpenAPI 类型自动生成
- **WHEN** 后端 API 定义更新
- **THEN** 运行 `pnpm gen:api` SHALL 从后端 `/openapi.json` 生成前端类型到 `src/api/types.ts`
- **AND** 前端 API 调用 SHALL 使用生成的类型，禁止手写重复类型

### Requirement: 文档上传功能

系统 SHALL 提供文档上传 UI，支持拖拽与点击两种方式上传 PDF 文件。

#### Scenario: 成功上传
- **GIVEN** 用户在文档管理页面
- **WHEN** 拖拽 PDF 文件到上传区或点击选择文件
- **THEN** 系统 SHALL 弹出元信息填写对话框（标题、文档类型、标准号）
- **AND** 用户确认后 SHALL 调用 `POST /documents/` 上传
- **AND** 上传成功后 SHALL 刷新文档列表

#### Scenario: 文件校验失败
- **WHEN** 用户上传超过大小限制或不支持类型的文件
- **THEN** 系统 SHALL 显示错误提示（el-message）
- **AND** 不发起上传请求

### Requirement: 文档解析触发与进度推送

系统 SHALL 提供触发文档解析的 UI 入口，并通过 SSE 实时推送解析进度。

#### Scenario: 触发解析
- **GIVEN** 用户在文档管理或解析查看页面
- **WHEN** 点击"开始解析"并选择 Schema（可选）
- **THEN** 系统 SHALL 调用 `POST /tasks/` 提交解析任务
- **AND** 返回 task_id 后 SHALL 开始监听 `GET /tasks/{id}/stream` SSE 流

#### Scenario: 进度实时展示
- **WHEN** 解析任务执行中
- **THEN** UI SHALL 显示进度条（0-100%）
- **AND** 进度更新通过 SSE 实时推送，无需轮询
- **AND** 任务完成（status=completed）后 SHALL 自动刷新文档详情

### Requirement: PDF 预览与 BoundingBox 叠加

系统 SHALL 在解析查看页面左栏渲染真实 PDF 内容，并叠加版面区域识别框。

#### Scenario: PDF 渲染
- **GIVEN** 用户在解析查看页面
- **WHEN** 文档存在且已加载
- **THEN** 左栏 SHALL 使用 pdfjs-dist 渲染 PDF 所有页面
- **AND** 支持分页导航与缩放控制

#### Scenario: 版面区域叠加
- **WHEN** 文档已解析（含 layout_data）
- **THEN** PDF 上 SHALL 叠加 SVG/Canvas 层绘制 bbox 矩形
- **AND** 不同区域类型（text/table/figure/title/header/footer）SHALL 用不同颜色区分
- **AND** 鼠标悬停 SHALL 显示区域类型与置信度 tooltip

### Requirement: 知识图谱 Cytoscape 可视化

系统 SHALL 使用 Cytoscape.js 渲染知识图谱节点与关系，替换当前占位符。

#### Scenario: 图谱渲染
- **GIVEN** 用户在知识图谱页面
- **WHEN** 图谱数据加载完成（nodes + edges 非空）
- **THEN** SHALL 使用 Cytoscape.js 渲染网络图
- **AND** 节点按 label 分色，边按 relation 类型分色
- **AND** 节点可拖拽，鼠标悬停高亮

#### Scenario: 子图查询
- **WHEN** 用户点击某节点
- **THEN** SHALL 调用 `GET /kg/subgraph?entity={name}` 获取子图
- **AND** 更新视图显示该节点周边 N 跳邻居
- **AND** 侧边栏 SHALL 显示节点详情（label、properties、关联关系）

### Requirement: SSE 流式问答

系统 SHALL 通过 SSE 流式接收 LLM 生成的回答，实现打字机效果。

#### Scenario: 流式回答
- **GIVEN** 用户在智能问答页面
- **WHEN** 提交问题
- **THEN** 系统 SHALL 调用 `POST /qa/stream` 发起 SSE 请求
- **AND** 答案消息 SHALL 先创建空内容，逐 chunk 追加文本
- **AND** 流结束（done 事件）后 SHALL 显示完整引用来源

#### Scenario: 引用来源字段对齐
- **WHEN** 显示引用卡片
- **THEN** SHALL 使用后端 Citation 字段：document_id、chunk_id、content、score、source
- **AND** 不使用前端臆造的字段（如 document_title、page）

### Requirement: 任务管理页面

系统 SHALL 提供独立的任务管理页面，展示所有解析、索引、图谱构建任务的状态。

#### Scenario: 任务列表
- **GIVEN** 用户在任务管理页面
- **WHEN** 页面加载
- **THEN** SHALL 调用 `GET /tasks/` 分页查询任务列表
- **AND** 表格 SHALL 展示 task_id、document_id、status、progress、created_at
- **AND** 支持按状态筛选

#### Scenario: 失败任务重试
- **WHEN** 用户点击失败任务的"重试"按钮
- **THEN** SHALL 调用 `POST /tasks/{id}/retry` 重新提交任务
- **AND** 新任务出现在列表中

### Requirement: 知识库管理页面

系统 SHALL 提供知识库管理页面，支持文档入索引、移除、重建索引操作。

#### Scenario: 索引管理
- **GIVEN** 用户在知识库管理页面
- **WHEN** 页面加载
- **THEN** SHALL 显示统计卡片（total_chunks、total_docs、indexed_docs、completed_docs）
- **AND** 文档表格 SHALL 显示每个文档的索引状态与操作按钮
- **AND** 可触发单个文档索引、移除、重建全部索引

### Requirement: Prometheus 监控集成

系统 SHALL 暴露 Prometheus 格式的指标端点，供 Prometheus 采集。

#### Scenario: 后端指标暴露
- **GIVEN** 后端 FastAPI 服务运行中
- **WHEN** 访问 `GET /metrics`
- **THEN** SHALL 返回 Prometheus 格式指标
- **AND** 指标 SHALL 包含 HTTP 请求 QPS、延迟分布、状态码分布

#### Scenario: Grafana 仪表盘
- **GIVEN** Grafana 启动
- **WHEN** 用户访问 Grafana
- **THEN** SHALL 自动加载 Hansight 仪表盘
- **AND** 仪表盘 SHALL 包含 backend、arq-worker、PostgreSQL、Valkey、Milvus、Neo4j 面板

### Requirement: 测试体系恢复

系统 SHALL 恢复完整的测试体系，覆盖单元测试、集成测试、端到端测试。

#### Scenario: 后端单元测试
- **WHEN** 运行 `pytest`
- **THEN** SHALL 覆盖 config、security、auth、documents、schemas、terms 模块
- **AND** 覆盖率 SHALL ≥ 60%

#### Scenario: e2e 测试
- **WHEN** 运行 `python scripts/e2e_test.py`
- **THEN** SHALL 覆盖登录→上传→解析→索引→问答全流程
- **AND** 所有断言 SHALL 通过

---

## MODIFIED Requirements

### Requirement: 文档管理页面

原 spec Task 6.5 要求"上传区 + 文件列表 + 分页"，现补充：
- 上传功能 SHALL 真实实现（替换空 handleUpload）
- 文档表格 SHALL 新增"删除"操作
- 文档表格 SHALL 新增"开始解析"操作（调用 POST /tasks/）

### Requirement: 解析查看页面

原 spec Task 6.6 要求"双栏 PDF预览 + 识别框 + 结果面板"，现明确：
- 左栏 SHALL 使用 pdfjs-dist 渲染真实 PDF（非占位符）
- 左栏 SHALL 叠加 BoundingBox（来自 layout_data）
- 右栏"原始文本"Tab SHALL 读取 document.parsed_text
- 右栏"结构化"Tab SHALL 读取 document.structured_data
- 右栏"抽取数据"Tab SHALL 展示完整抽取结果（非仅元数据）
- 顶部 SHALL 显示任务进度（SSE 实时推送）

### Requirement: 知识图谱页面

原 spec Task 6.9 要求"GraphViewer Cytoscape"，现明确：
- SHALL 真正集成 Cytoscape.js（非占位符）
- SHALL 提供构建/重建/删除图谱操作入口
- SHALL 实现子图查询与节点详情面板
- SHALL 展示图统计信息

### Requirement: 智能问答页面

原 spec Task 6.10 要求"ChatWindow + SourceCard + SSE流式接收"，现明确：
- SHALL 使用 POST /qa/stream SSE 流式（非 GET EventSource）
- SHALL 实现 Markdown 渲染与代码高亮
- 引用来源字段 SHALL 与后端 Citation 对齐

---

## REMOVED Requirements

### Requirement: 前端会话历史与列表
**Reason**: 后端 qa.py 未实现 `/qa/conversations` 与 `/qa/conversations/{id}/messages` 端点，且会话持久化非核心功能
**Migration**: 当前每次刷新清空消息的行为保留；会话功能移至后续迭代

### Requirement: 任务取消功能
**Reason**: arq 不原生支持任务取消
**Migration**: task.ts 移除 cancel 方法；UI 不提供取消按钮

### Requirement: 前端 PUT /documents/{id} 编辑
**Reason**: 后端未实现，且文档元信息编辑非高优先级
**Migration**: document.ts 移除 update 方法；编辑功能移至后续迭代
