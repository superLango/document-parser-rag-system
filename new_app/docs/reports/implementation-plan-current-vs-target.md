# 文档解析平台实施方案：现有路线 vs 建议改造路线

> 日期：2026-11-12
> 依据：50 份标准回归、60 份新旧对比、旧项目金标筛选、hansonDoc_RAG 版面模型核查、市场调研
> 原则：不改变现有服务拆分；新能力通过配置开关、影子通道和新增适配层接入；任何阶段都可回滚
> 更细的“版面优先 + 配方矩阵 + 审核修复闭环”落地设计见 [layout-first-and-repair-optimization-plan.md](layout-first-and-repair-optimization-plan.md)

## 1. 目标与范围

### 1.1 目标

1. 把 50 份标准中“有记录”的文档从 **11/50** 提升到 **40/50 以上**。
2. 把 60 份新旧对比的 Field F1 从 **0.4933** 提升到 **0.60（一期）→ 0.70（二期）→ 0.80（三期）**。
3. 静默错误率从 **4.92%** 压到 **≤3%**，单位存在率保持 **100%**。
4. 让已微调的 PP-DocLayoutV3 真正参与解析，而不是停留在模型服务器上。
5. 建立可回归的金标集与验收门禁，避免“改一处、坏一片”。

### 1.2 不在本期范围

- 不重写现有 7 个微服务，不改变现有 API 契约。
- 不把旧项目抽取链路重新引入；旧项目只提供字典、规则与金标参考。
- 不在本期做标准换版比对、条款级知识图谱等产品化功能。

## 2. 路线 A：现有路线（As-Is）

### 2.1 架构与数据流

```text
PDF
 │
 ├─ OCR 服务（hybrid）
 │   ├─ 有可读文本层 → PdfOcrAdapter（pymupdf）
 │   │    └─ page.find_tables()（lines_strict）→ HTML table
 │   └─ 无可读文本层 → GLM-OCR（视觉）
 │        └─ 视觉模型输出 HTML table
 │
 ├─ 表格归一化：HTML → TableGrid（rowspan/colspan、header_paths、跨页合并）
 │
 ├─ 路由：recipe-registry stable 通道，按表签名匹配配方
 │
 ├─ 沙箱：builtin.py 按配方 bindings 解析
 │    └─ records / evidence / diagnostics
 │
 └─ 审核：确定性规则 + 模型审核
      └─ STRUCTURED_READY / REVIEW_FAILED
```

关键实现：

| 能力 | 当前文件 |
|---|---|
| 原生 PDF 解析 | `services/ocr/adapters/pdf.py` |
| 混合 OCR 选择 | `services/ocr/adapters/hybrid.py` |
| 版面调用（仅 vision） | `services/ocr/service.py`、`adapters/layout.py` |
| HTML → TableGrid | `services/ocr/algorithms/table_grid.py` |
| 表型识别 | `services/ocr/algorithms/profile.py` |
| 配方匹配 | `services/recipe_registry/matcher.py` |
| 确定性解析 | `services/sandbox/runtime/builtin.py` |
| 审核门禁 | `services/review/service.py` |

### 2.2 当前指标

| 指标 | 结果 |
|---|---|
| 50 份标准结构化成功 | 50/50 |
| 有记录文档 | 11/50；39 份 0 记录 |
| 记录 / 字段 | 160 / 533 |
| 牌号 / 值原文命中 | 100% / 100% |
| 单位存在率 | 100% |
| 空记录率 | 0% |
| 文档内重复键 / 同键多条件 | 17 / 9 |
| 端到端 p50 / p95 | 10.16s / 12.31s |
| 60 份 Field F1 | 0.4933 |
| 60 份 Value match | 0.9508 |
| 60 份静默错误率 | 4.92% |

### 2.3 39 份 0 记录的根因

