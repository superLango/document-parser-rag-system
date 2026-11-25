# app_v3 方案文档：面向开放标准文档的通用解析架构

> 版本：v3-plan-20261125  
> 前置基线：v2 当前路线冻结版（`new_app/docs/v2-final-route-freeze.md`）  
> 详细实施排期见：[IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md)  
> 基线指标（20 份）：一致率 **0.7899**、覆盖率 **68.61%**、总耗时 **2882.3s**

---

## 1. 背景与目标

### 1.1 背景

当前 v2 路线（OCR → 表格绑定 → 确定性展开 → 富化 → 组装）在部分文档上效果较好，但对"再来 20 份不一样的文档"泛化不足。20 份实测缺口集中在：

| 问题域 | 数量级 | 表现 |
|---|---:|---|
| 化学成分配对错误 | 缺失 1886 / 多余 1596 | 值基本正确（94.7%），但牌号/项目键错 |
| 条件与列绑定错误 | 室温值一致 50.1%、冲击值一致 3.6%、硬度 44.8% | 条件缺失导致配对到错误行/列 |
| 条款类未抽取 | 高倍缺 149、弯曲缺 5、热处理部分缺 132 | 只处理表格，未启用条款通道 |
| 过度派生/重复 | 多余 2513 | 化学/热处理/高温拉伸重复展开 |
| 英文标准适配 | AMS/ISO 0% | 牌号列被表头文字污染，中英项目/状态体系不同 |
| 选表过严 | GBT 8547 仅 1 条 / 金标 9 | 小标准表被 profile 规则过滤 |

### 1.2 目标

1. **不针对单文档/单表打补丁**：新文档接入不修改代码；
2. 一致率 ≥ **0.92**，覆盖率 ≥ **80%**，多余率显著下降；
3. 所有输出可回溯（页/表/单元格/条款引文）；
4. 无法确定的内容进入"未解决队列"，不静默错/丢；
5. 新标准通过**检索/程序模板/模型**迁移，而不是新增分支。

### 1.3 非目标

- 不追求"所有标准全自动 100%"；开放语义差异需人工确认/本体扩展；
- 不替换现有 OCR 能力，而是组合使用（结构化通道保留）。

---

## 2. 问题诊断（根因）

| 编号 | 根因 | 证据/影响 |
|---|---|---|
| R1 | 牌号解析错误 | AMS: `Up to 2.000,incl(1)`；ISO: `Sheet and stripc`；化学缺失/多余对称 |
| R2 | 条件-列绑定不完整 | 冲击值一致 4/111；室温 977/1952；硬度 60/134 |
| R3 | 条款类未抽取 | 高倍 156 金标仅匹配 7；弯曲 0/5；热处理缺失 132 |
| R4 | 选表过严 | GBT 8547 仅 1 条；XX454 高倍/室温缺失 |
| R5 | 过度派生/重复 | 化学多余 1596、热处理 282、高温 103 |
| R6 | 标准信息元数据不稳 | 20 金标，匹配 15，缺失 5 |
| R7 | 英文标准体系未适配 | AMS/ISO 0；ASME/ASTM 低覆盖 |

**本质**：差异是开放集合；当前架构缺少 4 层：
- **规范目标模式层**（Schema/本体）
- **独立验证层**（证据/守恒/一致性）
- **跨文档学习层**（检索/模板/微调）
- **程序化表格变换层**（DSL/程序，而非表类型分支）

---

## 3. 设计原则

1. **表示归一**：所有文档最终映射到同一套规范字段/条件/单位/牌号空间；
2. **模型做语义，代码做执行**：模型只输出结构/映射/程序，代码负责确定性展开与校验；
3. **证据可回溯**：每条记录必须绑定来源（页/表/单元格/条款引文）；
4. **验证独立**：抽取与验证分离，验证器不依赖抽取器同一路径；
5. **多通道互证**：结构化通道 + 语义通道，冲突升级；
6. **学习闭环**：人工确认/失败样本进入评测集与示例库；
7. **评测驱动**：不针对金标调参；指标含覆盖率、一致率、多余率、未解决率、时延。

---

## 4. 目标架构

