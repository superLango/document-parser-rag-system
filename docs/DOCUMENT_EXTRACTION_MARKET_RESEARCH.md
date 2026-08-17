# 市面成熟文档抽取系统调研与对比（2026-08）

> 目标：对照主流文档解析/结构化抽取系统的抽取链路，找出对方优点与可借鉴项，映射到本系统（HansonDOC RAG）。
> 本系统现状：PDF → PP-DocLayoutV3 版面 → GLM-OCR 块级识别 → markdown/layout.json → 层级分块 →
> BGE-M3+BM25 检索 → Schema/术语集驱动的 LLM 抽取（BaseExtract / LangExtractPkg+XGrammar）→ 脚本后处理/校验 → KB RLS。

## 1. 调研对象与抽取链路

| 系统 | 类型 | 抽取链路要点 |
|---|---|---|
| MinerU（opendatalab） | 开源解析引擎 | 双后端：pipeline（版面+MFD公式检测+OCR+表格TSR+阅读顺序+Markdown）与 VLM/hybrid（VLM 端到端，MinerU2.5-Pro-1.2B）；OmniDocBench v1.6 上 pipeline 86.47 / VLM 95.39；支持 DOCX/PPTX/XLSX、跨页表格合并、公式 LaTeX、109 语言 OCR、layout/span 可视化、mineru-router 多卡路由、滑动窗口超长文档 |
| RAGFlow DeepDoc | 开源 RAG 文档解析 | 视觉处理（OCR/Layout/TSR）与解析器解耦，可自选视觉模型；按文档类型（简历/论文等）模板化解析器；任务与分块解耦 |
| Docling（IBM / LF AI） | 开源文档理解 | RT-DETR 版面 + TableFormer 表格结构 + RapidOCR + 可选 VLM；统一 DoclingDocument 对象、无损 JSON 导出；表格 TEDS 95.4/90.1/93.6；docling-pipelines 提供 LLM 实体抽取 + JSON Schema 匹配输出 |
| Unstructured.io | 开源/商业解析+分块 | 元素化分区（Title/Table/ListItem…）→ 多种 chunk 策略（by_title/by_page/by_similarity，表格独立成块）；API/工作流节点 |
| 合合 TextIn | 商业 IDP | 扫描/电子自动分流；版面分析还原语义结构；跨页表格逻辑合并；印章/手写识别；1000 页内长文档一次解析；输出可直接入库/对接业务系统 |
| Azure Document Intelligence | 云 IDP | Layout 模型（段落/标题/表格/选择标记/签名）+ Custom template（版式 KV 抽取，需标注训练）+ Custom neural（少样本、容忍版式变化）+ 字段级置信度 |
| AWS Textract | 云 IDP | OCR + TABLES/FORMS 特征 + Queries（自然语言查询抽取，如“What is the total amount due?”）+ 自定义 Queries |
| LlamaParse（LlamaIndex） | 商业解析平台 | parse_mode 分级：无LLM/LLM/LVM/Agent/Layout-Agent/页级或文档级；LLM 重建版式、VLM 端到端、Agent 推理循环、跨页连续性；130+ 格式；Schema 驱动抽取（LlamaParse Extract） |

## 2. 对方优点清单（按可借鉴价值排序）

1. **VLM 端到端解析与“解析强度分级”**（MinerU、LlamaParse）：复杂版面（跨页表格、图表、公式、扫描件）用 VLM/Agent 模式，简单文档用快速模式；可动态选后端。
2. **统一中间文档对象/无损 JSON**（Docling）：标准化的 DoclingDocument + lossless JSON，便于审计、多格式导出、下游复用。
3. **表格结构专用模型**（TableFormer/TSR）：结构化还原（单元格/行列/合并）远超“文本提示式表格增强”；并给出明确 TEDS 评测分。
4. **模板 + 神经双路线与字段级置信度**（Azure）：高度结构化表单走模板抽取（快、准、可解释），版式多变走 neural；每字段带置信度。
5. **查询式抽取**（Textract Queries）：用自然语言提问抽取字段，降低 Schema 配置门槛。
6. **元素化分区 + 多种分块策略**（Unstructured）：先输出带类型的元素，再按标题/页面/相似度分块；表格独立成块。
7. **扫描/电子自动分流、印章手写、跨页表格合并、超长文档**（TextIn、MinerU）：真实业务文档的高可用细节。
8. **页级 vs 文档级模式、跨页连续性**（LlamaParse parse_document_with_*）：整文档处理保持标题层级与长表连续。
9. **可视化质量确认**（MinerU layout/span 可视化）：直接看版面/跨度识别结果，快速定位解析错误。
10. **评估基准与门禁**（OmniDocBench、TEDS）：统一指标对比解析/表格质量。
11. **文档级后校验**（Docling 教训）：独立表格页可能被版面模型误判为图片——需要“解析后表格完整性校验”兜底。

