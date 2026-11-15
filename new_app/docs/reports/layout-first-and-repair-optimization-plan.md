# 版面优先 + 配方矩阵 + 审核修复闭环优化方案

> 日期：2026-11-12
> 性质：方案设计，本次不改代码
> 目标：同时提升“有产物”和“字段抽对”，并让审核真正驱动配方/解析修复

## 0. 先回答六个疑问

### Q1：新项目为什么会直接处理 PDF？OCR 层不应该先版面分析再 OCR 吗？

**新项目并不是完全不 OCR，而是顺序和粒度与旧项目不同：**

- 新项目 `HybridOcrAdapter` 先判断文本层是否可读：
  - 可读 → `PdfOcrAdapter` 直接用 pymupdf 抽文本和 `find_tables()`；
  - 不可读 → `GlmOcrAdapter` 把**整页图片**送 GLM，一次性输出整页 Markdown/HTML。
- 版面分析 `_run_layout` 是 OCR **之后**的可选步骤，而且 `layout_only_for_vision=True` 让原生文本 PDF 直接跳过版面；版面服务当前又不可达。
- 旧项目 `ocr/glm.py` 的路径是明确的 **PDF → 版面分析 → 按 block 裁剪 → 分块 GLM-OCR → 组装 Markdown**：
  - 标题/表格/公式/图片说明分别识别；
  - 文本 block 优先用文本层，但用 `COMMON_CJK` 常用字比例过滤乱码；
  - 表格 block 单独走表格 OCR，有独立并发槽；
  - 页面失败才回退整页文本层。

所以差异不是“新项目不 OCR”，而是：

| 维度 | 旧项目 | 新项目当前 |
|---|---|---|
| 版面分析 | OCR 前，驱动 block 裁剪 | OCR 后，仅附加 layout 元数据 |
| OCR 粒度 | 按 block 类型 | 整页一次 |
| 文本层使用 | 按 block 选择性使用 | 整篇/整页切换 |
| 表格 | 表格 block 单独识别 | 整页 HTML 后统一解析 |
| 失败回退 | 页面级 → 文本层 | GLM 失败 → native |

**结论：新项目应改成“版面优先、block 路由、文本层按块复用”的 OCR 流程。** 这不是简单把 `_run_layout` 调到前面，而是让 layout 成为 OCR 的驱动器。

### Q2：新项目不应该也通过不同配方、矩阵等解析逻辑完成解析吗？

**应该，而且当前只做了一半。**

- 新项目有 recipe registry、签名匹配、`builtin.py` 的 binding 主循环，以及元素行/元素列/化学成分兜底。
- 但旧项目对同一张表有 9 类提取器依次兜底：bound matrix、property matrix、grade-property matrix、property rows、grade-property tail、element matrix、hardness minmax、nonrecord 等。
- 新项目缺少“策略链”：表头形态一超出配方假设，就直接 `ROW_KEY_NOT_FOUND` / `MEASURE_COLUMN_MISSING`，然后 0 记录。

**结论：新项目需要“配方 + 矩阵策略链”，但必须在新契约内重写，不直接 import 旧代码。**

### Q3：旧项目资产能用就迁移，但要适配新规范

同意。迁移清单见第 3 节；原则是：

1. 只迁移数据/规则/算法思路，不迁移旧 pipeline、旧 API、旧依赖。
2. 迁移前先按新 `TableGrid`/`Record`/`RecipeManifest` 契约重写。
3. 每条规则必须有正例、变体、反例测试。
4. 文档级硬编码修复必须改成“表签名/文档指纹”匹配，不能按 doc_id 写死。
5. 通过 shadow/candidate 验证后再进 stable。

### Q4：新项目要“既跑出产物，又字段抽取对”

对，当前的问题是“产物有、记录少”：

- 50 份标准全部有 pages/markdown/tables/diagnostics 产物；
- 但只有 11/50 有 records；39 份 records=0。
- 已产出的 533 个字段，牌号/值原文命中 100%，说明“抽出来的字段是对的”，但“该抽的字段没抽出来”。

因此目标要拆成两层指标：

| 层次 | 指标 | 当前 | 目标 |
|---|---|---|---|
| 产物 | 运行成功、pages/markdown/tables/diagnostics | 50/50 | 保持 50/50 |
| 覆盖 | 有 records 的文档 | 11/50 | ≥40/50 |
| 正确 | 牌号/值原文命中 | 100% | ≥99% |
| 正确 | Field F1（60 份） | 0.4933 | 0.60→0.80 |
| 正确 | 静默错误率 | 4.92% | ≤3% |
| 完整 | 单位存在率 | 100% | 100% |
| 完整 | 空记录率 | 0% | ≤1% |

### Q5：我们不是也有修复闭环吗？

**有骨架，但没有接通。** 当前实现：

