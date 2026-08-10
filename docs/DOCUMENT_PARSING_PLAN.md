# 文档解析开发方案（阶段：PDF-Extract-Kit + GLM-OCR）

> 依据：[MAINFLOW_PLAN.md](MAINFLOW_PLAN.md) 决策 D1-D10，尤其 **D8**。
> 本文档已吸收用户对 U1-U16 的确认（见 §2），并将里程碑细化为**阶段性开发方案**（§11）。
> 实施期仍需实测/待定的参数（如 GLM-OCR 图块上限、评测阈值）单独标注为“实施期确定”。

## 1. 目标与范围

1. 在重构版中落地“文档上传 → 解析 → 版面重建 → 结构化 Markdown 产物”，作为分块索引、
   结构化抽取、图谱、问答的基础。
2. 以知识库为隔离边界：文档/任务全 RLS，MinIO 按 KB bucket 分键。
3. 本期不实现：分块索引（U9 确认暂缓，但产物字段预留）、结构化抽取、图谱、问答、
   公开一体化接口（U16 确认暂缓）、跨页表格合并（U8 确认暂缓，记录为后续需求）。

## 2. 决策记录（U1-U16 已确认）

| 编号 | 事项 | 确认结果 |
|------|------|----------|
| U1 | PDF-Extract-Kit 引入方式 | **vendor 子模块/源码拷贝并锁定 commit** |
| U2 | PDF 渲染器与 DPI | **PyMuPDF；DPI=200**（实施期可按 GPU/质量微调） |
| U3 | 页眉页脚擦除 | **双方案**：方案 A 内置（默认）、方案 B 样本增强（迭代）（见 §6.3） |
| U4 | DocLayout-YOLO 部署形态与版本 | **本地 PyTorch/ONNX，权重版本锁定** |
| U5 | 阅读顺序算法 | **PDF-Extract-Kit 实现** |
| U6 | GLM-OCR 调用方式 | **现有 vLLM 9977 兼容接口**；图片块尺寸上限实施期实测 |
| U7 | 公式识别 | **GLM-OCR**，不引入 UniMERNet |
| U8 | 跨页表格合并（Popo） | **本期不做，记录为后续需求** |
| U9 | 分块入库 | **本期不做**；layout.json 预留 path/title/type/structural 信息供后续 |
| U10 | 支持文件类型 | **仅 PDF**（图片/docx 后续评估） |
| U11 | 并发与单页失败策略 | **页并发 4 × 块并发 8**；单页失败标记不中断（参数可配） |
| U12 | 评测指标集 | **采用 §9 推荐指标集**；样本数量/阈值实施期确定 |
| U13 | GLM-OCR 失败兜底 | **不回退、不保留开关**：直接记录错误并标记失败 |
| U14 | 中间产物保留 | **7 天清理 pages/裁剪块**，保留 result.md/layout.json |
| U15 | 上传权限与大小 | **editor+；上限 100MB** |
| U16 | 公开一体化接口 | **本期不做**，后续评估 |

## 3. 总体流水线

```
上传（API + MinIO）→ documents 记录（RLS）
  → 任务编排（PG outbox → Redis/arq）
  → 阶段 A：PDF → 高清图片（PyMuPDF，DPI=200）
  → 阶段 B：页眉页脚擦除（方案 A 内置 / 方案 B 样本增强）
  → 阶段 C：DocLayout-YOLO 版面分析 → 版面框
  → 阶段 D：阅读顺序排序（PDF-Extract-Kit）
  → 阶段 E：Markdown 拼接拼装（PDF-Extract-Kit）
  → 识别分支拦截：正文/表格/公式 → GLM-OCR（U7/U13）
  → 阶段 F：版面重建/后处理（Popo 迁移；跨页表格合并暂缓 U8）
  → 阶段 G：产物落库（result.md / layout.json / pages）
  →（后续阶段）分块索引 / 结构化抽取 / 图谱 / 问答
```

## 4. 组件矩阵（按确认结果更新）

