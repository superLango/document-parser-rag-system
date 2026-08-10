# 文档解析开发方案（阶段：PDF-Extract-Kit + GLM-OCR）

> 依据：[MAINFLOW_PLAN.md](MAINFLOW_PLAN.md) 决策 D1-D10，尤其 **D8**：
> 以 PDF-Extract-Kit 为底层框架（保留 PDF→图片、页眉页脚擦除、DocLayout-YOLO 版面分析、
> 阅读顺序、Markdown 拼装），在其识别分支处**统一拦截替换为 GLM-OCR**
> （替代 UniMERNet 公式、StructEqTable 表格、PaddleOCR 正文）。
> 文中 **⚠️【待确认 U?】** 为需用户拍板的内容，汇总见第 12 节。

## 1. 目标与范围

1. 在重构版（React + FastAPI + PG/MinIO/Redis）中落地“文档上传 → 解析 → 版面重建 → 结构化 Markdown 产物”，
   作为后续分块索引、结构化抽取、图谱、问答的基础。
2. 解析以**知识库为隔离边界**：文档数据全部 RLS 隔离，任务/产物按 KB 物理与逻辑隔离（MinIO bucket + PG RLS）。
3. 本期不实现：分块索引、结构化抽取、图谱、问答（后续阶段）。

## 2. 决策基线（引用主流程方案）

| 决策 | 内容 |
|------|------|
| D1 | KB RLS 隔离，知识库为入口 |
| D2/D3 | 主库/向量/图均为 PostgreSQL（本期向量/图未用，仅预留） |
| D4 | MinIO 对象存储（每 KB bucket） |
| D5 | Redis + arq 队列强化（Outbox/幂等/重试/死信/心跳） |
| D6 | LLM 兼容层（GLM-OCR 属于 VLM/OCR 专用通道，单独封装） |
| D8 | PDF-Extract-Kit 为底 + GLM-OCR 替换识别分支 |
| D10 | 认证：最新认证体系（RBAC + API Key + 审计） |

## 3. 总体流水线

```
上传（API + MinIO）
   │  创建 documents 记录（RLS）
   ▼
任务编排（PG outbox → Redis/arq）
   ▼
阶段 A：PDF → 高清图片（保留 PDF-Extract-Kit）
   ▼
阶段 B：页眉页脚擦除（保留）
   ▼
阶段 C：DocLayout-YOLO 版面分析（保留）→ 版面框（标题/正文/表格/公式/图）
   ▼
阶段 D：阅读顺序排序（保留）
   ▼
阶段 E：Markdown 拼接拼装（保留）
   │
   ┌────────────── 识别分支拦截（替换）──────────────┐
   │ 正文块 → GLM-OCR   表格块 → GLM-OCR   公式块 → GLM-OCR │
   └──────────────────────────┬────────────────────┘
   ▼
阶段 F：版面重建/后处理（迁移旧版 Popo：跨页表格合并/标题重建/图文关联）⚠️【待确认 U8】
   ▼
阶段 G：产物落库 + MinIO（页面 markdown、layout.json、图片块）
   │
   └─→ 后续阶段消费：分块索引 / 结构化抽取 / 图谱 / 问答
```

## 4. 组件矩阵（保留 / 替换 / 新增 / 待确认）

| 组件 | 来源 | 处理 | 说明 |
|------|------|------|------|
| PDF → 图片 | PDF-Extract-Kit | **保留** | 渲染器与 DPI ⚠️【U2】 |
| 页眉页脚擦除 | PDF-Extract-Kit | **保留** | 是否需要企业规则增强 ⚠️【U3】 |
| DocLayout-YOLO 版面分析 | PDF-Extract-Kit | **保留** | 权重与部署形态 ⚠️【U4】 |
| 阅读顺序排序 | PDF-Extract-Kit | **保留** | 与旧版 Popo 顺序算法择一 ⚠️【U5】 |
| Markdown 拼接拼装 | PDF-Extract-Kit | **保留** | 输出规范对齐 ⚠️【U9】 |
| 正文 OCR | 原 PaddleOCR 分支 | **替换 → GLM-OCR** | OCRBackend 拦截 |
| 表格识别 | 原 StructEqTable 分支 | **替换 → GLM-OCR** | 复杂跨页合并 ⚠️【U8】 |
| 公式识别 | 原 UniMERNet 分支 | **替换 → GLM-OCR** | 是否保留 UniMERNet 兜底 ⚠️【U7】 |
| 兜底 OCR | PaddleOCR | **待确认** | GLM-OCR 不可用时是否回退 ⚠️【U13】 |
| 版面重建后处理 | 旧版 popo/ | **迁移** | normalizer/tree_builder/markdown_renderer |
| 文档/任务模型 | 新建 | **新增** | documents/tasks/outbox/dead_letter，RLS |
| 任务编排 | arq + Redis | **新增（按 D5）** | Outbox + 幂等 + 重试 + 心跳 |