1. `FeedbackService.create`：人工/前端创建 feedback；
2. `POST /feedback/{id}/process`：运行 `TriageAgent` → `RepairAgent` → 生成 candidate recipe → sandbox 重跑 → `_verify` → verified/needs_more_info；
3. 人工 `POST /feedback/{id}/verify`：approve 后 promote 到 stable，reject 则 discard。

缺口：

- review 不会自动创建 feedback；
- review 规则是记录级的，0 记录不产生 finding，review 结果是 pass；
- `_verify` 要求 `target.measure`，0 记录/漏表没有 measure；
- `RepairAgent` 只改 recipe JSON（`/bindings`、`/signature`、`/rules`、`/templates`、`/compatibility`），不能改表格检测/表头重建/OCR；
- 没有 L1 文档重解析 diff，也没有 L3 代码修复提案；
- 验证只重跑当前文档、只检查一个 measure，没有 50 份标准 + 金标回归。

所以“审核有问题 → 修复 → 重抽取 → 人工审核 → 再修复”的目标是对的，但当前只完成了“人工 feedback → 配方 candidate”这一段。

### Q6：旧资产一样的，我们难道没有吗？新项目现在怎么实现的？

| 旧资产/能力 | 新项目当前实现 | 差距 |
|---|---|---|
| 版面分析驱动 OCR | `LayoutClient` 存在，但 OCR 后才调用；native 跳过 | 未做 layout-first / block 路由 |
| 分块 OCR | `GlmOcrAdapter` 整页 OCR | 未按 block 裁剪、未按类型分流 |
| 表格修复 | `algorithms/repairs.py` + `data/table_repairs.json` | 规则为空；旧有 6 文档/13 表 |
| 多矩阵提取器 | `builtin.py` 主循环 + 元素表/化学成分兜底 | 缺 property/grade-property/tail/hardness/nonrecord 策略 |
| 配方 | `recipe-registry` 7 个配方、版本/通道 | 有配方，但缺策略链和更全条件绑定 |
| 字段别名 | `MEASURE_ALIASES`/`DEFAULT_ROW_KEY`/`CONDITION_TOKENS` 已迁移一部分 | 旧 family/role/method/remark/dimension 未全迁 |
| 业务词典 | `orchestration/dictionary` 已导入 2,203 条 | 未进入 `builtin` 解析主循环 |
| 修复闭环 | feedback/triage/repair/candidate/verify | 手动触发、只修配方、无 L1/L3/回归 |
| 宽 schema | records/evidence | 旧还有 items/clauses/references/coverage；需产品决策 |

## 1. 目标架构：版面优先的 OCR

```text
PDF
 │
 ├─ 渲染页图（DPI 可配）
 │
 ├─ 版面分析（PP-DocLayoutV3 微调，188.75:9978）
 │   └─ blocks: title/text/table/formula/image_caption/footnote...
 │
 ├─ 页级/块级路由
 │   ├─ 文本 block：文本层可用 → 直接取；否则 GLM OCR
 │   ├─ 表格 block：裁剪 → 表格 OCR / 结构模型 → HTML
 │   ├─ 公式/图片/标题：按类型 OCR 或保留
 │   └─ 页面失败：文本层回退 + warning
 │
 ├─ 组装 Markdown / 结构化 blocks
 │
 ├─ TableGrid（HTML → 行列/合并/表头路径）
 │
 ├─ 配方路由 → 矩阵策略链 → records/evidence
 │
 ├─ 文档级质量门禁 → feedback
 │
 └─ 修复闭环：L1 重解析 diff / L2 配方 candidate / L3 代码提案
```

关键原则：

- **版面是 OCR 的前置驱动**，不是 OCR 后的附加元数据。
- **文本层按 block 复用**，不是整篇信任或整篇放弃。
- **表格 block 独立识别**，避免整页模型把表格和正文混在一起。
- **表格识别失败可回退**：表格 OCR → 结构模型 → 文本层坐标。

## 2. 配方 + 矩阵策略链

### 2.1 策略链

在现有 `services/sandbox/runtime/` 内增加内部策略模块（不新增微服务）：

| 顺序 | 策略 | 适用表 | 来源 |
|---|---|---|---|
| 1 | `bound_matrix` | 配方绑定明确、行列固定 | 现有 `builtin` 主循环 |
| 2 | `property_matrix` | 性能矩阵 | 旧 `extract_property_matrix` |
| 3 | `grade_property_matrix` | 牌号行 + 性能列 | 旧 `extract_grade_property_matrix` |
| 4 | `property_rows` | 属性-值竖表 | 旧 `extract_property_rows` |
| 5 | `grade_property_tail` | 宽表尾多性能列 | 旧 `extract_grade_property_tail` |
| 6 | `element_matrix` | 元素行/元素列 | 现有元素表 + 旧 `extract_element_matrix` |
| 7 | `chemical_columns` | 无牌号成分表 | 现有 `_parse_chemical_columns` |
| 8 | `hardness_minmax` | 硬度 min/max | 旧 `extract_hardness_minmax` |
| 9 | `nonrecord` | 检验/非记录表 | 旧 `extract_nonrecord` |