| 组件 | 处理 | 说明 |
|------|------|------|
| PDF → 图片（PyMuPDF，DPI=200） | 保留 | U2 |
| 页眉页脚擦除 | 双方案 | U3-A 内置 / U3-B 样本增强（§6.3） |
| DocLayout-YOLO 版面分析 | 保留 | U4，本地部署 |
| 阅读顺序排序 | 保留（PDF-Extract-Kit） | U5 |
| Markdown 拼接拼装 | 保留 | U5 |
| 正文 OCR | 替换 → GLM-OCR | U6 |
| 表格识别 | 替换 → GLM-OCR | 跨页合并暂缓 U8 |
| 公式识别 | 替换 → GLM-OCR | U7，无 UniMERNet |
| OCR 兜底 | **无** | U13：失败即记录错误，任务标记 failed/partial |
| 版面重建后处理 | 迁移旧版 popo | 排除跨页表格合并（U8 记录） |
| 文档/任务模型 | 新增 | documents/tasks/outbox/dead_letter，RLS |
| 任务编排 | 新增（D5） | Outbox + 幂等 + 重试 + 心跳 |

## 5. 数据模型（新表，KB 表启用 RLS）

```
documents
  id, kb_id, filename, file_type, file_size, object_key, sha256,
  status(queued/parsing/completed/failed),
  process_status(queued/rendering/layout/ocr/rebuild/completed/failed/partial),
  page_count, markdown_path, layout_path, error(jsonb), created_at, updated_at, deleted_at   [RLS]

tasks
  id, kb_id, task_id, type(document_parse), status, attempts, heartbeat_at,
  checkpoint(jsonb), error, created_at, updated_at                                           [RLS]

task_outbox
  id, task_id, type, payload(jsonb), created_at, enqueued_at, error                           [全局]

task_dead_letter
  id, task_id, type, error, attempts, created_at                                               [全局]
```

- MinIO 键：`kb-{id}/originals/{task_id}/{filename}`、`kb-{id}/ocr/{task_id}/pages/`、
  `kb-{id}/ocr/{task_id}/result.md`、`kb-{id}/ocr/{task_id}/layout.json`。
- 中间产物（pages/裁剪块）保留 7 天（U14），`result.md`/`layout.json` 长期保留。

## 6. 模块设计

### 6.1 文档上传与文件管理（MinIO）

- `POST /kb/{kb_id}/documents`（multipart；editor+，≤100MB，U15；仅 PDF，U10）。
- 流程：sha256 → documents(queued) → MinIO 上传 → outbox（事务内）→ 返回 document_id/task_id。

### 6.2 任务编排（D5）

- 事务性 outbox → dispatcher → arq；状态机
  `queued → rendering → layout → ocr → rebuild → completed/failed/partial`。
- 幂等：task_id 作 arq job id + Redis SETNX；checkpoint 断点续跑；重试/死信/心跳按主流程方案。

### 6.3 PDF-Extract-Kit 集成与页眉页脚擦除（U3 双方案）

**引入**（U1）：vendor 子模块或源码拷贝，锁定 commit；目录
`backend/app/services/parsekit/`（render、erase、layout、order、assemble、intercept）。

**页眉页脚擦除双方案**：

- **方案 A：内置（默认）**
  - 直接使用 PDF-Extract-Kit 内置页眉页脚擦除逻辑（版面框过滤 + 规则）。
  - 零定制、可快速上线；适合大部分标准 PDF。
- **方案 B：样本增强（迭代）**
  - 收集企业真实 PDF 样本（材料检测/标准等），人工标注页眉页脚区域；
  - 建立可配置规则集：按版面框位置（顶部/底部固定区）、字号/字体、重复内容模式、
    页码格式、页眉横线等；规则存 `kb_config`/系统配置；
  - 内置结果与规则结果做 A/B 对比，按样本准确率迭代；
  - 阶段内先以方案 A 上线，方案 B 在样本集到位后作为增强迭代（实施期确定启动时间）。

### 6.4 OCRBackend 拦截层（GLM-OCR，U6/U7/U13）

