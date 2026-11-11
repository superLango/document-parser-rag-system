# M2 里程碑详细执行计划：OCR 服务与表格结构算法

> 文档版本：v1.2  
> 编制日期：2026-11-11  
> 计划周期：2026-12-03 ~ 2026-12-16  
> 主责角色：项目负责人（兼算法/后端）  
> 协作角色：外部模型服务器管理员（按需）、业务/领域专家（按需）  
> 上游依据：[架构重构方案](architecture-refactor-plan.md)、[项目需求文档](requirements.md)、[整体开发计划](development-plan.md)、[项目决策记录](decision-log.md)  
> 前置里程碑：[M0](M0-project-scaffold.md)、[M1](M1-core-domain-orchestration.md)  
> 当前状态：进行中（核心链路已落地；金标语料与 GLM 联调待补）

---

## 1. 里程碑目标

建立真实 OCR 服务与可复现的表格结构算法：

- OCR 适配 GLM / PDF / Mock。
- 页图、版面、表格结构、质量评估产出。
- 表格 cell graph、rowspan/colspan 归一化、声明式修复规则、表型识别。
- 建立表格算法基准，决定“重写”还是“复制重构”。

## 2. 范围与不做

### 2.1 范围

| 项 | 内容 |
|---|---|
| OCR 适配 | GLM OCR、PDF 原生、Mock |
| 页图 | PDF 渲染、页图存储 |
| 版面 | Layout 服务适配、blocks、bbox |
| 表格结构 | HTML/OCR 表格 → CellGraph → TableGrid |
| 表格修复 | 数据驱动修复规则、签名匹配、回归用例 |
| 表型识别 | 化学/力学/检验/尺寸/分类/admin 等 |
| 质量评估 | OCR 质量分、告警 |
| 基准 | 表格字段/记录/证据/覆盖率、确定性、延迟 |

### 2.2 不做

- 不做矩阵抽取（M3/M5 后续）。
- 不做条款抽取（M5 后续）。
- 不做 Schema 投影（M5 后续）。
- 不实现配方匹配。
- 不实现沙箱。
- 不实现前端页面。

## 3. 前置依赖

| 依赖 | 说明 |
|---|---|
| M0 完成 | 服务骨架、contracts、CI |
| M1 完成 | 编排可调用 OCR 阶段 |
| OCR 服务地址 | 模型服务器上的 GLM/Layout；地址与版本参考旧代码（Q1） |
| 模型操作位置 | 所有模型部署/启停/调参在模型服务器执行（D-002） |
| 金标语料 | 表格样本 + 期望 TableGrid/记录 |
| 旧算法基线 | 旧 `tablegrid` 指标作为参考 |
| 业务规则 | 表型/列角色确认（外部支持） |

## 4. 交付物

| # | 交付物 | 路径 | 形式 | 验收人 |
|---|---|---|---|---|
| D2.1 | OCR 服务 | `services/ocr/` | 服务 | 架构/QA |
| D2.2 | OCR 适配器 | `services/ocr/adapters/` | 代码 | 架构 |
| D2.3 | 页图/版面产物 | 对象存储 + `pages.json` | 产物 | QA |
| D2.4 | TableGrid 契约实现 | `packages/contracts` + `services/ocr/algorithms/table_grid.py` | 代码 | 架构 |
| D2.5 | 表格修复规则 | `services/ocr/data/table_repairs.json` | 数据 | 业务/QA |
| D2.6 | 表型识别 | `services/ocr/algorithms/table_profile.py` | 代码 | 算法 |
| D2.7 | 算法基准报告 | `new_app/docs/reports/M2-table-benchmark.md` | 报告 | PM/架构 |
| D2.8 | 测试 | `new_app/tests/algorithm/table/` | 测试 | QA |
| D2.9 | OCR 失败处理 | 错误码/降级 | 代码 | QA |

## 5. 工作分解（WBS）

| 编号 | 任务 | 主责 | 协作 | 产出 | 计划完成 |
|---|---|---|---|---|---|
| M2-01 | OCR 契约与适配器接口 | 架构 | 算法/后端 | OcrPort | 2026-12-03 |
| M2-02 | GLM/PDF/Mock 适配 | 算法 | 后端 | 适配器 | 2026-12-05 |
| M2-03 | 页图渲染与存储 | 算法 | DevOps | 页图产物 | 2026-12-07 |
| M2-04 | Layout 适配与 blocks | 算法 | 后端 | 版面产物 | 2026-12-08 |
| M2-05 | CellGraph + GridNormalizer | 算法 | 架构 | 表格核心 | 2026-12-10 |
| M2-06 | 声明式修复规则 | 算法 | 业务专家 | 规则 + 用例 | 2026-12-11 |
| M2-07 | 表型识别与原因 | 算法 | 业务专家 | profile 代码 | 2026-12-12 |
| M2-08 | 质量评估与失败处理 | 算法 | QA | 质量分/错误码 | 2026-12-13 |
| M2-09 | 基准测试与对比 | QA/算法 | 架构 | 基准报告 | 2026-12-15 |
| M2-10 | 与编排集成 | 后端 | 算法 | OCR 阶段真实调用 | 2026-12-16 |

