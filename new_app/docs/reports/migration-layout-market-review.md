# 迁移、版面模型与市场方案总结

> 日期：2026-11-12
> 范围：旧项目可迁移产物、金标筛选、版面模型核查、方案优缺点与市场调研
> 约束：不改变 `new_app` 既有服务拆分与目录结构；迁移内容先按新规范改造、验证后再启用

## 1. 结论摘要

1. **旧项目可以迁移的是“数据与规则”，不是旧抽取链路**：已迁移字段别名、行键、条件关键词、单位口径，并以 `mechanical_properties_v1@1.2.0` 发布到 stable 通道；旧 `category_builder`、`table_to_rows`、检索式抽取仍不迁移。
2. **金标只能小规模、可验证地选**：521 份旧结果中 89 份能关联原文 PDF，按“牌号/值原文命中 ≥95%”筛出 4 份运行、去重后 **2 份唯一标准**（GB/T 1591、GB/T 33084）。多数旧 PDF 是无文本层扫描件，未做 OCR 前无法核对原文。
3. **版面模型确实是微调的**：模型服务器 192.168.188.75 上部署的是 PP-DocLayoutV3-v2 hybrid 微调权重（SHA `5b76c1ff...`），官方权重为 `5ea422c6...`；另有 v1 微调权重 `5c27e59c...`，但当前引擎哈希白名单不包含 v1。
4. **但版面模型没有真正接入新链路**：`LAYOUT_BASE_URL` 原指向不可达的 `192.168.1.35:9978`，已改为 `192.168.188.75:9978`；当前 188.75 上没有 `/v1/layout` 包装服务监听，`hansonDoc_RAG` 的版面引擎是内嵌的，未暴露该接口。原生文本 PDF 又因 `layout_only_for_vision=True` 跳过版面，所以微调模型目前对标准解析基本没有贡献。
5. **50 份标准回归结果**：50/50 成功，160 records / 533 fields，牌号与字段值原文命中 **100%**，单位存在率 **100%**，空记录 **0%**；端到端 p50 10.16s / p95 12.31s。剩余 39 份 0 记录的主因仍是表格结构检测、字库乱码与多层表头，而不是字段字典。
6. **市场判断**：本方案位于“自托管 + 中文标准 + 确定性 recipe”细分，优势是可控、可追溯、无云锁定；短板是表格检测与 OCR 依赖重、领域覆盖靠人工维护。短期不应替换主链路，优先补“版面服务化 + 无线表识别 + 条件绑定”。

## 2. 旧项目迁移：取了什么、没取什么

### 2.1 可迁移并已落地

| 旧项目产物 | 新项目落点 | 处理方式 |
|---|---|---|
| `configs/column_aliases.json` 的 `property_aliases` | `services/sandbox/runtime/builtin.py` `MEASURE_ALIASES` | 新增 E、侧向膨胀值、持久应力、持久温度、蠕变速率、蠕变变形；补 KU2/KV2 的 `akv/akuj/kuj` |
| `role_keywords.row_key` | `builtin.py` `DEFAULT_ROW_KEY` | 新增 级别、钢级、质量等级、统一数字代号、新牌号、原牌号、锻件种类 |
| `role_keywords.condition` | `builtin.py` `CONDITION_TOKENS` + 解析回退 | 新增 交货状态、热处理状态、试样状态、取样方向、壁厚、外径、产品形式、表面状态、轧制、冷轧、热轧、固溶、时效、退火、正火、回火、淬火 |
| `family_keywords` / `hardness_scales` | 既有 `profile.py` / `hardness_v1` | 已覆盖，不重复迁移 |
| 旧系统单位口径 | `binding_units` 回退 + 化学成分默认 `%` | 元素行/元素列/转置表统一补单位 |
| 旧运行结果 | `scripts/benchmark/closeout_gold_select.py` | 作金标筛选与回归基线，不作运行时依赖 |

配方以新版本发布，不修改 1.1.0：

- 新增 `services/recipe_registry/data/recipes/mechanical_properties_v1/1.2.0/manifest.json`
- stable 指针切换为 `1.2.0`，digest `ebb1459e...`
- 新增 measures：`E`、`侧向膨胀值`、`持久应力`、`持久温度`、`蠕变速率`、`蠕变变形`

### 2.2 明确不迁移

- 旧 `extraction/pipeline.py`、`category_builder*`、`table_to_rows.py`：41 类检索式抽取、不展开 rowspan/colspan，与新 TableGrid 契约冲突。
- 旧 API/认证/任务队列/存储封装：新项目已有等价实现，迁移会改变结构并引入旧缺陷。
- 旧结果作为“正确答案”：只在通过原文核对后作为金标，避免把旧系统错误带入新系统。

