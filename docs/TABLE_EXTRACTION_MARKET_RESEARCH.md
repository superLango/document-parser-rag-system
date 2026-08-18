# 市面「表格 → 结构化记录抽取」方案调研与最优方案（2026-08）

> 范围：本调研只聚焦**表格数据 → Schema 约束的结构化记录**这一环节。
> 输入：版面分析已还原的表格（layout.json 中的表格 HTML，如化学成分表、室温拉伸性能表等宽表）；
> 输出：材料牌号 + 项目名称 + 标准要求 + 单位等逐行记录。
>
> 触发背景：当前 LangExtractPkg 逐元素拆条时出现系统性丢失——
> 化学成分 511 个数据点只出 51/52 条（全是 C）、室温拉伸 45 行多项目每行只输出 1 条（全是 Rp0.2），
> max_tokens 提到 24000 仍不完整。**这是模型行为问题，不是 token 预算问题。**

## 0. 结论先行（TL;DR）

**表格数据的确定性结构化提取是市面主流 IDP 的共识做法**，推荐方案：

1. **写解析器**把表格 HTML 确定性还原为「行列 dict」——多行表头展平、rowspan/colspan 展开、
   续表按表头合并列、组标签（如"奥氏体型"）前向填充，零信息丢失；
2. **LLM 只做列名 → Schema 字段映射**——先做确定性匹配（术语集 match_record、
   材料牌号↔"新牌号"列、单位从列名括号/术语集提取），复杂列名一次 LLM 调用兜底；
3. **确定性生成记录**——按映射把每个非空、非 `-` 单元格 → 材料牌号 + 项目名称 + 标准要求 + 单位；
4. **非表格文本仍走 LangExtractPkg**（保留现有引擎与溯源能力）。

该方案对当前症状的消除是**确定性的**（数据不依赖 LLM 的"逐元素拆条"行为），
且完全术语集/ Schema 驱动，不针对单一文档硬编码。

## 1. 问题定义与已确认症状

### 1.1 症状（以 GB-T1220-2007 不锈钢棒.pdf 实测为准）

| 类别 | 期望数据点 | 实际输出 | 现象 |
|---|---|---|---|
| 化学成分 | 约 511 个（约 70 行 × 7 列） | 51/52 条 | 每条只有 C，大量行/列丢失 |
| 室温拉伸 | 45 行 × 多项目（Rp0.2/Rm/A/Z/HBW 等） | 45 条 | 每行只输出 1 条（全是 Rp0.2） |

- max_tokens 从默认提到 24000，输出仍不完整 → **不是输出预算截断**；
- few-shot 中已加入"一个原文片段含多值 → 拆多条单值记录"的拆条示例 → 示例没有让模型学会按行×列拆全；
- 表格块已独立成段（`assemble_segments`），单请求不跨表 → 不是上下文太长/跨表干扰；
- 结论：**让 LLM 对宽表做"逐单元格枚举 + 拆条"超出了当前模型的行为稳定性**，
  模型倾向每行只给 1 条"最重要"的记录。这是该领域的已知失败模式
  （LlamaExtract 官方文档明确记录：长表只抽前 20-30 条，见 §2.1）。

### 1.2 已有尝试与效果

| 尝试 | 效果 |
|---|---|
| 表格 HTML → 逐行文本（`table_to_rows.py`：行N: 值 \| 值 \| …） | 召回略升，仍不完整 |
| few-shot 拆条示例 | 无效（模型仍每行只出 1 条） |
| max_tokens 24000 / passes=1 / max_char_buffer=6000 | 无效（不是预算问题） |
| 段级并行 + `llm_sem`（匹配 vLLM max_num_seqs=8）+ 不设超时 | 提升吞吐与稳定性，不解决拆条 |
| bge-reranker-v2-m3 重排 | 提升召回排序，不解决拆条 |

## 2. 市面方案调研（聚焦表格→记录）

### 2.1 LlamaExtract / LlamaParse（LlamaIndex）

- **官方文档明确承认该失败模式**：长表（如 380 家医院列表）默认只抽前 20-30 条，
  官方解决方案是 **`per_table_row=True`（或按行抽取）**——每行独立成为抽取单元，逐行抽、逐行出记录；