策略选择：

- 配方增加 `strategy_chain` 字段；未指定时按 profile 默认链。
- 每个策略返回统一的 `records/evidence/diagnostics`，并带 `quality_score`。
- 第一个达到质量阈值的策略胜出；低质量表不产出记录，避免污染。
- 策略之间做冲突检测：同表多策略产出不一致时，保留高分并记录 `STRATEGY_CONFLICT`。

### 2.2 配方 1.3.0

在现有 `mechanical_properties_v1@1.2.0` 基础上新增：

- `strategy_chain`：bound → property → grade_property → tail → hardness。
- 更全条件绑定：壁厚、交货状态、产品形式、取样方向、试验温度、表面状态。
- 字段字典：HB/HBW、HRC/HV、RP0.2/ReL、KU2/KV2 的别名与对比映射（输出保留原始符号，报告可归一化）。
- 版本流程：shadow → candidate → stable；保留 1.2.0 回滚。

## 3. 旧资产迁移清单

| 资产 | 旧位置 | 新落点 | 适配要求 | 验证 |
|---|---|---|---|---|
| 表格修复规则 | `legacy/metal-doc-agent/configs/table_repairs.json`（6 文档/13 表） | `services/ocr/data/table_repairs.json` | 用表签名/文档指纹匹配，禁止 doc_id 硬编码 | 每条规则对照原文 + 50 份回归 |
| 字段别名/角色关键词 | `configs/column_aliases.json` | `builtin.py` + 配方 manifest | 按新 measure/condition 结构重写 | 单元测试 + 50 份标准 |
| 业务词典 2,203 条 | `business_dictionary.hanson.json` | 解析主循环或审核/路由 | 只用于 canonicalize/别名，不改变记录契约 | 词典命中率 + 回归 |
| 矩阵提取器 | `extraction/matrix.py` | `runtime/strategies/` | 按新 TableGrid/Record 契约重写 | 每策略正例/变体/反例 |
| 硬表修复算子 | `tablegrid/repairs.py`、`selfheal/l2.py` | `ocr/algorithms/repairs.py` | 只保留新支持的 action；补测试 | 规则回放 |
| 修复闭环模式 | `selfheal/l1.py`、`l2.py`、`l3.py`、`codefix.py` | feedback 服务 | 重写为 async 服务；L3 只提案 | 端到端 feedback 测试 |
| 金标/验证语料 | `data/validation-2026-11-06` | `gold-standards` | OCR 后核对，分层采样 | 金标 ≥30 份 |
| schema projection/coverage | 旧 `schema_projection.py`、`coverage.py` | 暂不迁移 | 先确认产品是否需要 items/clauses/coverage | 产品决策 |

## 4. 审核-修复闭环设计

### 4.1 文档级质量门禁

在 review 前增加文档级规则，产生 finding 并自动创建 feedback：

| 规则 | 触发 | 目标 |
|---|---|---|
| `DOC-NO-RECORDS` | records=0 且 tables>0 | 表存在但 0 记录 |
| `DOC-NO-TABLES` | tables=0 且 pages≥N | 表格检测失败 |
| `DOC-LOW-COVERAGE` | 有记录表/可解析表 < 阈值 | 覆盖不足 |
| `DOC-UNBOUND-COLUMNS` | `MEASURE_COLUMN_MISSING` 比例高 | 配方绑定不足 |
| `DOC-DUP-KEYS` | 同牌号同指标重复 > 阈值 | 条件维度缺失 |
| `DOC-UNIT-MISSING` | 数值字段无单位比例 > 阈值 | 单位继承缺失 |

### 4.2 自动 feedback

- review 命中文档级规则 → `FeedbackService.create`：
  - `target.document_id`、`target.table_id`、`target.recipe_id`；
  - 允许没有 `target.measure`；
  - `description` 自动生成“表 T3 存在但 0 记录”。
- 保留人工 feedback 入口。

### 4.3 分层修复

| 层级 | 修复 | 触发 | 验证 |
|---|---|---|---|
| L1 | 文档重解析 + diff | 自动 | 记录增删改、无新增 error |
| L2 | 配方/别名/表修复 candidate | 自动 | 目标表/文档 + 回归集 |
| L3 | 解析代码提案 | 只生成 diff | 策略门禁 + 测试 + 人工审批 |

L3 参考旧 `codefix.py`：只改通用规则、禁止文档/记录/值硬编码、必须带回归测试、默认只提案不自动合并。

### 4.4 验证与晋升