### 2.3 迁移验证

- 单元/集成测试：114 项收集，110 通过，4 项 Docker 用例跳过。
- 50 份标准回归（迁移后）：50/50 `STRUCTURED_READY`，160 records / 533 fields，牌号命中 100%、值命中 100%、单位存在 100%、空记录 0%，p50 10.16s / p95 12.31s。

## 3. 金标筛选结果

### 3.1 方法

脚本：`new_app/scripts/benchmark/closeout_gold_select.py`

1. 扫描旧 `result.json`，从 `source_path` 的 `<!-- source: ... -->` 元数据、`pdf_manifest.json`、全项目 PDF 标题索引三条路径关联原文。
2. 用 pymupdf 读取原文文本；记录页 ±1 页命中优先，未命中回退全文命中；数值按归一化 token 比对。
3. 阈值：记录 ≥5、字段 ≥10、牌号命中 ≥95%、值命中 ≥95%、空记录率 ≤2%。
4. 同一 PDF 的多个旧运行按 PDF SHA-256 去重，只保留指标最好的一次。

### 3.2 结果

| 指标 | 结果 |
|---|---|
| 扫描旧结果 | 521 |
| 可关联原文 PDF | 89 |
| 达到阈值 | 4（含重复运行） |
| 去重后金标 | 2 |
| 无法关联原文 | 347 |

金标文档：

| 文档 | 页 | 记录 | 字段 | 牌号命中 | 值命中 |
|---|---|---|---|---|---|
| GB/T 1591-2018 低合金高强度结构钢 | 22 | 67 | 67 | 100% | 100% |
| GB/T 33084-2016 | 18 | 152 | 812 | 97% | 100% |

### 3.3 局限

- 旧语料中大量 PDF 是无文本层扫描件，pymupdf 取不到文字，无法做原文核对；这部分未纳入金标，不代表旧结果错误。
- 金标当前只适合做“回归基线”，不足以做统计显著性评估；恢复 GLM-OCR 后可把扫描件纳入核对，金标规模才会扩大。
- 详细清单：[gold-standards.md](gold-standards.md) / [gold-standards.json](gold-standards.json)

## 4. 版面分析模型核查

### 4.1 结论

**使用的是微调模型，不是官方原版。** 模型服务器 192.168.188.75 的 `hansonDoc_RAG/models` 下存在多套权重：

| 权重 | SHA-256（前 8 位） | 说明 | 验证集 AP | table AP |
|---|---|---|---|---|
| `PP-DocLayoutV3_safetensors` | `5ea422c6` | 官方权重 | — | — |
| `PP-DocLayoutV3-v1_safetensors` | `5c27e59c` | 第一次微调（343 训练页 / 61 验证页） | 0.6921 | 0.8997 |
| `PP-DocLayoutV3-v2`（训练报告） | `11c83ce6` | 第二次微调（325 训练页 / 79 验证页） | 0.6501 | 0.9070 |
| `PP-DocLayoutV3-v2-hybrid-20260903` | `5b76c1ff` | 当前部署的 v2 hybrid；报告未单独记录指标 | 未单独记录 | 未单独记录 |

当前 `models/pp_doclayoutv3` 与 `pp_doclayoutv3_finetuned_v2` 的权重都是 `5b76c1ff`；`backend/.env` 也指向 `finetuned_v2`。`layout_ppdoc.py` 的 `EXPECTED_SHA256` 为 `5b76c1ff`，允许回滚到官方 `5ea422c6`，但**不包含 v1 微调权重 `5c27e59c`**。

需要特别说明：v2 训练报告记录的 safetensors 是 `11c83ce6`，与部署的 `5b76c1ff` 不一致，说明部署产物与训练报告之间还存在一次未记录的转换/混合操作；在正式选型前应补齐该产物的来源、转换脚本和评测记录。

### 4.2 新项目接入现状

- 原默认 `LAYOUT_BASE_URL=http://192.168.1.35:9978`，该地址不可达，且不是当前模型服务器。
- 已改为 `http://192.168.188.75:9978`（compose / k8s / `.env.example`），超时 15s。
- 但 188.75 当前没有服务监听 9978；`hansonDoc_RAG` 只有内嵌 `PPDocLayoutEngine`，没有 `/v1/layout` 端点。也就是说，新链路的版面调用目前必然失败并降级为 warning。
- 原生 PDF 走 `PdfOcrAdapter`，`layout_only_for_vision=True` 会跳过版面；扫描件走 GLM 时才调用版面，而 GLM 服务当前也不可用。

### 4.3 建议