| 根因 | 份数 | 现状 |
|---|---|---|
| 原生文本层无框线表格未识别 / 封面误判为表 | 30 | `find_tables()` 只做线检测，AMS 封面被当表，正文性能表漏检 |
| 字体编码/字库乱码 | 2 | 可读性门禁只看字符类型，CJK 乱码仍走 native |
| 多层/合并表头、转置元素表无法绑定 | 5 | 元素标签、单位、条件没有从父表头继承到叶子列 |
| 表型不在记录产出范围 | 2 | 尺寸/分类/检验规则表只做表型识别，不产出记录 |

### 2.4 现有路线的问题本质

1. **表格检测是单点**：只要 `find_tables()` 失败，整篇文档就没有记录；没有第二引擎兜底。
2. **版面模型未接入**：`LAYOUT_BASE_URL` 原指向不可达地址；188.75 上没有 `/v1/layout` 服务；原生 PDF 又跳过版面。
3. **表头信息在归一化时丢失**：`header_paths` 存在，但单位、条件、元素标签没有系统化继承。
4. **条件维度不完整**：壁厚、交货状态、产品形式、取样方向等列未绑定到 `condition_key`，导致重复键。
5. **质量评估口径不统一**：新旧对比是字段级，原文核对是文档级，缺少单元格级 TEDS/F1 门禁。

## 3. 路线 B：建议改造路线（To-Be）

### 3.1 目标架构

```text
PDF
 │
 ├─ 页图/文本层
 │
 ├─ 版面服务（模型服务器 188.75:9978）
 │   └─ PP-DocLayoutV3 微调权重 → 标题/段落/表格/图片/公式块
 │
 ├─ 表格三级策略
 │   ├─ Tier 1：数字 PDF 文本层坐标（零幻觉）
 │   ├─ Tier 2：结构模型（TATR / PP-Table）处理无框线、合并单元格
 │   └─ Tier 3：VLM OCR（GLM-OCR / PaddleOCR-VL）兜底扫描件
 │
 ├─ TableGrid 统一契约
 │   └─ header_paths + column_units + column_conditions + merges
 │
 ├─ 配方 1.3.0
 │   └─ 字段字典 + 条件绑定 + 单位继承
 │
 ├─ 沙箱确定性解析（保持不变）
 │
 └─ 审核 + 金标回归门禁
```

核心变化不是“换掉现有解析器”，而是**给现有解析器增加可靠的输入**：版面负责找表，表格引擎负责还原结构，recipe 继续负责确定性字段绑定。

### 3.2 工作包与具体改动

#### W1 版面服务化（P0，前置）

**目标**：让 188.75 上的微调版面模型可被新链路调用。

改动：

1. 模型服务器新增薄服务 `layout_api`（FastAPI）：
   - `POST /v1/layout`：入参页图（base64 或 multipart），出参 `blocks[{type,bbox,score,order}]`。
   - `GET /healthz`：返回模型名、权重 SHA、GPU/CPU、版本。
   - 复用 `hansonDoc_RAG/backend/app/services/parsekit/layout_ppdoc.py` 的 `PPDocLayoutEngine`，不复制模型代码。
2. `new_app/services/ocr/config.py`：
   - 新增 `layout_native_fallback: bool = True`（原生 PDF 0 表时允许调用版面）。
   - 新增 `layout_table_crop: bool = True`（版面 table 块裁剪后送 OCR）。
   - 保留 `layout_timeout_seconds=15`、连续失败熔断。
3. `new_app/services/ocr/service.py`：
   - `_run_layout` 条件从“仅 vision”改为“vision 或（native 且 0 表）”。
   - 对 `type=table` 的块，裁剪页图并调用 GLM/表格引擎，产出 HTML table。
4. `new_app/deploy/compose/docker-compose.yml`、`deploy/k8s/base/apps.yaml`、`.env.example`：
   - `LAYOUT_BASE_URL=http://192.168.188.75:9978`（已改）。
   - 增加 `LAYOUT_API_TOKEN`（如启用鉴权）。

验收：

- `/healthz` 返回 `5b76c1ff...` 或选定权重 SHA。
- 10 份 AMS/ASME 文档中至少 6 份能检出 1 张以上正文表。
- 版面失败不影响原有 OCR，且 warning 可观测。
- 版面 p95 <1s/页（仅页图推理）。

#### W2 表格三级策略（P0，核心）

