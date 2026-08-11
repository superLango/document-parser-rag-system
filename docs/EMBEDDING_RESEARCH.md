# 文档结构化抽取向量构建调研（D2，2026-08）

> 目的：确定嵌入模型（D2）、多维向量维度与内容（D3）、检索方案（D6）。
> 调研对象：市面主流 RAG 产品与多向量/结构化向量实践。

## 1. 主流嵌入模型与维度

| 模型 | 维度 | 特性 | 适用 |
|------|------|------|------|
| **BGE-M3**（BAAI） | **1024** | 多语言、dense+sparse+多向量三合一、8192 token | 中文最强开源，通用 RAG |
| BGE-large-zh-v1.5 | 768 | 中文 | RAGFlow 默认选项之一 |
| text-embedding-3-small | 1536 | OpenAI，可配 256-1536 | 英文为主 |
| text-embedding-3-large | 3076（可配） | OpenAI | 英文为主 |
| Qwen3-Embedding | 1024(0.6B)/2048/4096 | 多语言、MRL 可截断 | 国产可私有化 |
| m3e-base / text2vec | 768 | 轻量中文 | 低资源 |
| GTE/E5/MiniLM | 384-768 | 轻量 | 英文 |

要点：中文企业文档首选 **BGE-M3（1024 维）**；维度并非越高越好
（3072 维比 1536 维收益通常 <3%，存储与检索成本更高）。

## 2. 市面多维/结构化向量实践

| 方案 | 向量维度设计 | 存储内容 |
|------|--------------|----------|
| **原项目（五维）** | Path/Title/Content/Type/Structural（5 个向量） | 层级路径、标题、正文、内容类型、结构位置（bge-m3） |
| **Azure AI Search（文档布局技能）** | **多字段向量化**（标题字段 + 内容字段等） | 按文档布局检测标题与语义块，可对任意字段单独 embedding |
| **Dify 高质量索引** | 单向量/分段（通用/父子模式） | 分段文本向量；父子模式下父块可作上下文；经济索引用 jieba 关键词（零模型） |
| **RAGFlow** | 单向量（模型可配 bge-large/m3e/text2vec 等） | DeepDoc 解析 + 9 种分块模板（naive/paper/manual/table/qa 等）；RAPTOR 召回增强 + 知识图谱 |
| **多视图向量化**（17 种 RAG 方法） | summary/body/metadata 多视图 embedding | 文档摘要、正文、元数据分别嵌入 |
| **块头标签**（Contextual Headers） | 标题/章节名作为元数据嵌入 | 技术手册场景，标题向量辅助定位 |
| **Jina ColBERT** | token 级多向量 | 每 token 一个向量，存储剧增，检索精度高但成本高 |

要点：
- **标题+内容双向量是主流**（Azure 多字段、多视图、块头标签均覆盖该模式）
- 五维（原项目）属激进设计，Path/Type/Structural 维度收益未验证，且每块 5 次嵌入成本 5 倍
- ColBERT token 级多向量不适合当前企业场景（存储爆炸）

## 3. 对 D2/D3/D6 的建议

### D2 嵌入模型：BGE-M3（1024 维）
- 中文企业文档最强开源模型，dense+sparse 三合一，8192 token 支持大表格块
- 设计 EmbeddingService 可插拔接口（模型名/维度配置化），后续 Qwen3-Embedding 等可替换
- 注意：BGE-M3 权重约 2.2GB（fp32），GPU 推理；可用 flag embedding / sentence-transformers 加载

### D3 向量维度：建议 **Title + Content 双向量（2 维）+ 结构化字段**
- **title_vector**：标题/章节层级文本（含 hierarchy breadcrumb）嵌入 → 定位章节
- **content_vector**：块正文（表格含 HTML）嵌入 → 语义检索
- **Path/Type/Structural 不入向量**，作为结构化字段存储（pgvector 行内 metadata 列），用于过滤/溯源/展示
- 成本：每块 2 次嵌入（五维的 40%），收益覆盖主流实践（标题+内容）
- 如需更强：预留 summary_vector（块摘要，由 LLM 生成，可选项）

### D4 澄清：BM25/稀疏检索**不依赖 LLM**
- 传统 BM25（jieba 分词 + 词频统计）构建快（毫秒-秒级），零模型依赖（Dify 经济索引同思路）
- bge-m3 的 sparse embedding 是模型输出稀疏权重（非 LLM 生成），批量构建也很快
- 若担心构建时间，可选 **bge-m3 sparse**（模型自带）或 **jieba BM25**（零模型），均不调用 LLM

### D6 检索：dense + sparse 混合（RRF）+ rerank 预留
- dense：title_vector + content_vector 双路（可加权融合，如 content 0.8 + title 0.2）
- sparse：bge-m3 sparse 或 BM25（零模型）
- RRF 融合 dense/sparse；rerank 接口预留（后续接 bge-reranker 等）
- 图检索：本期不做（已确认）

## 4. 决策建议汇总

| 决策 | 建议 |
|------|------|
| D2 嵌入模型 | BGE-M3（1024 维），接口可插拔 |
| D3 向量维度 | **Title + Content 双向量**；Path/Type/Structural 结构化字段存储 |
| D6 检索 | dense（title+content 融合）+ sparse（bge-m3 sparse / BM25）+ RRF；rerank 预留 |

> 待用户确认后据此出实施方案（表结构/分块器/嵌入服务/任务状态机/检索 API）。