```
┌─────────────────────────────────────────────────────────────┐
│                     Ingestion / Representation              │
│  PDF → Layout/OCR/Table（Docling/TableFormer 类）→ 结构化 IR │
└──────────────────────────┬──────────────────────────────────┘
                           │
      ┌────────────────────┴────────────────────┐
      │                                         │
┌─────▼──────────────┐                ┌─────────▼─────────────┐
│ 结构化通道          │                │ 语义通道（VLM/LLM）    │
│ - 表格 IR           │                │ - 整页/整表理解        │
│ - 列角色/条件       │                │ - 中英文语义映射       │
│ - 程序 DSL 执行     │                │ - 条款/正文抽取        │
│ - 值可追溯          │                │ - 带证据输出 schema    │
└─────┬──────────────┘                └─────────┬─────────────┘
      └────────────────────┬────────────────────┘
                           │
                 ┌─────────▼─────────┐
                 │  规范模式/本体层   │
                 │  Schema/Ontology  │
                 │  项目/条件/单位/牌号│
                 └─────────┬─────────┘
                           │
                 ┌─────────▼─────────┐
                 │   验证/仲裁层      │
                 │ 证据/守恒/一致性   │
                 │ 双通道冲突/置信度  │
                 └─────────┬─────────┘
                           │
        ┌──────────────────┼──────────────────┐
        │                  │                  │
┌───────▼───────┐  ┌───────▼───────┐  ┌───────▼────────┐
│ 高置信记录     │  │ 未解决队列     │  │ 评测/主动学习   │
│ 直接入库       │  │ 人工/二次复核  │  │ 检索/模板/微调  │
└───────────────┘  └───────────────┘  └────────────────┘
```

---

## 5. 六条可行路线

### 路线 A：Schema/本体驱动的规范化抽取（P0，优先）

**机制**：
1. 定义产品标准规范模式：实体（标准/牌号/项目/条件/要求/方法/取样）、条件维度（温度/状态/尺寸/方向/位置）、单位、比较符；
2. 类别/项目使用本体词表（汉唐 taxonomy + 标准体系）；
3. 模型输出严格 schema JSON（可用 JSON Schema/约束解码）；
4. 代码做归一/校验/值守恒，不按表写分支。