- 目标文档：0 记录 → ≥1 记录；目标表：产出 ≥1 记录；目标字段：出现且值命中。
- 回归：50 份标准 + ≥30 份金标；有记录文档数、F1、静默错误、单位存在率不得回退。
- 晋升：candidate → shadow → stable；失败自动回滚。
- 人工：approve / reject / 补充反馈，形成“审核 → 修复 → 重抽取 → 人工复核 → 再修复”的闭环。

## 5. 分阶段实施

### Phase 0：版面优先 PoC（工作量 S）

- 在 188.75 部署 `/v1/layout` 包装服务。
- 新 OCR 增加 `layout_first` 开关：页图 → layout → block → OCR；native 文本按 block 复用。
- 选 10 份 AMS/ASME 文档验证：正文表检出、block OCR 质量、延迟。
- 门禁：10 份中 ≥6 份检出正文表；现有 11 份有记录文档不退化。

**Phase 0 执行结果（2026-11-12）：**

- 版面服务已部署在 `http://192.168.188.75:9978`，`/healthz` 返回模型 `models/pp_doclayoutv3`、`cuda:0`、权重 `5b76c1ff...`；远程目录 `/home/grainuser/hansonDoc_RAG/layout_api`，启动命令 `backend/.venv/bin/python -m uvicorn layout_api.app:app --host 0.0.0.0 --port 9978`。
- PoC 10 份 0 记录文档：**10/10 检出 table block，62 个 table block，40 个有表页，0 推理错误**；明细见 [layout-first-poc.md](layout-first-poc.md)。
- GLM-OCR 已切到 `http://192.168.188.75:9977/v1`（vLLM，`max-num-seqs 2`），启动脚本补 `PATH` 后 FlashInfer JIT 可用。
- 新增 `LayoutFirstOcrAdapter` 与 `OCR_LAYOUT_FIRST` 开关（默认 false）：
  - 页图 → 版面 block → 文本块复用文本层（bbox 取不到文本时回退 GLM）→ 表格/公式块裁剪送 GLM → 组装 Markdown；
  - 并发按旧项目 `parsekit` 语义：页 4 × 块 4（旧项目两个 semaphore 同时持有，实际生效并发为 4）；
  - 每个块失败重试 2 次并记录 warning，不再静默丢表；
  - 页级超时 600s；OCR 后不再重复调用版面（避免重复 block 与额外延迟）。
- 本轮修复的生产问题：
  1. GLM 请求缺 `max_tokens`，vLLM 按 32768 生成导致单块数分钟；
  2. 表格裁剪依赖 Pillow，镜像缺失导致块 OCR 静默返回空；
  3. httpx 复用被 vLLM 关闭的 keep-alive 连接，请求挂到 180s 超时才失败（表现为“卡住 + 空错误 + 丢表”），现改为每请求新建连接；
  4. 文本层 bbox 为空时整块被丢弃，现回退 GLM。
- 端到端验证（`OCR_LAYOUT_FIRST=true`，GLM 4096 tokens）：

  | 文档 | 页数 | GLM 块 | OCR 耗时 | 表 | 记录 | 状态 |
  |---|---|---|---|---|---|---|
  | ASME SB338-2025.pdf | 10 | 14 | **51.9s** | 11 | 31 | STRUCTURED_READY |
  | ASTM B338-17(2026)--+.pdf | 9 | 9 | **36.7s** | 6 | 34 | STRUCTURED_READY |

  E2E p50 42.3s / p95 56.4s；两份文档 Table 3 的 31 个牌号-性能值逐项与原文核对**全部一致**。
- 遗留问题：
  - ASTM 第 4 页 Table 1（产品分析公差）被当成性能表，产生 3 条 `~` 空属性记录（review 已标 T1-R1~R3）；
  - Table 3 的 9D/9A、18D/18A 两行脚注被剥离后牌号重复，review 报重复键 warning；
  - GLM 服务 `max-num-seqs 2` 是当前吞吐上限，未调整（属模型服务器运维变更，需单独确认）。

### 后续任务决策（2026-11-12）

- 已确认：`OCR_LAYOUT_FIRST` 默认改为 **true**（compose / k8s / .env.example / config 同步）。
- 已确认：GLM 服务参数暂不调整（保持 `max-num-seqs 2`）。
- 已确认：**先进入 Phase 1**，解析链路全部在沙箱 runtime 内改造，保证 agent 修复后可立即使用最新代码。
- 记录待办（本轮不执行）：

| 编号 | 任务/问题 | 说明 |
|---|---|---|
| A | 沙箱记录清理 | 丢弃空属性记录；脚注后缀（9D/9A、18D/18A）并入牌号键，消除重复键 warning |
| C | 文档级质量门禁 + 自动 feedback | 已完成（P2，2026-11-12）：6 条 `DOC-*` 规则 + 自动 feedback + 文档级验证 |
| D | 50 份标准 + 金标批量回归 | 改造后产出新基线报告 |
| E | GLM `--max-num-seqs` 提升 | 需模型服务器授权，暂不调整 |
| F | ASTM 第 4 页 Table 1 误判为性能表 | 由策略链的 `nonrecord`/`chemical` 分支处理 |