**目标**：解决 30 份无框线表格和 5 份合并表头。

改动：

1. 新增 `services/ocr/algorithms/text_tables.py`：
   - 输入 `page.get_text("words")`，按 y 聚类成行、按 x 间隔聚类成列。
   - 输出 HTML table，要求：行数≥4、列数≥3、数字单元格比例≥20%、表头命中领域关键词（牌号/元素/抗拉/屈服/伸长/硬度/成分/Grade/Tensile 等）。
   - 不直接把 `find_tables(strategy="text")` 的结果当表格：实测它会把每个词切成列。
2. `services/ocr/adapters/pdf.py`：
   - `find_tables()` 无线结果时，调用 `text_tables` 兜底；仍失败则交给版面 + VLM。
3. 结构模型 PoC（与 W2 并行）：
   - 候选：Table Transformer（TATR）、PP-Table、Docling TableFormer。
   - 在 30 份 0 记录文档上比较表格级 precision/recall、单元格 TEDS、推理延迟。
   - 选择 1 个作为 Tier 2，不直接上生产。
4. `table_grid.py`：
   - 统一接收三种来源的 HTML，保持 `TableGrid` 契约不变。
   - 增加“表格质量分”：表头完整度、数字比例、合并单元格比例；低分表不进入 recipe。

验收：

- 30 份无框线文档中 ≥15 份产出至少 1 条记录。
- 新增记录牌号/值原文命中 ≥95%。
- 不劣化已有 11 份有记录文档。

#### W3 表头/条件/单位继承（P1）

**目标**：解决 5 份多层表头与 17 组重复键。

改动：

1. `services/ocr/algorithms/table_grid.py`：
   - 输出 `column_units`、`column_conditions`、`column_elements`，从 `header_paths` 逐级继承。
2. `services/sandbox/runtime/builtin.py`：
   - `_header_columns` 额外返回父级路径；`_extract_unit` 优先列名，其次 `column_units`，最后配方单位。
   - 条件列优先 `bindings.conditions`，其次 `column_conditions`，最后 `CONDITION_TOKENS`。
3. 配方 `mechanical_properties_v1@1.3.0`：
   - 增加壁厚、交货状态、产品形式、取样方向、试验温度等条件绑定。
   - 增加字段字典：HB/HBW、HRC/HV、RP0.2/ReL、KU2/KV2 的别名与对比映射。
   - 先发 shadow 通道，指标达标后 promote stable。
4. 对比口径：
   - `m8_effect_compare.py` 增加字段字典映射开关，分别输出“原始符号”和“归一化符号”两套 F1。

验收：

- 文档内重复键从 17 组降到 ≤5 组。
- ISO 5832-2 类转置表 grade/condition 语义明确，不再出现 `col3`。
- 50 份标准记录数不下降，值命中 ≥99%。

#### W4 金标与回归门禁（P1）

**目标**：让每次改动有可比基线。

改动：

1. 扩展 `closeout_gold_select.py`：
   - 对无文本层 PDF，调用 GLM-OCR 生成页文本后再核对旧结果。
   - 金标从 2 份扩到 ≥30 份，按 GB/GJB/ASTM/AMS/ISO 分层。
2. 扩展 `closeout_standard_audit.py`：
   - 增加单元格级指标：字段准确率、TEDS、表头命中率、条件键完整率。
3. CI 门禁：
   - 50 份标准 + 30 份金标必须全部跑通。
   - 门槛：有记录文档 ≥40/50、F1 ≥0.60、静默错误 ≤3%、单位 100%、空记录 ≤1%。

验收：

- 每次配方/解析改动自动产出对比报告。
- 回滚时能直接对比“改动前/改动后”四项核心指标。

#### W5 OCR 韧性与多引擎（P2）

**目标**：降低 GLM 单点依赖。

改动：

1. 大扫描件异步队列：>20 页走后台任务，API 返回任务 ID；完成后回写。
2. 多引擎路由：GLM-OCR 为主，PaddleOCR-VL 或 MinerU 为备；按文档类型/失败率切换。
3. OCR 健康检查与熔断：连续失败 N 次自动降级，恢复后回切。