```
OCRBackend.ocr_block(image_block, block_type: text|table|formula) -> str
  └─ GLMOCRBackend（唯一实现）
       POST {GLMOCR_SERVER_URL}（现有 vLLM 9977 兼容接口）
       输入：裁剪图片块；输出：文本/Markdown 片段
```

- 拦截点：`parsekit/intercept.py` 在 UniMERNet/StructEqTable/PaddleOCR 调用处统一替换为
  `ocr_block(...)`；原分支代码不注册、不保留开关（U13）。
- 公式走 GLM-OCR（U7），无 UniMERNet。
- **失败语义（U13）**：块级失败重试 2 次；仍失败 → 记录 `error`（块类型/页码/原因），
  任务按策略标记 `failed` 或 `partial`；**不回退其他 OCR、不提供开关**。
- 并发：页 4 × 块 8（U11）+ GLM-OCR 侧限流；图片块尺寸上限实施期实测（U6）。

### 6.5 版面重建/后处理（旧版 Popo 迁移，U8 暂缓项记录）

- 迁移：`popo/normalizer.py`、`tree_builder.py`、`markdown_renderer.py` → `services/rebuild/`。
- 本期实现：标题层级重建、图文关联、结构树输出。
- **U8 记录（后续需求）**：跨页表格合并暂缓；在 `documents.layout_path` 中保留
  `table_cross_page` 标记字段，后续阶段据此做合并，不影响本期 schema 演进。

### 6.6 输出产物规范（U9 暂缓项记录）

- `result.md`：结构化 Markdown。
- `layout.json`：版面框列表（type/bbox/order/confidence + 图片块 key），并**预留**
  `path/title/type/structural` 字段（U9：本期不分块入库，但字段对齐避免返工）。
- `pages/*.png`：页面图与裁剪块（7 天清理）。

## 7. API 设计（草稿）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| POST | `/kb/{kb_id}/documents` | editor+ | 上传 PDF 并创建解析任务（≤100MB） |
| GET | `/kb/{kb_id}/documents` | viewer+ | 文档列表 |
| GET | `/kb/{kb_id}/documents/{doc_id}` | viewer+ | 详情与状态 |
| GET | `/kb/{kb_id}/documents/{doc_id}/markdown` | viewer+ | result.md |
| GET | `/kb/{kb_id}/documents/{doc_id}/layout` | viewer+ | layout.json |
| POST | `/kb/{kb_id}/documents/{doc_id}/reparse` | editor+ | 重新解析（幂等） |
| DELETE | `/kb/{kb_id}/documents/{doc_id}` | editor+ | 删除文档与产物 |
| GET | `/kb/{kb_id}/tasks` | viewer+ | 任务列表 |

全部走 `require_not_pending` + `get_kb_context`（RLS）；上传/重解析/删除审计留痕。

## 8. 错误处理与降级（按 U13 更新）

| 场景 | 行为 |
|------|------|
| PDF 损坏/不可渲染 | 任务 failed，记录 error |
| 单块 GLM-OCR 失败（重试 2 次后） | 记录块级 error；任务 failed 或 partial（按配置，U11） |
| GLM-OCR 服务整体不可用 | 任务 failed，记录“OCR 服务不可用”；**不回退、无开关（U13）** |
| Redis 不可用 | 上传仍写 outbox；接口 503 提示稍后自动执行 |
| worker 被杀 | 心跳超时回收，checkpoint 续跑 |
| 单页失败 | 页面级失败不影响其他页，最终 partial（可配，U11） |

## 9. 测试方案（铁律五层）

| 层 | 内容 |
|----|------|
| L1 单元 | 渲染/擦除（A/B）/版面框排序/OCRBackend/拼装/outbox 幂等/错误记录 |
| L2 集成 | 上传→任务→解析→产物全链路（真实 PDF 样本） |
| L3 功能 | 前端：上传、进度、结果预览、重解析、删除（E2E） |
| L4 边界 | 大文件/空 PDF/损坏 PDF/并发上传/重复提交/GLM-OCR 注入失败/断点续跑 |
| L5 安全 | 非成员 403、越权删除、RLS 绕过、类型绕过、MinIO 键注入 |