## 5. 数据模型（新表，全部 KB 表启用 RLS）

```
documents
  id, kb_id, filename, file_type, file_size, object_key, sha256,
  status(queued/parsing/completed/failed),
  process_status(queued/rendering/layout/ocr/rebuild/completed/failed),
  page_count, markdown_path, layout_path, error, created_at, updated_at, deleted_at   [RLS]

tasks
  id, kb_id, task_id, type(document_parse), status, attempts, heartbeat_at,
  checkpoint(jsonb), error, created_at, updated_at                                    [RLS]

task_outbox
  id, task_id, type, payload(jsonb), created_at, enqueued_at, error                   [全局]

task_dead_letter
  id, task_id, type, error, attempts, created_at                                       [全局]
```

- 所有 KB 表执行 `ENABLE ROW LEVEL SECURITY`，策略函数复用 §4.1（`app.current_kb` + `kb_effective_role`）。
- MinIO 键规范：`kb-{id}/originals/{task_id}/{filename}`、`kb-{id}/ocr/{task_id}/pages/`、
  `kb-{id}/ocr/{task_id}/result.md`、`kb-{id}/ocr/{task_id}/layout.json`。

## 6. 模块设计

### 6.1 文档上传与文件管理（MinIO）

- 端点：`POST /kb/{kb_id}/documents`（multipart；权限：editor+ ⚠️【U15】）。
- 流程：校验文件类型/大小 ⚠️【U15】→ 计算 sha256 → 写 `documents`（status=queued）→ 上传 MinIO →
  写 `task_outbox`（事务内）→ 返回 `document_id/task_id`。
- 文件类型支持范围 ⚠️【U10】：默认仅 PDF（旧版还有图片/其他），docx 是否本期支持待确认。

### 6.2 任务编排（D5 落地）

- 沿用主流程方案：业务事务写 `task_outbox` → dispatcher 入队 arq → worker 执行。
- 状态机：`queued → rendering → layout → ocr → rebuild → completed/failed`，
  每阶段更新 `process_status` 与 `checkpoint`（断点续跑）。
- 幂等：`task_id` 作为 arq job id + Redis SETNX 去重；重复执行以 checkpoint 跳过已完成阶段。
- 重试/死信/心跳：见 MAINFLOW_PLAN §4.5。

### 6.3 PDF-Extract-Kit 集成层

- **引入方式** ⚠️【U1】：建议 **vendor 目录（只读参考）或 Git 子模块锁定 commit**，不直接 pip 依赖，
  便于对“识别分支”做拦截改造；也可源码拷贝到 `backend/app/services/parsekit/`。
- 依赖项（以最终确认版本为准）：PyMuPDF/PDFium（渲染）、torch/onnxruntime（DocLayout-YOLO）、
  PDF-Extract-Kit 自带版面/顺序/拼装模块。
- 目录建议：`backend/app/services/parsekit/`（渲染、擦除、版面、顺序、拼装、intercept）。
- 组件接口：
  - `render_pdf(pdf_bytes, dpi) -> list[page_image]`
  - `erase_header_footer(page_image, layout_boxes) -> page_image`
  - `layout_analyze(page_image) -> list[LayoutBox{type,bbox,order,confidence}]`
  - `sort_reading_order(boxes) -> list[LayoutBox]`
  - `assemble_markdown(blocks) -> str`
- 每步输出落盘 `pages/` 与 `layout.json`（含 box 坐标，供 GLM-OCR 裁剪与后续索引使用）。

### 6.4 OCRBackend 拦截层（GLM-OCR 替换）

- 在拼装前增加统一接口：

```
OCRBackend
  ocr_block(image_block: bytes, block_type: text|table|formula) -> str(markdown_fragment)
  └─ GLMOCRBackend（默认）
       POST {GLMOCR_SERVER_URL}（现有 vLLM 9977 兼容接口，端点/模型可配）
       输入：裁剪图片块（PNG/JPEG）
       输出：文本/Markdown 片段
```