### 当前进度快照（2026-11-12）

- 已完成：Phase 0 版面优先；Phase 1 第一批 + **第二批矩阵策略**（`nonrecord`、`grade_property_tail`、`element_matrix` + 配方 1.5.0 + parser 1.0.4）；Phase 2 功能项（文档门禁、自动 feedback、L1 重解析 diff）；**Phase 2 指标治理**（Field F1 0.4860 → 0.6020、静默 5.30% → 2.55%，parser 1.0.13 + 配方 `chemical_element_rows_v1@1.2.0`）；**L3 执行链路**（pinned parser 重跑 + 验证/晋升/回滚，候选 1.0.14 端到端验证）；**规模化回归门禁 v1**（50 份 F1 0.6025 / 静默 2.62%，发布脚本 + 退出码阻断）；资产化 P1–P5（parser 热加载、文档级门禁/自动 feedback、已验收快照与增量补丁、shadow/晋升/回滚、L3 安全闸门）；GLM 网络根因治理（WSL mirrored → NAT + Docker 网段冲突清理）。
- 未完成：
  1. 金标扩到 ≥30 份（现有 legacy 严格校验仅 2/89 合格，需用 accepted_snapshot 累计）；
  2. 历史 0 记录文档的策略命中率统计（`grade_property_tail` / `element_matrix` 尚无真实命中）。