验收：

- 28–37 页扫描件成功率 ≥90%。
- OCR 服务不可用时，文档进入可重试队列，不长时间挂起。

#### W6 灰度与回滚（贯穿）

- 配置开关：`LAYOUT_NATIVE_FALLBACK`、`TABLE_ENGINE`（native/text/model/vlm）、`RECIPE_CHANNEL`。
- 配方先 shadow，再 candidate，再 stable；每步保留上一版本。
- 灰度 10% 文档，对比 zero-record 率、F1、p95；异常自动回滚。
- 所有新能力失败时回退到现有路线 A，不阻断主链路。

## 4. 两条路线对比

### 4.1 定量对比

> 路线 B 的指标为**目标值/预估值**，需通过 Phase 0–2 的 PoC 验证，不是已实现结果。

| 维度 | 路线 A（现有） | 路线 B（建议） |
|---|---|---|
| 有记录文档 | 11/50 | 目标 ≥40/50（一期）→ ≥45/50（二期） |
| 记录数 | 160 | 预计 400–800（表结构恢复后） |
| 牌号/值原文命中 | 100% / 100% | 保持 ≥99% / ≥99% |
| 单位存在率 | 100% | 100% |
| 文档内重复键 | 17 组 | 目标 ≤5 组 |
| 60 份 Field F1 | 0.4933 | 0.60（一期）→ 0.70（二期）→ 0.80（三期） |
| 静默错误率 | 4.92% | ≤3%（一期）→ ≤2%（二期） |
| 端到端 p95 | 12.31s（50 份标准） | 数字 PDF ≤15s；扫描件 ≤25s（含版面/表格模型） |
| 版面模型利用率 | 基本为 0 | 全量数字 PDF 0 表页 + 扫描件 |
| 外部依赖 | GLM-OCR 单点 | 版面服务 + 表格模型 + OCR 多引擎 |
| 运维复杂度 | 低（7 服务） | 中高（+版面服务、模型服务、队列） |
| GPU 成本 | 中（GLM） | 中高（版面 + 表格模型 + OCR） |
| 变更风险 | 低（增量修规则） | 中高（新链路），但可开关回退 |
| 交付工作量 | S/M（持续补规则） | L（分三期） |
| 可逆性 | 高 | 高（shadow/开关/版本回滚） |
| 上限 | 受表格检测限制，F1 难超 0.60 | 可到 0.80，具备产品化上限 |

### 4.2 定性对比

| 维度 | 路线 A | 路线 B |
|---|---|---|
| 技术风险 | 低，但问题是“治标” | 中高，需要模型与工程配合 |
| 数据风险 | 低 | 中，表格模型可能引入结构错误，需要 recipe 校验 |
| 组织成本 | 低，现有团队可维护 | 中高，需要模型/平台/数据标注协同 |
| 用户价值 | 当前 11 份可用，39 份不可用 | 大部分标准可产出记录，F1 可持续提升 |
| 长期维护 | 规则越加越多，边际收益下降 | 引擎分层，替换单点不影响整体 |
| 适用阶段 | 灰度期/兜底 | 规模化/产品化 |

### 4.3 推荐结论

**采用“双轨并行、渐进切换”**：

1. 路线 A 保留为**基线/兜底**，不停止现有规则修复。
2. 路线 B 先在 shadow 环境做 Phase 0 PoC（版面服务 + 10 份文档 + 表格引擎对比）。
3. PoC 达标后，按 W1→W2→W3→W4 顺序接入；每一步用开关控制，异常回退路线 A。
4. 不建议“一次性替换”：当前最大风险不是模型能力，而是表格结构错误会污染 recipe 结果；必须保留确定性校验与回滚。

## 5. 分阶段实施计划

### Phase 0：可行性 PoC（工作量 S）

- 部署 `/v1/layout` 包装服务，打通 188.75:9978。
- 选 10 份 AMS/ASME 0 记录文档，比较：
  - 现有 `find_tables()`；
  - PyMuPDF 文本坐标聚类；
  - pdfplumber 文本策略；
  - Table Transformer / PP-Table。