- 其实现本质：**把"表"从"上下文段落"中特殊化出来**，行的枚举交给确定性逻辑，
  LLM 只负责"这一行这一列是什么字段"，而不是"把整张表拆成多少条记录"；
- 与我们的对照：`table_to_rows.py` 已把行显式编号，但**仍然把整表文本交给 LLM 让模型自己拆条**，
  等于只做了一半——行的枚举仍由 LLM 完成。

### 2.2 smelt（开源，表格 RAG/抽取）

- 核心原则原文：**"LLM only names and types columns — all extraction is deterministic"**
  （LLM 只负责给列命名/归类，所有取值提取都是确定性的）；
- 先对表格做结构性解析（行列、多行表头、合并单元格），再让 LLM 把列映射到语义字段，
  之后所有单元格取值 = 程序遍历，零丢失；
- 与本项目理念最一致（Schema/术语集驱动、可审计、可离线评估）。

### 2.3 Sensible（商业 IDP，结构化表格抽取标杆）

- 提供 **Fixed Table / Text Table 两类布局抽取**：通过文档上标注行列边界（锚点、列线）
  做**布局确定性提取**，不依赖 OCR/LLM 的语义猜测；
- **DocBits**：把表格切成 cell-level 单元（行列索引可引用），再做 **column mapping**
  （列→字段）与 **Grouping Rows**（按组标签把行聚成子记录）——后处理脚本语言化；
- 优点可借鉴：**行列索引（row_idx, col_idx）贯穿全流程**，任何字段都可溯源回原表格坐标。

### 2.4 Azure Document Intelligence（自定义抽取）

- **表格字段级置信度**：每个行列/单元格带置信度；表格抽取被当作一等公民（表头、单元格、合并）；
- 对高度结构化表单用 **custom template**（标注行列锚点、确定性提取），版式多变走 neural；
- 启示：**版式固定/规律的数据表优先用确定性模板，而不是 LLM 语义抽取**。

### 2.5 Rossum / Hyperscience / ABBYY Vantage（传统 IDP）

- 均以**规则/模板优先、置信度路由人工复核**为主：确定性解析失败才进 LLM/人工；
- Rossum 的 checksum 勾稽（如净额=总额-税）属于"表格内数据一致性校验"，
  对本项目"化学成分各列相加/牌号行号对齐"类校验有参考价值。

### 2.6 开源 RAG/文档链（RAGFlow DeepDoc、Docling）

- RAGFlow 有 "表格结构化"（表格转关系型数据）能力，但主要面向问答，不面向逐行记录入库；
- Docling 有 TableFormer 结构还原（行列/合并单元格），但**抽取侧仍交给 LLM**，与本问题同源。

### 2.7 结论：市面共识

| 做法 | 采用方 |
|---|---|
| **表格 → 确定性行列结构 → 程序遍历取值**（LLM 只映射列名/列类型） | smelt、Sensible Fixed Table、LlamaExtract per_table_row 的底层 |
| **行列坐标贯穿全流程、字段可溯源回单元格** | Sensible DocBits、Azure 表格置信度 |
| **版式规律的表优先确定性模板，LLM 兜底** | Azure template、Rossum、ABBYY |
| **组标签/续表聚合为记录分组依据** | Sensible Grouping Rows、DocBits |
| **整表文本交给 LLM 自己拆条** | 我们的现状（被证明不稳） |

## 3. 推荐方案：确定性表格抽取 + LLM 列映射

### 3.1 总体设计

```text
layout.json 表格 HTML
        │
        ▼
TableParser（确定性）        ← 新增：行列 dict 解析
  ├ 多行表头展平（第1行=牌号, 第2行=分类单位）
  ├ rowspan/colspan 展开（前向填充）
  ├ 续表合并列（同名列对齐，不合并为一张大表）
  ├ 组标签列前向填充（"奥氏体型"、"马氏体型"…）
  └ 输出 {row_idx, col_idx, row_header, col_header, value, page}
        │
        ▼
ColumnMapper（LLM 轻量调用）  ← 新增：列名 → Schema 字段
  ├ 术语集 match_record（已有）
  ├ 规则映射（材料牌号↔"新牌号"、单位↔列名括号）
  └ 复杂列名一次 LLM 调用兜底（每表 ≤1 次，非每单元格）
        │
        ▼
RecordBuilder（确定性）       ← 新增：单元格 → 记录
  └ 非空非"-"单元格 → {材料牌号, 项目名称, 标准要求, 单位, 溯源(row_idx,col_idx,page)}
        │
        ▼
与 LangExtractPkg 文本抽取结果合并（同一类别）
```