## 3. 与本系统逐环节对比

| 环节 | 本系统现状 | 对方做法 | 差距/对方优点 |
|---|---|---|---|
| 文档类型/格式 | 仅 PDF | MinerU/TextIn/LlamaParse 支持 DOCX/PPTX/XLSX/图片 | 缺多格式 |
| 扫描/电子分流 | 有 pdf_classify 但未接入自动分流 | TextIn 自动分流，电子版走文字层 | 可接入 |
| 版面分析 | PP-DocLayoutV3 | MinerU pipeline（DocLayout 系）、Docling RT-DETR | 同级，均有专用版面模型 |
| OCR | GLM-OCR（VLM 风格，块级） | MinerU PP-OCRv6 / VLM 端到端、RapidOCR | 我们偏 VLM 风格；缺“快速 OCR 档位” |
| 表格 | 表格不切分 + table_enhancer（文本提示式概述） | TableFormer/TSR 结构化还原（单元格级） | **明显差距：表格结构化还原弱** |
| 公式 | 无（GLM-OCR 走图片） | MinerU 公式 → LaTeX | 缺公式 LaTeX |
| 跨页表格 | U8 暂缓（仅标记） | MinerU/TextIn 支持跨页表格合并 | 差距 |
| 中间产物 | layout.json + markdown（自定义） | DoclingDocument 无损 JSON（标准化） | 缺标准化无损对象 |
| 分块 | 层级父子分块、表格不切分 | Unstructured 元素化 + by_title/by_page/similarity | 缺多种分块策略 |
| 检索 | BGE-M3 双路 + BM25 + RRF | 各家类似（Hybrid） | 同级，不落后 |
| 抽取驱动 | Schema/术语集 + Prompt + few-shot | Azure 模板/神经、Textract Query、Docling JSON Schema、LlamaParse Extract | 缺模板路线、查询式抽取、字段级置信度 |
| 输出约束 | XGrammar（原包）/ JSON 模式 | Instructor/Outlines/XGrammar 类 | 已对齐 |
| 后处理/校验 | 脚本（post/validation） | docling-pipelines 校验、TextIn 语义还原 | 同级；缺“解析后表格/页面完整性校验” |
| 评估 | Phase 6 解析评测（自建样本） | OmniDocBench、TEDS | 可对齐公开基准 |
| 可视化确认 | layout 调试视图（部分） | MinerU layout/span 可视化 | 可强化 |
| 部署 | 私有化 GPU + arq + MinIO | MinerU router 多卡、滑动窗口超长文档 | 缺多卡路由与超长文档滑窗 |

## 4. 可借鉴项（落地建议）

1. 解析后端增加 **VLM 端到端模式**（可选 hybrid）：在 parsekit 增加 backend 开关（pipeline/vlm），复杂文档用 GLM-OCR 全页/Agent 模式。
2. 定义 **标准化中间产物**：layout.json 对齐 DoclingDocument 子集 + 无损导出（含 reading order、表格结构、图像位置）。
3. 表格增强升级：优先评估 **表格结构专用模型/结构化 TSR**（如基于 PP-StructureV3/TableFormer 思路），替换/增强当前文本式 table_enhancer。
4. 抽取结果增加 **字段级置信度** 与“未确认”标记（Azure 风格），前端展示可复核。
5. 预留 **查询式抽取**：Schema 字段可由“自然语言问题”定义（Textract Query 思路），降低配置门槛。
6. 分块器增加 **by_title/by_page/similarity 策略**（Unstructured 风格），表格独立块已具备。
7. 解析后 **完整性校验**：检测“独立表格页被判为图片/空表格”等情况并告警（Docling 教训）。
8. 评估对齐 **OmniDocBench / TEDS**：补充版面/阅读顺序/表格 TEDS 指标到 Phase 6 评测。
9. 增加 **layout/span 可视化确认**工具，辅助人工抽检。

## 5. 结论

- 我们与主流系统在“版面模型 + OCR + 检索 + Schema 驱动 LLM 抽取 + 输出约束”主链路上**方向一致、不落后**；
- 对方最大优点集中在：**表格结构化还原、VLM 端到端/解析强度分级、标准化无损中间产物、模板/神经双路线+字段置信度、查询式抽取、多格式与跨页处理、公开评测基准**；
- 建议优先补：表格结构化、字段级置信度、解析后端 VLM 模式开关、解析完整性后校验、公开基准评测。