## 6. 接口与契约

### 6.1 OcrPort

```python
class OcrPort(Protocol):
    def parse(self, request: OcrRequest) -> OcrResult: ...
```

`OcrResult` 至少包含：

- `pages`：页号、页图 URI、宽高、DPI。
- `markdown_uri`。
- `layout_uri`。
- `tables`：`TableGrid` 列表。
- `quality`：0–1。
- `warnings`。
- `artifacts`。

### 6.2 TableGrid

```python
class TableGrid(BaseModel):
    table_id: str
    page_no: int
    caption: str | None
    profile: str
    orientation: str
    n_rows: int
    n_cols: int
    header_paths: list[list[str]]
    header_rows: int
    units: list[str]
    rows: list[list[str]]
    blocks: list[TableBlock]
    bbox: list[float] | None
```

### 6.3 修复规则

```json
{
  "rule_id": "...",
  "match": {"standard_no": "...", "table_caption": "..."},
  "action": {"type": "rebuild_grid", "columns": 16, "rows": 16},
  "cases": ["tests/algorithm/table/...json"]
}
```

## 7. 算法重写策略

### 7.1 默认方案

- 复制旧 `tablegrid/parser.py`、`repairs.py`、`profile.py` 的验证逻辑到 `new_app/services/ocr/algorithms/`。
- 去掉 pipeline/settings 依赖。
- 重写为纯函数 + 类型契约。
- 记录 PROVENANCE。

### 7.2 允许重写

如果新实现满足以下条件，可替换旧实现：

- CellGraph + GridNormalizer 更简单、可单测。
- 修复规则数据化，新增表型不改代码。
- 基准指标不低于旧基线。

### 7.3 回退条件

- Field/Record F1 下降 >0.01。
- 任一金标文档指标下降 >0.02。
- 确定性失败。
- 延迟超过旧基线 1.2×。

回退到“复制重构”实现，不阻塞 M3。

## 8. 验收标准

### 8.1 功能

- [ ] OCR 服务可处理 `.pdf` 和 `.md`。
- [ ] 页图、版面、表格结构产物完整。
- [ ] `TableGrid` 通过 schema 校验。
- [ ] 表格修复规则可命中指定样本。
- [ ] 表型识别输出 profile + 原因。
- [ ] OCR 失败返回稳定错误码。
- [ ] OCR 模型地址/版本来自配置；模型操作在模型服务器执行（Q1）。

### 8.2 算法质量

| 指标 | 门槛 |
|---|---|
| 表格 Record F1 | ≥ 旧基线 |
| 表格 Field F1 | ≥ 旧基线 |
| 证据命中 | ≥ 旧基线 |
| 单文档下降 | ≤0.01 |
| 确定性 | 同输入输出哈希一致 |
| 延迟 | ≤旧基线 1.2× |
| 表格对齐错误 | 不高于旧基线 |

### 8.3 工程质量

- [ ] 表格算法单元测试覆盖核心分支。
- [ ] 基准测试可重复运行。
- [ ] 无旧包 import。
- [ ] 所有产物有 sha256。
- [ ] 日志包含 table_id/page_no/rule_id。

### 8.4 文档

- [ ] OCR 服务 README。
- [ ] TableGrid 字段说明。
- [ ] 修复规则格式说明。
- [ ] 基准报告（含失败样本）。
- [ ] PROVENANCE 记录。

## 9. 时间节点

| 节点 | 日期 | 标志 |
|---|---|---|
| K2.1 OCR 契约冻结 | 2026-12-03 | 评审通过 |
| K2.2 OCR 适配可用 | 2026-12-07 | 真实 PDF 出页图/版面 |
| K2.3 表格核心可用 | 2026-12-11 | TableGrid 产出 |
| K2.4 修复/表型可用 | 2026-12-13 | 样本通过 |
| K2.5 基准报告 | 2026-12-15 | 指标达标/回退决策 |
| K2.6 验收 | 2026-12-16 | 集成通过 |

## 10. 风险与应对