评测指标（U12 推荐集；样本数量/阈值实施期确定）：OCR 页面正确率、表格还原率、
标题层级准确率、版面框检出/误检率、任务成功率与平均耗时。

## 10. 迁移映射（旧版 → 新版）

| 旧版文件 | 新版位置 | 处理 |
|----------|----------|------|
| `services/ocr/ocr_service.py`、`ocr_config.py` | `services/parsekit/` + `services/ocr_backend/glmocr.py` | 拆分重构 |
| `services/popo/*` | `services/rebuild/*` | 迁移（排除跨页表格合并） |
| `tasks/document_tasks.py`、`process_tasks.py` | `tasks/document_tasks.py` | 重写为 outbox+checkpoint |
| `api/v1/endpoints/kb_documents.py` | `api/v1/endpoints/kb/documents.py` | 按新权限/RLS 重写 |
| `models/document.py`、`schemas/document.py` | 新版对应文件 | 新表 + 新响应 |

## 11. 阶段性开发方案（Phase 1-6）

> 每个阶段完成即按铁律五层测试，评审通过后再进入下一阶段。

### Phase 1：数据与任务骨架

- 目标：上传→任务闭环可跑通（解析内容为桩）。
- 交付：
  - documents/tasks/outbox/dead_letter 表 + RLS 迁移；
  - 上传接口 + MinIO 分桶；outbox dispatcher + arq worker；
  - 任务状态机与 checkpoint；文档列表/详情/删除 API；
  - 前端：文档页（上传/列表/状态/删除）基础版。
- 验收：上传 PDF 后任务状态流转正确；杀 worker 不丢单；RLS 集成测试通过；E2E 通过。

### Phase 2：PDF-Extract-Kit 集成

- 目标：样本 PDF 能完成“渲染→擦除（方案 A）→版面→顺序→拼装”，产出 layout.json + markdown。
- 交付：parsekit 模块、DocLayout-YOLO 本地部署与权重锁定、内置擦除方案 A 上线。
- 验收：≥10 份企业样本 PDF 全部产出合法产物；版面框检出率达标（U12 实施期阈值）；
  五层测试通过。

### Phase 3：GLM-OCR 拦截层

- 目标：正文/表格/公式图块全部走 GLM-OCR。
- 交付：OCRBackend + GLMOCRBackend、并发（页4×块8）、块级重试与错误记录（U13）。
- 验收：三类图块抽样人工核对正确率；GLM-OCR 注入失败场景按 U13 语义记录并失败；
  五层测试通过。

### Phase 4：后处理与产物落库

- 目标：结构化 Markdown + layout.json（含 U9 预留字段）落库/落 MinIO。
- 交付：rebuild 模块（标题层级/图文关联）、页面预览产物、7 天清理任务（U14）。
- 验收：产物字段契约测试；清理任务验证；跨页表格合并标记字段落位（U8 记录）；
  五层测试通过。

### Phase 5：前端完整化

- 目标：文档解析页全功能（上传/进度/结果预览/重新解析/删除）。
- 交付：文档列表卡片或表格、上传弹窗（≤100MB、PDF 校验）、进度展示、
  结果 Markdown 预览、layout 调试视图（可后置）、重解析/删除。
- 验收：E2E 全流程通过；控制台无错误、无横向溢出；移动端适配。

### Phase 6：评测与调优

- 目标：按 U12 指标集收敛质量。
- 交付：评测样本集与脚本（`qa/evaluation/`）、指标报告、
  页眉页脚方案 B（样本增强）原型（如样本到位）。
- 验收：指标门禁通过；输出评测报告；满足条件后进入分块索引阶段。

## 12. 实施期待定参数（非用户决策，实测确定）

| 参数 | 说明 |
|------|------|
| GLM-OCR 图片块尺寸上限（U6） | Phase 3 实测 |
| 页/块并发实际最优值 | 默认页4×块8（U11），按 GPU 实测调整 |
| 评测样本数量与阈值（U12） | Phase 2/6 随样本确定 |
| 页眉页脚方案 B 启动时间（U3） | 样本集到位后评估 |