- 拦截实现：`parsekit/intercept.py` 在调用 UniMERNet/StructEqTable/PaddleOCR 的位置统一改为
  `ocr_block(...)`；原分支代码**不注册**（或保留为 `legacy` 开关，默认关闭）⚠️【U13】。
- 并发控制：页面并行 × 块并行（默认 4 × 8，可配 ⚠️【U11】）+ GLM-OCR 侧限流；
  失败块重试 2 次，仍失败标记 `ocr_failed` 不阻塞整页。
- GLM-OCR 调用方式与图片块尺寸上限 ⚠️【U6】。
- 公式兜底 ⚠️【U7】：默认 GLM-OCR；如需保留 UniMERNet 作为可配兜底，将作为独立 fallback 实现。

### 6.5 版面重建/后处理（旧版 Popo 迁移）

- 迁移文件：`popo/normalizer.py`、`popo/tree_builder.py`、`popo/markdown_renderer.py`、
  `popo/popo_inference.py` → `backend/app/services/rebuild/`。
- 能力：跨页表格合并、标题层级重建、图文关联、结构树输出。
- 是否本期包含跨页表格合并 ⚠️【U8】（建议包含，属于领域关键能力）。

### 6.6 输出产物规范（对下游承诺）

- `result.md`：结构化 Markdown（含标题层级、表格、公式占位、图片引用）。
- `layout.json`：版面框列表（type/bbox/order/confidence + 对应图片块 key）。
- `pages/*.png`：页面图与裁剪块（供预览/调试）。
- 与旧版五维分块字段兼容性 ⚠️【U9】：建议 layout.json 同时输出
  `path/title/type/structural` 所需信息，避免下一阶段返工。

## 7. API 设计（草稿，待评审）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/kb/{kb_id}/documents` | editor+（待确认 U15） | 上传并创建解析任务 |
| GET | `/kb/{kb_id}/documents` | viewer+ | 文档列表（分页/搜索） |
| GET | `/kb/{kb_id}/documents/{doc_id}` | viewer+ | 文档详情与状态 |
| GET | `/kb/{kb_id}/documents/{doc_id}/markdown` | viewer+ | 解析结果 Markdown |
| GET | `/kb/{kb_id}/documents/{doc_id}/layout` | viewer+ | 版面 JSON |
| POST | `/kb/{kb_id}/documents/{doc_id}/reparse` | editor+ | 重新解析（幂等） |
| DELETE | `/kb/{kb_id}/documents/{doc_id}` | editor+ | 删除文档与产物 |
| GET | `/kb/{kb_id}/tasks` | viewer+ | 任务列表（复用后续任务页） |

- 全部端点走 `require_not_pending` + `get_kb_context`（RLS 激活）。
- 审计：上传、重新解析、删除留痕。
- 公开一体化接口（旧版 `public_extraction`）是否本期恢复 ⚠️【U16】。

## 8. 错误处理与降级

| 场景 | 行为 |
|------|------|
| PDF 损坏/不可渲染 | 任务 failed，documents.status=failed，记录 error；可重新上传 |
| GLM-OCR 超时/500 | 块级重试 2 次；仍失败标记 ocr_failed（整页不中断） |
| GLM-OCR 服务整体不可用 | 任务进入重试队列；是否回退 PaddleOCR ⚠️【U13】 |
| Redis 不可用 | 上传仍写 outbox，接口 503 提示稍后自动执行（不丢单） |
| worker 被杀 | 心跳超时回收，任务重新调度，checkpoint 续跑 |
| 单页失败 | 页面级失败不影响其他页，最终标记 partial（可选）⚠️【U11】 |

## 9. 测试方案（铁律五层）

| 层 | 内容 |
|----|------|
| L1 单元 | 渲染/擦除/版面框排序/OCRBackend 接口/markdown 拼装/outbox 幂等 |
| L2 集成 | 上传→任务→解析→产物落库全链路（真实 PDF 样本） |
| L3 功能 | 前端：文档页面上传、进度、结果预览、重新解析、删除（E2E） |
| L4 边界 | 大文件/空 PDF/损坏 PDF/并发上传/重复提交/GLM-OCR 超时注入/断点续跑 |
| L5 安全 | 非成员访问 403、越权删除、RLS 绕过、文件类型绕过、MinIO 键注入 |