| 风险 | 应对 |
|---|---|
| OCR 服务不稳定 | Mock 优先；重试/降级；测试环境隔离 |
| 表格重写指标下降 | 基准门槛；回退复制重构 |
| 跨页/rowspan 复杂 | CellGraph 中间产物；逐表用例 |
| 修复规则过拟合 | 规则需覆盖多文档；禁止只对单文档 |
| 页面图像存储过大 | 压缩/生命周期；对象存储 |
| GPU/模型资源不足 | OCR 服务独立部署；限流 |

## 11. 出口准则与回滚

**出口准则**

- OCR 服务可被编排调用。
- 表格指标达标或已回退到复制重构。
- 基准报告签字。
- QA/架构/PM 验收。

**回滚**

- OCR 阶段可切回 M1 的 fake OCR。
- 表格算法可切回复制重构版本。
- 不影响 M3 配方注册。

## 12. 关联文档

- [架构重构方案](architecture-refactor-plan.md)
- [整体开发计划](development-plan.md)
- 上一里程碑：[M1](M1-core-domain-orchestration.md)
- 下一里程碑：[M3 配方注册中心](M3-recipe-registry.md)

## 13. 变更记录

| 版本 | 日期 | 变更 | 变更人 |
|---|---|---|---|
| v1.0 | 2026-11-11 | 初版 | 项目负责人 |
| v1.1 | 2026-11-11 | 补充 Q1 模型服务器/版本、Q8 单人角色 | 项目负责人 |
| v1.2 | 2026-11-11 | 记录 M2 执行结果：OCR 适配器、TableGrid 算法、表型与修复规则、编排集成 | 项目负责人 |

---

## 14. 执行记录（2026-11-11）

### 14.1 已完成

| 项 | 结果 |
|---|---|
| OCR 契约 | `services/ocr/contracts.py`：`OcrRequest`/`OcrResult`/`Page`/`TableGrid`/`TableBlock`/`Merge`/`ArtifactRef` |
| 适配器 | `text`（md/txt）、`pdf`（PyMuPDF 渲染页图 + 文本/表格）、`glm`（OpenAI 兼容多模态）、`mock`、`auto` 工厂 |
| 表格算法 | `normalize.py`、`table_grid.py`（rowspan/colspan、表头路径、跨页合并、分块）、`profile.py`、`repairs.py` |
| 修复规则 | `services/ocr/data/table_repairs.json`，支持 `rebuild_grid`/`header_rows`/`patch_cells`/`replace_rows`/`delete_rows`/`trim_trailing` |
| 产物 | 页图 PNG、markdown、pages.json、tables.json、ocr.json，均记录 sha256/bytes |
| OCR API | `POST /internal/ocr/parse`（对象存储读取）、`POST /internal/ocr/parse-file`（直传） |
| 错误码 | `OCR_BACKEND_UNAVAILABLE`/`OCR_BACKEND_ERROR`/`OCR_PDF_INVALID`/`OCR_EMPTY_DOCUMENT`/`OCR_UNKNOWN_BACKEND` |
| 编排集成 | OCR 阶段调用真实服务；`OCR_USE_FAKE=true` 可回退 M1 fake |
| 共享存储 | `services/shared/storage.py` 供 orchestration 与 ocr 共用 |
| 测试 | `tests/algorithm/table/test_table_grid.py` 5 个用例 |
| 基准 | `scripts/benchmark/table_benchmark.py`；报告见 [M2-table-benchmark](reports/M2-table-benchmark.md) |
| 文档 | `services/ocr/README.md`、`PROVENANCE.md` 已记录算法来源 |

### 14.2 验证证据

| 验证 | 结果 |
|---|---|
| Markdown + HTML 表格 | `backend=text`，识别 T1：`mechanical_properties`，3 行 3 列，header_paths 正确，4 个产物 |
| PDF 原生渲染 | `backend=pdf`，1 页，页图 `ocr/pdfcheck/pages/1.png`，markdown 正常 |
| 编排端到端（K8s） | 上传 fixture → `STRUCTURED_READY`；artifacts 含 `markdown.md`/`pages.json`/`tables.json`/`ocr.json` 及 run 级产物 |
| Compose | 全部容器 Healthy；`18002/internal/ocr/parse-file` 返回完整 `OcrResult` |
| 算法单测 | 5 passed |
| 基准 | 平均 1.45 ms、p95 1.91 ms、50 次输出哈希一致 |
| Ruff | 通过 |

### 14.3 未完成与限制

- [ ] GLM 适配器未联调：`192.168.1.35:9977`、`192.168.188.75:9977`、公网地址均不可达，`auto` 当前走 `text`/`pdf`。
- [ ] 版面（layout blocks）未实现：PDF 原生只输出页与文本；GLM 恢复后再补 layout 适配。
- [ ] 金标语料与旧基线指标未建立：基准报告仅覆盖本地 fixture。
- [ ] 矩阵/条款抽取、Schema 投影按计划留给 M3/M5。