- 产出：表格检出率、单元格 TEDS、延迟、错误类型。
- 门禁：至少一种方案在 10 份中检出 ≥6 份正文表，且不劣化现有 11 份有记录文档。

### Phase 1：表格与表头能力（工作量 L）

- 落地 W1 版面兜底 + W2 选定的表格引擎。
- 落地 W3 表头/条件/单位继承，发 `mechanical_properties_v1@1.3.0` shadow。
- 跑 50 份标准 + 30 份金标。
- 门禁：有记录文档 ≥40/50；重复键 ≤5；单位 100%；F1 ≥0.60；静默错误 ≤3%。

### Phase 2：质量与回归（工作量 M）

- 扩展金标到 ≥30 份（含 OCR 后的扫描件）。
- 增加单元格级指标与 CI 门禁。
- 字段字典映射生效，输出“原始/归一化”两套对比。
- 门禁：F1 ≥0.70；静默错误 ≤2%；金标回归全部通过。

### Phase 3：规模化与产品化（工作量 M）

- 大扫描件异步队列、多 OCR 引擎、版面/表格服务监控。
- 灰度 10% → 50% → 100%，保留回滚开关。
- 门禁：50 份标准有记录 ≥45；扫描件成功率 ≥90%；F1 ≥0.80 的路径明确。

## 6. 验收标准

| 阶段 | 验收项 | 门槛 |
|---|---|---|
| Phase 0 | 版面服务可用 | `/healthz` 200，权重 SHA 正确 |
| Phase 0 | 表格 PoC | 10 份中 ≥6 份检出正文表 |
| Phase 1 | 标准召回 | 有记录 ≥40/50 |
| Phase 1 | 数据质量 | 牌号/值命中 ≥99%，单位 100%，空记录 ≤1% |
| Phase 1 | 条件维度 | 文档内重复键 ≤5 |
| Phase 1 | 性能 | 数字 PDF p95 ≤15s |
| Phase 2 | F1 | 60 份 ≥0.60，金标 ≥30 份 |
| Phase 2 | 静默错误 | ≤3% |
| Phase 3 | 规模化 | 大扫描件成功率 ≥90%，灰度无 P0 故障 |

## 7. 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| 版面服务不可用/延迟高 | 原生 PDF 仍 0 记录 | 超时 15s、连续失败熔断、回退现有路线 |
| 表格模型结构错误 | 错误字段进入 recipe | recipe 白名单/量纲/上下限校验；低质量表不产出记录 |
| 多层表头模型识别不稳定 | 元素/单位/条件错位 | 保留 header_paths 规则兜底；人工抽检 + 金标门禁 |
| GLM 单点故障 | 扫描件失败 | 多引擎路由 + 异步队列 + 重试 |
| 配方版本膨胀 | 维护困难 | 只发语义版本；shadow→candidate→stable；旧版本保留可回滚 |
| 字段字典争议 | F1 口径不一致 | 产品/业务确认字段字典；同时输出原始与归一化指标 |
| GPU 资源不足 | 吞吐下降 | 版面/表格/OCR 分时复用；夜间批处理；按页限流 |

## 8. 相关文件

- 现有 OCR 实现：[pdf.py](../../services/ocr/adapters/pdf.py)、[hybrid.py](../../services/ocr/adapters/hybrid.py)、[service.py](../../services/ocr/service.py)
- 表格归一化：[table_grid.py](../../services/ocr/algorithms/table_grid.py)
- 确定性解析：[builtin.py](../../services/sandbox/runtime/builtin.py)
- 配方注册：[registry.json](../../services/recipe_registry/data/recipes/registry.json)
- 50 份标准报告：[closeout-standards-e2e.md](closeout-standards-e2e.md)、[closeout-standards-audit.md](closeout-standards-audit.md)
- 新旧对比：[closeout-effect-comparison.md](closeout-effect-comparison.md)
- 金标：[gold-standards.md](gold-standards.md)
- 迁移与市场总结：[migration-layout-market-review.md](migration-layout-market-review.md)