- 执行顺序（已确认）：~~GLM 根因治理~~ → ~~Phase 1 第二批~~ → ~~Phase 2 指标治理~~ → ~~L3 执行链路~~ → ~~规模化回归门禁 v1~~ → **金标扩充 + 策略命中统计**。
- GLM 根因与修复记录：[model-server-glm-ocr.md](../model-server-glm-ocr.md#8-网络稳定性问题与修复2026-11-12)。

### Phase 1：矩阵策略链（工作量 L）

- 将 bound/property/grade-property/tail/element/hardness 策略重写进 `runtime/strategies/`。
- 配方 1.3.0 增加 `strategy_chain` 和条件绑定。
- 迁移 table_repairs 6/13 条，逐条验证。
- 门禁：有记录 ≥40/50；重复键 ≤5；单位 100%；牌号/值命中 ≥99%。

**Phase 1 执行结果（第一批，2026-11-12）：**

- 落点：`services/sandbox/runtime/strategies.py`（解析算法层，随沙箱引擎镜像分发），`builtin.parse_table` 在绑定列解析无记录时按配方 `rules.strategy_chain` 依次兜底；`runtime/Dockerfile` 已加入 `COPY strategies.py`。
- 已迁移策略：
  1. `property_matrix`：性能 × 温度/方向矩阵；
  2. `grade_property_matrix`：牌号行 × 性能列，ksi/MPa 重复列优先 MPa；
  3. `property_rows`：竖向 `Property / Value` 表；
  4. `hardness_minmax`：硬度 min/max（输出 range/≥/≤）。
- 配方：新增 `mechanical_properties_v1@1.3.0`（`rules.strategy_chain`），stable 指针已切换；1.2.0 保留可回滚。
- 两道质量门禁（首轮回归发现误判后补）：
  - 策略只能输出配方 `bindings.measures` 中声明的 measure，避免把元素列当力学指标；
  - 短 ASCII 符号（A/E/ReL/HBW…）必须整词匹配，避免 `Other Elements` 被识别成 `ReL`。
- 测试：新增 `tests/integration/sandbox/test_strategy_chain.py` 7 个用例；sandbox 全量 **26 passed / 4 skipped**，ruff 通过。
- 回归（两份 B338）：2/2 `STRUCTURED_READY`，**65 records / 195 fields / 17 tables / 9 findings**，与接入策略链前完全一致；OCR p50 32.4s、总 p50 40.3s / p95 56.4s，说明策略链未误触发。
- 命中验证（历史 0 记录文档 AMS4108G）：**0 → 2 records / 6 tables**，`STRUCTURED_READY`；记录来自化学成分 min/max 列（`_parse_chemical_columns`），策略链本身未产生额外噪声。
- 遗留运行问题：该文档 OCR 195s，原因是 2 个表格块各经历 2 次 90s 读超时后第 3 次成功。**已于 2026-11-12 定位并修复**：根因是 WSL `networkingMode=mirrored` + Docker 网桥 NAT 间歇丢包，已切换为 NAT 模式，详见 [model-server-glm-ocr.md](../model-server-glm-ocr.md#8-网络稳定性问题与修复2026-11-12)。
- 第二批已完成：`grade_property_tail`、`element_matrix`、`nonrecord`，结果见下。
- 后续资产化与热更新（解析代码不再重建镜像、agent 修复闭环）见独立方案：[algorithm-asset-hot-update-plan.md](algorithm-asset-hot-update-plan.md)。

**Phase 1 执行结果（第二批，2026-11-12）：**

- 新策略（`services/sandbox/runtime/strategies.py`）：
  - `nonrecord`：公差/允许偏差、检验/分类/尺寸 profile、纯尺寸表直接阻断；预解析阶段在 mechanical / chemical profile 下命中公差表时返回 `NONRECORD_TABLE`；
  - `grade_property_tail`：性能值按行右对齐，结合 Rm≥Rp、A/Z∈[0,100]、硬度≥50 的语义评分选择对齐方式，处理 OCR 错列；
  - `element_matrix`：元素名在行、牌号在列的转置化学成分表，输出每个牌号一条记录。
- 配方：新增 `mechanical_properties_v1@1.5.0`（`strategy_chain` 加入 `nonrecord`、`grade_property_tail`、`element_matrix`），stable 已切换，1.3.0 保留可回滚。
- Parser 资产：`parser_core@1.0.4` 已发布并指向 stable（1.0.2/1.0.3 为迭代版本），沙箱热加载，无需重建引擎镜像。
- 回归（改造前后对比）：
  - AMS4108G：2 records / 7 fields，不变；
  - ASME SB338：31 records / 93 fields，不变；
  - ASTM B338：34 records / 102 fields，不变；
  - 三份均 `STRUCTURED_READY`。
- 正向命中：GB/T 3077-2015（热处理困难表）由 125 records / 11 表变为 **122 records / 9 表**；诊断显示 `nonrecord` 阻断 T15/T17/T18/T19，`NONRECORD_TABLE` 阻断 T16，去掉 3 条非记录表伪记录。
- 测试：新增 10 个策略用例；sandbox 全量 **50 passed / 4 skipped**；ruff 通过。
- 遗留：`grade_property_tail`、`element_matrix` 尚无真实文档命中，需继续用历史 0 记录文档统计命中率；table_repairs 的 6 类通用动作已在 OCR `repairs.py` 支持，当前规则文件为空。

### Phase 2：审核质量门禁 + 自动反馈（工作量 M）

- 文档级规则 + 自动 feedback + table/document 级 triage/verify。
- L1 重解析 diff。
- 门禁：0 记录文档能被 review 标记并自动进入 feedback；F1 ≥0.60；静默 ≤3%。

**Phase 2 执行结果（L1 重解析 diff，2026-11-12）：**

- 新增接口：
  - `POST /v1/runs/{run_id}/reparse`：同文档用当前 stable 资产重跑，返回新 run；
  - `GET /v1/runs/{run_id}/diff?against={other_run}`：对比两次 run 的 records/fields/diagnostics/tables。
- 新增 `services/orchestration/rundiff.py`：records added/removed/changed、字段级 before/after（含 value/unit/operator）、diagnostics added/removed、表集合变化。
- 实测 AMS4108G：reparse run `STRUCTURED_READY`；diff 为 **2→2 records、0 字段变化、85→85 diagnostics、表 T2 一致**。
- 测试：新增 6 个 diff 用例并通过；ruff 通过。
- 模型服务器已切换到 `192.168.1.35`（GLM 9977 + layout 9978），AMS/ASTM 回归均 `STRUCTURED_READY`；切换过程中发现并清理了 Docker 网段 `192.168.0.0/20` 与 `192.168.1.0/24` 的路由冲突。
- 60 份效果对比已执行，结果见下。

**Phase 2 指标验收（60 份效果对比，2026-11-12 20:46）：**

| 指标 | 结果 | Phase 2 门槛 | 结论 |
|---|---|---|---|
| Field F1 | 0.4860 | ≥0.60 | 未达 |
| Value match | 0.9470 | ≥0.90 | 达标 |
| 静默错误率 | 5.30% | ≤3% | 未达 |
| 覆盖率 | 100% | ≥0.90 | 达标 |
| 失败运行 | 0 | 0 | 达标 |
| p95 延迟 | 9.22s | ≤120s | 达标 |

- 字段数 2914 → 3052（+138），Precision 0.4764 / Recall 0.4959；与改造前基线（F1 0.4933、静默 4.92%）基本持平。
- 收紧 `grade_property_tail` / `element_matrix`（parser 1.0.5）后指标完全不变，说明这批文档的字段差异不来自这两个策略。
- 结论：Phase 2 的**功能项**（文档门禁、自动 feedback、L1 重解析 diff）已完成，但 **F1/静默指标门槛未达**，需要单独做一轮字段对齐与配方覆盖的准确性治理。

**Phase 2 指标治理（字段对齐 + 配方覆盖，2026-11-12）：**

- 60 份样本实际由“旧 result.json 的表结构”驱动，旧基线与新解析共用同一批表格，差异只来自解析/配方/字段键对齐。
- 根因定位（逐文档统计）：
  1. 表头分组测点丢失：`R m`、`R eL (R ) p0.2`、`KU 2 (KV) 2` 等空格符号未绑定（GB/T 3308 单文档少 138 字段）；
  2. 比较符后缀未剥离：`P≤`、`Cu≤`、`S≤` 等列绑定失败；
  3. 中文限定词未匹配：`方向` 无法命中 `试样方向`，导致切向/纵向条件丢失；
  4. 占位文本被当作牌号：`元素/基/MAX/MIN/含量/余量/日期/更改人`；
  5. 非记录表未阻断：修订记录、签名/职责表、脚注散文被解析成字段；
  6. 转置化学成分表路由不足：元素符号未进入 `chemical_element_rows_v1` 签名，落入 mechanical 兜底；
  7. 重复测点列：同一测点在“室温/高温、纵向/横向、不同直径”多列重复时只保留第一列；
  8. 重复表：版面 OCR 在同一文档内输出完全相同的表。
- 修复（parser `1.0.6` → `1.0.13`，全部经资产热加载发布；配方 `chemical_element_rows_v1@1.2.0`）：
  - 表头：比较符剥离、空格符号（含 `σb/σ0.2/δ5/ψ`）绑定、分组作用域别名 + 完整表头回退（恢复 `碳当量 CEV`）、印刷符号决定共享别名归属（`KU2` 不再抢占 `KV2` 列）；
  - 牌号：占位集合拒绝、长中文脚注/标准号拒绝、`HBW→HB` 归一；
  - 表：修订/签名表阻断、重复表去重、无表头续表的数值表阻断、散文脚注值过滤；
  - 记录：多表头分组（室温/高温、纵向/横向）补录为独立记录，室温组并入主记录；元素符号/“元素”标签不再当作数值。
- 最终指标（parser 1.0.13，60 份）：

| 指标 | 治理前 | 治理后 | 目标 | 结论 |
|---|---|---|---|---|
| Field F1 | 0.4860 | **0.6020** | ≥0.60 | 达标 |
| Value match | 0.9470 | **0.9745** | ≥0.90 | 达标 |
| 静默错误率 | 5.30% | **2.55%**（47/1846） | ≤3% | 达标 |
| Precision | 0.4764 | 0.5767 | 参考 | — |
| Recall | 0.4959 | 0.6296 | 参考 | — |
| 共同字段 | 1454 | 1846 | 参考 | — |
| 覆盖率 | 100% | 100% | ≥0.90 | 达标 |
| 失败运行 | 0 | 0 | 0 | 达标 |
| p95 延迟 | 9.22s | 10.3s | ≤120s | 达标 |

- 剩余 47 个静默错误主要为旧基线自身缺陷：欧洲小数逗号（`0,040` 被旧解析为 `40.0`）、旧表按“不同直径列”取错值、旧基线的公差/偏差表伪记录、旧基线把 `提供数据` 与数值强行配对。继续追逐这些差异会反向降低正确性，暂不处理。
- 说明：Phase 2 的 0.80 原始门槛仍受旧基线噪声限制（旧 baseline 存在 hash 截断牌号、公差表/修订表伪记录），本轮以治理目标 0.60 / 3% 验收；0.80 留待金标集与 Phase 3 规模化评估。

### L3 执行链路（parser candidate 验证闭环，2026-11-12）

- 目标：候选 parser 不移动 stable 指针也能在真实文档上重跑、对比、验证，再决定晋升或回滚。
- 实现：
  1. 契约：`ExecutionRequest.parser: ParserAssetRef | None`（`asset_id` / `version` / `digest`），未设置时行为不变；
  2. 沙箱：`prepare_workspace` 按 pinned 版本从资产注册表拉取精确版本，校验 manifest/摘要，manifest 记录 `pinned=true`；未指定时仍按 channel 解析；
  3. 编排：`runs.parser_version` 迁移（0006）、`RunOut.parser_version`、`POST /runs/{run_id}/reparse` 接受 `{"parser_version": "..."}`，创建前先校验版本存在；
  4. 网关：`POST /v1/runs/{run_id}/reparse` 透传可选 body；
  5. 测试：新增 `test_parser_pin.py`（固定版本拉取、摘要不匹配拒绝），sandbox 全量 **69 passed / 4 skipped**。
- 端到端验证（重建应用镜像后，真实 API）：
  - 发布 `parser_core@1.0.14`（与 1.0.13 同代码）并指向 candidate；
  - `reparse {"parser_version":"1.0.14"}` → `STRUCTURED_READY`，8.1s；
  - 沙箱 `manifest.json`：`parser.version=1.0.14`、`pinned=true`、摘要与候选一致；
  - 与原 run diff：0 records / 0 fields / 0 diagnostics / 表一致；
  - 未知版本：400 `PARSER_VERSION_UNKNOWN`；
  - 晋升 stable：1.0.13 → 1.0.14；回滚：恢复 1.0.13。
- 边界：新文档 `create_run` 仍按 stable channel 取 parser；固定版本仅用于 reparse 验证链路，避免绕过晋升流程。

### 规模化回归门禁（v1，2026-11-12）

- 新增 `scripts/benchmark/gate_scale.py`：复用 M8 对比口径（旧 result 表结构重建为输入），默认 50 份、并发 2，按发布门槛评估并返回非零退出码：
  - Field F1 ≥ 0.60；
  - 静默错误率 ≤ 3%；
  - 覆盖率 ≥ 90%；
  - 失败运行 = 0。
- 50 份实测（parser 1.0.13 stable）：
  - Field F1 **0.6025**、静默 **2.62%**（46/1755）、覆盖率 100%、失败 0、p95 9.25s；
  - `failures: []`，退出码 0，发布放行；
  - 报告：`docs/reports/scale-gate.json` / `.md`。
- 金标子集：`gold-standards.json` 中严格 PDF 落地校验仅 2/89 合格（85 份低于阈值，主因旧基线 grade/value 无法在源 PDF 落地），50 份样本覆盖其中 1 份：F1 0.8416、静默 0%。
- 金标 ≥30 的现状与后续：
  - 现有 legacy 数据不足以自动产出 30 份可信金标；
  - 后续用运行期 `accepted_snapshot`（审核通过快照）累计金标，达到 30 份后把金标 F1 纳入门禁；
  - 在此之前门禁以 50 份旧基线回归 + 2 份 PDF 落地金标为准，避免用噪声金标误判。
- CI 分工：`.github/workflows/new-app-ci.yml` 保持离线 ruff / compile / pytest；50 份门禁依赖运行中的服务栈，作为发布步骤执行，不放入默认 CI。

### Phase 3：L3 代码修复提案 + 规模化（工作量 M）

- L3 代码提案：白名单、反硬编码、测试、人工审批。
- 金标扩到 ≥30 份；50 份标准 + 金标 CI 门禁。
- 灰度 10% → 50% → 100%，保留回滚。
- 门禁：F1 ≥0.70（阶段目标）→ 0.80；扫描件成功率 ≥90%。

## 6. 验收指标

| 指标 | 当前 | Phase 1 | Phase 2 | Phase 3 |
|---|---|---|---|---|
| 有 records 文档 | 11/50 | ≥40/50 | ≥45/50 | ≥48/50 |
| Field F1（60 份） | 0.6020 | ≥0.60 | ≥0.70 | ≥0.80 |
| 静默错误 | 2.55% | ≤3% | ≤2% | ≤2% |
| 单位存在率 | 100% | 100% | 100% | 100% |
| 空记录率 | 0% | ≤1% | ≤1% | ≤1% |
| 数字 PDF p95 | 12.31s | ≤15s | ≤15s | ≤15s |
| 扫描件成功率 | 未单独统计 | 基线 | ≥80% | ≥90% |

## 7. 风险与边界

| 风险 | 应对 |
|---|---|
| layout-first 增加调用量 | 按 block 裁剪，小图 OCR；表格/文本分流；缓存页图 |
| 版面服务延迟/不可用 | 15s 超时、连续失败熔断、回退整页/native |
| 矩阵策略产出冲突 | 质量分 + 冲突诊断；低质量表不产出记录 |
| 旧 table_repairs 过拟合 | 改用表签名/文档指纹；逐条原文核对 |
| L3 代码修复风险 | 默认只提案；白名单 + 反硬编码 + 测试 + 人工审批 |
| schema 扩张 | 先做 records 覆盖与正确性；items/clauses/coverage 由产品决策 |

## 8. 相关文件

- 现有 OCR 流程：[service.py](../../services/ocr/service.py)、[pdf.py](../../services/ocr/adapters/pdf.py)、[glm.py](../../services/ocr/adapters/glm.py)、[hybrid.py](../../services/ocr/adapters/hybrid.py)
- 旧 OCR 版面优先实现：[glm.py](../../../legacy/metal-doc-agent/metal_doc_agent/ocr/glm.py)
- 旧多矩阵提取器：[pipeline.py](../../../legacy/metal-doc-agent/metal_doc_agent/pipeline.py)、[matrix.py](../../../legacy/metal-doc-agent/metal_doc_agent/extraction/matrix.py)
- 新确定性解析：[builtin.py](../../services/sandbox/runtime/builtin.py)
- 新审核规则：[rules.py](../../services/review/rules.py)
- 新反馈闭环：[service.py](../../services/orchestration/feedback/service.py)、[repair.py](../../services/agent/agents/repair.py)
- 现有实施方案：[implementation-plan-current-vs-target.md](implementation-plan-current-vs-target.md)
- 新旧差异分析：[legacy-vs-new-and-review-loop-analysis.md](legacy-vs-new-and-review-loop-analysis.md)