### 3.2 关键决策点

1. **只对表格块启用**：文本段落/非表格内容保持现有 LangExtractPkg 链路，两者结果按类别合并；
2. **列映射三种方式递进**：术语集精确/模糊匹配 → 规则（牌号/单位）→ LLM 一次调用；
3. **多值单元格**（如"≤0.030"含多个元素限定）：先按行×列枚举，单元格内多值再按项目术语集
   的 NAME 匹配拆分（`match_record` 已有），拆分仍是确定性规则，不依赖 LLM；
4. **组标签**：`<td rowspan>` 或表首列连续同名 → 前向填充为该行属性（表头列之一），
   不另造记录；
5. **续表**：多个 `<table>` 且表头列名一致 → 按列名对齐合并列集（保留分页信息），
   不合并行（遵守"完整表不从中切断、续表不合并"的已确认约束）；
6. **溯源**：记录附加 `row_idx / col_idx / page`，可直接在页面上定位原表格单元格，
   与现有 `_evidence` 溯源体系一致。

### 3.3 与现有代码的对接点

| 现有文件 | 改动/新增 |
|---|---|
| `backend/app/services/extraction/table_to_rows.py` | 升级为完整 `TableParser`（行列 dict，含 colspan/rowspan/多行表头/组标签） |
| `backend/app/services/extraction/context_assembler.py` | 表格段输出结构化 dict 而非纯文本（或并行保留文本给 LangExtract） |
| `backend/app/services/extraction/lang_pkg_extractor.py` | 表格段改走确定性抽取分支，文本段仍走 lx_extract |
| `backend/app/services/extraction/pipeline.py` | 类别级合并两个分支结果后过脚本校验 |
| `backend/app/services/extraction/script_tools.py` | 复用 `match_record` / 术语集加载做列映射 |
| `backend/app/services/indexing/chunker.py` | 表格块已独立分块，无需改动（确认 has_table 标记完整） |

### 3.4 验证与验收

- 用 GB-T1220-2007 不锈钢棒.pdf 回归：化学成分 ≥ 500 条、室温拉伸逐行多项目全出；
- 与 LangExtractPkg 纯 LLM 方案做 A/B（同 Schema、同文档），比较：条数、字段完整度、耗时；
- 断言：每行非空非 `-` 单元格都有对应记录；无重复记录（主键=材料牌号+项目名称）；
- 随机抽 3 个数据点人工核对原表格坐标（row_idx/col_idx/page）与值一致。

## 4. 暂不采纳项与原因

| 方案 | 不采纳原因 |
|---|---|
| 增大 max_tokens / 加长上下文再试 | 已实测无效，是模型行为不是预算 |
| few-shot 增加拆条示例 | 已实测无效 |
| 表格转 CSV/JSON 后仍交 LLM 逐行拆条 | 只是换皮，枚举仍靠 LLM |
| 专用表格结构还原模型（TableFormer/TSR） | 我们已有 DocLayoutV3 版面 + GLM-OCR 还原的表格 HTML，行/列结构已在，缺的是**抽取侧**确定性利用 |
| 商用 IDP（Sensible/Azure） | 企业内私有化部署约束，能力可自研复刻 |

## 5. 实施路径建议（仅调研，待确认后执行）

- **S1（核心）**：TableParser 行列解析 + 单测（rowspan/colspan/多行表头/组标签/续表）；
- **S2**：ColumnMapper（术语集+规则+LLM 兜底）与 RecordBuilder；
- **S3**：接入 pipeline 与 LangExtractPkg 结果合并，A/B 对比验证；
- **S4**：溯源字段（row_idx/col_idx/page）写入结果并支持页面定位；
- 每阶段完成后按 `qa/TESTING_PROCESS.md` 铁律全流程测试。