1. 在模型服务器增加一个薄 `POST /v1/layout` 包装服务，复用 `PPDocLayoutEngine`，只接收页图并返回块；加健康检查与超时。
2. 先在 50 份标准集上对比 v1 与 v2-hybrid 的 table/text 检出率，再决定 stable 权重；若选 v1，需要同步更新 `ALLOWED_SHA256`。
3. 原生 PDF 的“0 表格页”允许触发版面，用版面 table 块裁剪后送 GLM，作为无线表兜底。
4. 版面服务必须纳入 compose/k8s 健康检查；不可用时显式告警，而不是静默跳过。

## 5. 当前方案优缺点

### 5.1 优点

- **确定性可追溯**：配方绑定 + TableGrid + evidence，字段可回溯到表/页/行；比纯 LLM 抽取更可控。
- **自托管与数据主权**：模型、OCR、解析全部内网；适合标准/军工/核电等敏感文档。
- **中文标准适配**：PP-DocLayoutV3 微调 + GLM-OCR + 中文字段别名，覆盖 GB/GJB/HB/YS 等。
- **服务拆分清晰**：OCR、路由、沙箱、审核、配方注册独立，便于替换单点。
- **指标可回归**：已有 50 份标准核对、60 份新旧对比、12 份基线复测，能持续量化。

### 5.2 缺点

| 缺点 | 证据 | 影响 |
|---|---|---|
| 原生文本层无线表检测弱 | 50 份中 30 份 0 记录；AMS 封面被误判为表 | 标准召回低 |
| 版面模型未接入 | 188.75 无 `/v1/layout`，原生路径跳过版面 | 微调模型价值未释放 |
| OCR 单点依赖 | GLM 服务不可用时扫描件无法兜底 | 大扫描件/乱码件失败 |
| 多层表头继承不完整 | `ELEMENT_COLUMNS_NOT_FOUND`、单位/条件丢失 | 元素表、复合表头解析失败 |
| 条件绑定仍不全 | 文档内重复键 17 组、同键多条件 9 组 | 下游去重/对比歧义 |
| 字段字典/覆盖口径差异 | 60 份 F1 0.4933，旧 HB/HRC vs 新 HBW/HV | F1 难达 0.80 |
| 配方人工维护成本 | 新 measure/条件需发版 | 长尾标准覆盖慢 |

## 6. 市场调研（2025–2026）

> 以下为公开资料与厂商页面的汇总，价格/基准会变化，采购前需以官方报价和实测为准。

### 6.1 方案对比

| 方案 | 类型 | 优势 | 短板 | 对本平台适配度 |
|---|---|---|---|---|
| AWS Textract | 云 API | 表格/表单成熟，S3 集成好 | 无私有化，中文弱，按页计费高 | 低 |
| Azure AI Document Intelligence | 云 + 容器 | 支持本地容器，预置/自定义模型齐全 | 通用结构输出，需下游重组 | 中（兜底/对标） |
| Google Document AI | 云 API | Layout Parser、自定义抽取成熟 | 无私有化，标注成本高 | 低 |
| Adobe PDF Extract | 云 API | 原生 PDF 结构还原好 | 扫描件弱，无自托管 | 低 |
| Mistral OCR / Document AI | 云 + 企业容器 | 多语言、schema 输出、单价低 | 中文标准表格非强项 | 中低 |
| LlamaParse | 云（企业可自托管） | Agentic 解析，难页效果好 | 计费不透明，自评基准 | 中（难页兜底） |
| Reducto | 云（企业自托管） | 复杂表格/财报强 | 中文与国标领域弱，闭源 | 中 |
| Unstructured | 开源核心 + 平台 | 格式多、ETL 生态好 | 表格结构精度一般 | 中低 |
| MinerU 2.x | 开源自托管 | 中文好，pipeline/VLM 双模式，显存门槛低 | 许可有附加条款，需核对商用条件 | 高（对照/备选） |
| PaddleOCR PP-StructureV3 / PP-DocLayoutV3 | 开源自托管 | Apache 2.0，中文最强，多点框/阅读顺序 | 无线表仍需调优，多模型编排复杂 | **很高（现基座）** |
| PaddleOCR-VL / GLM-OCR | 开源自托管 | 小参数 VLM，单卡可跑，中文 OCR 强 | 跨页表、长尾术语仍需后处理 | 高（OCR 主/备） |
| Docling | 开源自托管（MIT） | TableFormer、DocTags、工程化好 | 中文精度不及 Paddle 系 | 中（结构参考） |
| Camelot / pdfplumber | 开源库 | 数字 PDF 坐标精确、可解释、零幻觉 | 无 OCR，扫描件/无线表失效 | 中（文本层基线） |
| Table Transformer / DELTA | 开源模型 | 单元格结构识别，可与文本层对齐 | 需 OCR 供文本，跨页需后处理 | 中（结构补强） |