- 评测指标（**指标集待确认 ⚠️【U12】**，推荐）：
  - 页面 OCR 正确率（抽样人工标注）；
  - 表格还原率（Markdown 表格与原文结构一致性）；
  - 标题层级准确率；
  - 版面框检出率/误检率（DocLayout-YOLO 基线）；
  - 整页任务成功率与平均耗时（GPU 实测）。
- 样本集：企业真实 PDF 样本（材料检测标准等）**待确认**数量与来源。

## 10. 迁移映射（旧版 → 新版）

| 旧版文件 | 新版位置 | 处理 |
|----------|----------|------|
| `services/ocr/ocr_service.py`、`ocr_config.py` | `services/parsekit/` + `services/ocr_backend/glmocr.py` | 拆分：版面/渲染沿用，OCR 走新拦截层 |
| `services/popo/*` | `services/rebuild/*` | 迁移并适配新 layout.json |
| `tasks/document_tasks.py`、`process_tasks.py` | `tasks/document_tasks.py`（新版） | 重写为 outbox + 状态机 + checkpoint |
| `api/v1/endpoints/kb_documents.py` | `api/v1/endpoints/kb/documents.py` | 按新权限/RLS 重写 |
| `models/document.py` | `models/document.py`（新版） | 新表结构 + RLS |
| `schemas/document.py` | `schemas/document.py`（新版） | 新响应字段 |
| `public_extraction.py` | 视 U16 决定 | 待确认 |

## 11. 里程碑

| 里程碑 | 内容 | 出口标准 |
|--------|------|----------|
| M1 | 数据模型 + 上传/任务骨架（outbox/arq/RLS） | 上传与任务状态 E2E 通过 |
| M2 | PDF-Extract-Kit 集成（渲染/擦除/版面/顺序/拼装） | 样本 PDF 产出 layout.json + markdown |
| M3 | GLM-OCR 拦截层 + 并发/重试 | 三类图块均走 GLM-OCR，指标达标（U12） |
| M4 | Popo 后处理迁移 + 产物落库 | 结构化 Markdown + 预览 |
| M5 | 前端文档页（列表/上传/进度/结果/重解析/删除） | E2E + 五层测试通过 |
| M6 | 评测与调优（U12） | 指标门禁通过，可进入分块索引阶段 |

## 12. 待确认清单（请逐条确认）

| 编号 | 事项 | 推荐值 |
|------|------|--------|
| U1 | PDF-Extract-Kit 引入方式与版本 | vendor 子模块/源码拷贝并锁定 commit |
| U2 | PDF→图片渲染器与 DPI | PyMuPDF（现有）或 PDFium；DPI 默认 200 ⚠️ 待定 |
| U3 | 页眉页脚擦除规则 | 先沿用 PDF-Extract-Kit 内置，后按企业样本增强 |
| U4 | DocLayout-YOLO 部署形态与权重版本 | 本地 PyTorch/ONNX，权重版本待锁定 |
| U5 | 阅读顺序算法 | 优先 PDF-Extract-Kit，对比旧版 Popo 后确定 |
| U6 | GLM-OCR 调用方式与图片块尺寸上限 | 现有 vLLM 9977 兼容接口；尺寸上限待实测 |
| U7 | 公式兜底 | 默认 GLM-OCR；是否保留 UniMERNet 可配 |
| U8 | 跨页表格合并（Popo）本期是否实现 | 建议包含 |
| U9 | layout.json/markdown 是否对齐旧版五维分块字段 | 建议对齐，避免返工 |
| U10 | 支持文件类型范围 | 默认仅 PDF；docx/图片待确认 |
| U11 | 并发参数与单页失败策略 | 页 4 × 块 8；单页失败标记不中断（可配） |
| U12 | 评测指标集与阈值、样本集 | 按 §9 推荐集，数量/阈值待确认 |
| U13 | GLM-OCR 不可用时是否回退 PaddleOCR | 建议不自动回退（保留 legacy 开关） |
| U14 | 中间产物保留与清理策略 | 建议 7 天后清理 pages/裁剪块，保留 result.md/layout.json |
| U15 | 上传权限与文件大小限制 | editor+；上限建议 100MB（企业内可调） |
| U16 | 公开一体化接口是否本期恢复 | 建议本期不做，文档解析阶段后评估 |