**参考**：
- Schema-constrained LLM verification pipeline：[ACM DOI](https://dlnext.acm.org/doi/pdf/10.1145/3789982.3790050?download=true&__cf_chl_tk=aVO161EVQpFbxPiOq.XL7OvIyrdLMGfnJZK8XfkG8MI-1782375510-1.0.1.1-Bz3wwEQOcF87qDEAmoKl_NVFL8AuCggCmSfkSsrmIFw#1#2#1)
- Doc2DB：抽取后独立验证/全局完整性：[VLDB](https://www.vldb.org/pvldb/vol19/p2522-tang.pdf)

**解决**：R1/R2/R5/R7 的规范化部分。  
**风险**：规范模式需要覆盖常见语义；本体外内容进入未解决队列。  
**改动**：中（schema + 归一/校验层）。

### 路线 B：双通道互证（P1）

**机制**：
1. 结构化通道：现有 OCR/表格绑定/程序展开；
2. 语义通道：VLM/LLM 直接读页面/表，按规范 schema 输出记录 + 证据；
3. 仲裁：一致→高置信；冲突/单通道→未解决队列；低置信不直接入库。

**参考**：
- Docling（DocLayNet + TableFormer）：[Docling](https://arxiv.org/abs/2408.09869)、[TableFormer](https://arxiv.org/abs/2203.01017)
- Donut OCR-free 文档理解：[Donut](https://arxiv.org/abs/2111.15664)
- Qwen2-VL：[Qwen2-VL](https://arxiv.org/abs/2409.12191)
- READoc 真实文档结构化基准：[READoc](https://arxiv.org/abs/2409.05137)
- VAREX 多模态结构化抽取失败模式：[VAREX](https://openaccess.thecvf.com/content/CVPR2026W/MMFM5/papers/Barzelay_VAREX_A_Benchmark_for_Multi-Modal_Structured_Extraction_from_Documents_CVPRW_2026_paper.pdf)

**解决**：R1/R2/R3/R7（尤其英文标准与未见版式）。  
**风险**：成本/时延增加；需仲裁规则。  
**改动**：中高。

### 路线 C：表格程序合成 / 表格代数 DSL（P1）

**机制**：
1. 模型输出表格变换程序：列选择/角色、melt/pivot/explode/join/rename/filter、条件绑定；
2. 代码引擎执行程序，生成规范记录；
3. **回放校验**：记录反向重建表格，必须与原表单元格一致；失败→重试/降级。

**参考**：
- CACHE-ED2：LLM 推理编译为可复用抽取程序：[CACHE-ED2](https://aclanthology.org/2026.emnlp-industry.93.pdf)
- QUIETT：程序化表格重构：[QUIETT](https://aclanthology.org/2026.findings-emnlp.1717.pdf)
- TableLLM：LLM 代码/表格操作：[TableLLM](https://arxiv.org/abs/2403.19318)

**解决**：R2/R5（宽表/多级表头/转置/重复）与"表类型分支"问题。  
**风险**：需要稳定表格 IR 与执行引擎；程序生成错误需回退。  
**改动**：高。

### 路线 D：检索增强的跨标准迁移（P1）

**机制**：
1. 建立标准语料库：同类标准、表头、项目/牌号/状态词表、历史示例；
2. 新文档先检索相似表/相似条款；
3. 用检索样例做 few-shot 或模板迁移（绑定 schema/程序/条件规则）；
4. 词表全局归一。

**参考**：
- RAG 领域信息抽取框架：[RAG extraction](https://researchers.unab.cl/en/publications/a-framework-for-extraction-of-clinical-information-from-radiologi/)
- Few-shot RAG 抽取实践：[Few-shot RAG](https://pubs-acs-org-443.webvpna.lzu.edu.cn/doi/pdf/10.1021/acs.jcim.5c02299?ref=article_openPDF#5#7#5)

**解决**：R1/R7 与新文档冷启动；越用越准。  
**风险**：检索质量/语料覆盖；冷启动需积累。  
**改动**：中（检索库 + 示例管理）。

### 路线 E：智能体提取 + 独立验证 + 人工闭环（P2）

**机制**：
1. 规划器：识别文档/章节/目标类别；
2. 工具：layout、表格、OCR、条款检索、词表；
3. 抽取器：按章节/表带证据抽取；
4. 验证器：证据、守恒、条件完整性、跨表一致性；
5. 未解决队列 + 人工确认回流（主动学习）。

**参考**：
- Agentic Toolkit for Regulatory Documents：[Agentic Toolkit](https://www.semanticscholar.org/paper/An-Agentic-Toolkit-for-Adaptive-Information-from-Colakoglu-Solmaz/b8f0f8bd1642b95c085ea3b62ce4700c97f13073)
- Doc2DB 验证/反馈闭环：[Doc2DB](https://www.vldb.org/pvldb/vol19/p2522-tang.pdf)
- 生成式+专用模型+HITL/主动学习：[AI Business](https://aibusiness.com/nlp/better-together-how-a-blend-of-generative-and-specialized-ai-is-creating-a-new-frontier-with-high-speed-high-precision-business-process-automation)

**解决**：R3 条款类、难例运营、质量可控。  
**风险**：工程复杂、预算控制。  
**改动**：高。

### 路线 F：领域多模态模型微调/蒸馏（P2，长期）

**机制**：
1. 以 40+ gold + 合成数据（表头改写/条件扰动/中英转换/合并单元格）微调领域 VLM/抽取模型；
2. 输出规范 JSON + 证据；
3. 蒸馏到小模型降成本；
4. 与规则引擎/验证器组合。

**参考**：
- Donut / LayoutLMv3 / Qwen2-VL 基座：[Donut](https://arxiv.org/abs/2111.15664)、[LayoutLMv3](https://arxiv.org/abs/2204.08387)、[Qwen2-VL](https://arxiv.org/abs/2409.12191)
- 工业 PDF 抽取研究（agentic schema enforcement + 数据增强）：[ScienceDirect](https://www.sciencedirect.com/science/article/pii/S2590005626004418#8)

**解决**：长尾版式/中英文差异，降低规则维护。  
**风险**：数据/训练资源；短期不如 A/B 见效。  
**改动**：高（数据+训练）。

---

## 6. 推荐组合与分阶段 Roadmap

| 阶段 | 内容 | 交付物 | 目标指标 |
|---|---|---|---|
| **P0（1–2 周）** | A：规范 schema + 牌号/项目/条件/单位归一 + 验证器（证据/值守恒/条件完整性）+ 未解决队列 | `schema/`、`normalize/`、`verify/`、评测报告 | 一致率 ≥0.90，多余 <1000 |
| **P1（3–6 周）** | C：表格程序 DSL + 回放校验；B：双通道互证（先覆盖英文标准）；D：相似标准/表检索 | `table_program/`、`channels/`、`retrieval/` | 覆盖率 ≥80%，英文标准可用 |
| **P2（2–3 月）** | E：Agent + 人工闭环；F：领域模型微调/蒸馏；运营指标 | `agent/`、`learning/`、HITL 队列 | 覆盖率 ≥85%，人工量可控，时间下降 |
| **长期** | A+B+C+D+E+F 融合，平台化 | 版本化标准接入流程 | 新标准接入不写代码 |

**推荐顺序**：A → C → B → D → E → F（先归一/验证，再程序化，再双通道，再检索/学习）。

---

## 7. 评测体系

| 指标 | 定义 | 目标 |
|---|---|---|
| 覆盖率 | 匹配/金标 | ≥80%（P1）→ ≥85%（P2） |
| 一致率 | 值一致/匹配 | ≥0.92 |
| 多余率 | 多余/我方记录 | <15% |
| 未解决率 | 未解决/金标 | 可解释、可控（人工量） |
| 证据命中率 | 记录可回溯到源单元格/引文比例 | ≥99% |
| 时延 | OCR+抽取总时间/文档 | P1 <2min，P2 <1.5min |

**评测原则**：
- 固定评测集（20 份 + 新增 20 份盲测）；
- 不以金标反推规则；任何规则改动需通过回归；
- 分类别报告（化学/室温/冲击/硬度/高倍/热处理等）。

---

## 8. app_v3 建议目录（实施时创建）

```
app_v3/
├── README.md
├── PLAN.md                # 本文件
├── schema/                # 规范模式/本体/词表
├── ingest/                # OCR/layout/表格 IR
├── table_program/         # 表格程序 DSL + 执行器 + 回放校验
├── channels/              # 结构化通道 + 语义通道 + 仲裁
├── normalize/             # 牌号/项目/条件/单位归一
├── verify/                # 证据/守恒/一致性验证
├── retrieval/             # 相似标准/表检索
├── agent/                 # 规划器/工具/未解决队列
├── learning/              # 评测/主动学习/微调数据
└── docs/                  # 设计与实验记录
```

---

## 9. 风险与依赖

| 风险 | 影响 | 对策 |
|---|---|---|
| 规范 schema 覆盖不足 | 新语义进未解决队列 | 本体可扩展 + 人工确认 |
| VLM 成本/时延 | 双通道不可全量 | 先对难例/英文标准启用，按需路由 |
| 程序 DSL 生成错误 | 输出错误记录 | 回放校验 + 降级到结构化通道 |
| 检索语料不足 | 迁移效果差 | 合成数据 + 逐步积累 |
| 评测过拟合 | 新文档退化 | 盲测集 + 分类别指标 + 不针对金标调参 |

---

## 10. 参考链接

1. Schema-constrained LLM verification pipeline — [ACM DOI](https://dlnext.acm.org/doi/pdf/10.1145/3789982.3790050?download=true&__cf_chl_tk=aVO161EVQpFbxPiOq.XL7OvIyrdLMGfnJZK8XfkG8MI-1782375510-1.0.1.1-Bz3wwEQOcF87qDEAmoKl_NVFL8AuCggCmSfkSsrmIFw#1#2#1)
2. Doc2DB: extraction + relational verification — [VLDB](https://www.vldb.org/pvldb/vol19/p2522-tang.pdf)
3. Docling technical report — [arXiv 2408.09869](https://arxiv.org/abs/2408.09869)
4. TableFormer: table structure understanding — [arXiv 2203.01017](https://arxiv.org/abs/2203.01017)
5. Donut: OCR-free document understanding — [arXiv 2111.15664](https://arxiv.org/abs/2111.15664)
6. LayoutLMv3 — [arXiv 2204.08387](https://arxiv.org/abs/2204.08387)
7. Qwen2-VL — [arXiv 2409.12191](https://arxiv.org/abs/2409.12191)
8. READoc: realistic document structured extraction benchmark — [arXiv 2409.05137](https://arxiv.org/abs/2409.05137)
9. VAREX: multi-modal structured extraction benchmark — [CVPRW PDF](https://openaccess.thecvf.com/content/CVPR2026W/MMFM5/papers/Barzelay_VAREX_A_Benchmark_for_Multi-Modal_Structured_Extraction_from_Documents_CVPRW_2026_paper.pdf)
10. CACHE-ED2: compiling LLM reasoning into extraction programs — [ACL Anthology](https://aclanthology.org/2026.emnlp-industry.93.pdf)
11. QUIETT: programmable table restructuring — [ACL Anthology](https://aclanthology.org/2026.findings-emnlp.1717.pdf)
12. TableLLM: tabular data manipulation with LLMs — [arXiv 2403.19318](https://arxiv.org/abs/2403.19318)
13. Agentic Toolkit for Adaptive Information Extraction from Regulatory Documents — [Semantic Scholar](https://www.semanticscholar.org/paper/An-Agentic-Toolkit-for-Adaptive-Information-from-Colakoglu-Solmaz/b8f0f8bd1642b95c085ea3b62ce4700c97f13073)
14. RAG-based domain extraction framework — [UNAB](https://researchers.unab.cl/en/publications/a-framework-for-extraction-of-clinical-information-from-radiologi/)
15. Few-shot RAG extraction — [ACS JCIM](https://pubs-acs-org-443.webvpna.lzu.edu.cn/doi/pdf/10.1021/acs.jcim.5c02299?ref=article_openPDF#5#7#5)
16. Structured data extraction from industrial PDFs（agentic schema enforcement + data enrichment）— [ScienceDirect](https://www.sciencedirect.com/science/article/pii/S2590005626004418#8)
17. Generative + specialized AI + HITL/active learning — [AI Business](https://aibusiness.com/nlp/better-together-how-a-blend-of-generative-and-specialized-ai-is-creating-a-new-frontier-with-high-speed-high-precision-business-process-automation)