### 6.2 市场趋势

1. **小参数 VLM 替代多模型流水线**：0.9B–3B 级 OCR/VLM 在单卡可跑，逐步替代“检测+识别+表格”多模型串联。
2. **版面模型强调非平面鲁棒**：多点框、弯曲/倾斜/拍照件、阅读顺序成为标配。
3. **表格竞争从“有线检测”转向“结构识别”**：无线表、合并单元格、跨页续表是核心差异点。
4. **价格两极分化**：云端按页计费从约 $1.5 到数十美元/千页；开源自托管免费但需 GPU 与工程投入。
5. **开源许可成为硬约束**：Apache 2.0/MIT 更受政企欢迎；MinerU 附加条款、Marker 权重许可、PyMuPDF AGPL 需前置评估。
6. **从解析走向抽取**：schema/recipe 驱动的结构化抽取、单元格级溯源、标准换版比对成为溢价点。
7. **评测体系成熟但自评泛滥**：OmniDocBench、ParseBench 等并存，厂商自评需交叉验证。
8. **标准数字化政策催化**：标准语义知识库、元素排序等规范会推动行业 schema 标准化。

### 6.3 对本平台的启示

- 主链路继续用 **PP-DocLayoutV3 微调 + 中文 OCR**，但不要把版面/OCR/表格绑死在一个服务里。
- 表格采用三级策略：**数字 PDF 文本层坐标 → 结构模型（TATR/PP-Table）→ VLM 兜底**，recipe 做最终确定性校验。
- 建立分层 Golden Set（GB/GJB/ASTM/AMS/ISO），用**单元格级 F1/TEDS/字段准确率**而非整页字符准确率。
- 只选 Apache 2.0/MIT 组件，规避许可风险；模型权重、词典、配方全部本地化。
- 差异化做“标准换版比对、单元格坐标溯源、按标准规范的列序/schema 资产”，而不是单纯卖 OCR。

## 7. 优化路线图

### P0（当前最影响召回）

1. **版面服务化**：在 188.75 部署 `/v1/layout` 包装服务，纳入健康检查；原生 PDF 的 0 表格页触发版面 + GLM 表格兜底。
2. **无线表识别**：文本层坐标 + 结构模型（Table Transformer/PP-Table）补“无框线、少框线”表；不要把 `find_tables(strategy="text")` 直接当表格用，它会把每个词切成列。
3. **条件绑定**：把壁厚、交货状态、产品形式、取样方向、试验温度绑定到 `condition_key`，优先消除 17 组重复键。
4. **金标扩容**：恢复 GLM-OCR 后，对扫描件做 OCR 再核对旧结果，把金标从 2 份扩到 20–50 份。

### P1（质量与效率）

5. **字段字典映射**：建立 HB/HBW、HRC/HV、RP0.2/ReL、KU2/KV2 的对比口径与配方别名；F1 目标先从 0.49 提到 0.60。
6. **多层表头继承**：元素标签、单位、条件从父级 header_path 继承到叶子列；补齐 ISO 5832-2 类表的单位/条件。
7. **字库乱码门禁**：增加“常用字/编码命中率 + 表头符号比例”判据，疑似乱码页强制走 OCR。
8. **OCR 异步队列**：大扫描件夜间批处理，>20 页独立 SLA。

### P2（产品化）

9. **多引擎兜底**：PaddleOCR-VL / MinerU 作为 GLM 的备选，按文档类型路由。
10. **标准换版比对**：同一标准新旧版本的字段差异、条款差异、牌号增删。
11. **单元格级溯源与列序规范**：为每个字段保留页/表/行/列坐标，按行业标准列序输出。

## 8. 附件

- [50 份标准 E2E](closeout-standards-e2e.md) / [JSON](closeout-standards-e2e.json)
- [50 份标准原文核对](closeout-standards-audit.md) / [JSON](closeout-standards-audit.json)
- [旧项目金标筛选](gold-standards.md) / [JSON](gold-standards.json)
- [收尾测试报告](closeout-test-report.md)
- [实施方案：现有路线 vs 建议路线](implementation-plan-current-vs-target.md)
- [版面优先 + 配方矩阵 + 审核修复闭环优化方案](layout-first-and-repair-optimization-plan.md)
- [Phase 0 版面优先 PoC 结果](layout-first-poc.md)
- [新旧项目差异与审核-修复闭环分析](legacy-vs-new-and-review-loop-analysis.md)
- [60 份新旧对比](closeout-effect-comparison.md)
- [版面服务说明](../../services/ocr/README.md)
- [机械配方 1.2.0](../../services/recipe_registry/data/recipes/mechanical_properties_v1/1.2.0/manifest.json)
