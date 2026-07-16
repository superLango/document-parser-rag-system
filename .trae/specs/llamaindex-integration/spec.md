# LlamaIndex 集成实施 Spec

> 本文档基于 LlamaIndex 系统性调研与对比分析结果，制定在 Hansight 项目中
> 有效利用 LlamaIndex 优点的具体实施方案。
>
> 集成原则：渐进式集成、保留领域定制、抽象层桥接、可回滚。

---

## 一、任务优先级与清单

### P0 级别任务（立即执行）

#### 阶段1：索引层增强

| 任务ID | 任务描述 | 预期目标 | 负责人 | 状态 |
|--------|---------|---------|--------|------|
| P0-1.1 | 安装 LlamaIndex 依赖并验证环境兼容性 | llama-index-core 及相关包安装成功，与现有依赖无冲突 | AI 工程师 | 待执行 |
| P0-1.2 | 创建 IndexManager 多索引管理器 | 支持 Vector/Tree/Summary/KeywordTable 四种索引类型，懒加载 | AI 工程师 | 待执行 |
| P0-1.3 | 在 rag_service.py 集成 IndexManager | 根据查询意图（summarization→SummaryIndex, comparison→TreeIndex）自动选择索引 | AI 工程师 | 待执行 |

#### 阶段2：查询引擎增强

| 任务ID | 任务描述 | 预期目标 | 负责人 | 状态 |
|--------|---------|---------|--------|------|
| P0-2.1 | 实现 SubQuestionQueryEngine 封装 | 复杂比较类问题自动分解为子问题并行回答 | AI 工程师 | 待执行 |
| P0-2.2 | 实现 RouterQueryEngine 路由层 | 根据查询意图自动选择查询引擎，保留现有 LLM 意图分类 | AI 工程师 | 待执行 |
| P0-2.3 | 重构 rag_service.query 为路由分发模式 | 现有 query 方法改为路由分发，保留兜底降级能力 | AI 工程师 | 待执行 |

### P1 级别任务（P0 完成后启动）

| 任务ID | 任务描述 | 预期目标 | 负责人 | 状态 |
|--------|---------|---------|--------|------|
| P1-3.1 | 引入 HierarchicalNodeParser 层级分块 | 替代现有扁平 RecursiveCharacterTextSplitter，支持层级分块 | AI 工程师 | 待排期 |
| P1-3.2 | 实现 AutoMergingRetriever 上下文合并 | 配合层级分块，自动合并相邻分块提升上下文完整性 | AI 工程师 | 待排期 |
| P1-3.3 | 接入 LlamaHub 数据连接器（Confluence/Notion/GitHub/Web） | 新增数据源同步 API，支持企业知识库同步 | AI 工程师 | 待排期 |
| P1-3.4 | 保留现有结构感知分块作为 fallback | 新旧分块策略可切换，确保回滚能力 | AI 工程师 | 待排期 |

### P2 级别任务（后期评估）

| 任务ID | 任务描述 | 预期目标 | 负责人 | 状态 |
|--------|---------|---------|--------|------|
| P2-4.1 | 升级 llm_service 为原生 vLLM token 流式 | 替代"先生成后分块"模拟流式，首 token 延迟降至 ~200ms | AI 工程师 | 待评估 |
| P2-4.2 | 引入 MultiModalQueryEngine 多模态问答 | 支持图片/图表问答能力 | AI 工程师 | 待评估 |
| P2-4.3 | 集成 LlamaIndex callback 可观测性 | 与现有 Prometheus 监控互补，提供 token 级追踪 | AI 工程师 | 待评估 |

---

## 二、验收标准

### P0 验收标准
- [ ] LlamaIndex 依赖安装成功，与现有依赖共存无冲突
- [ ] IndexManager 支持 4 种索引类型，懒加载，单例模式
- [ ] rag_service 根据查询意图自动选择索引
- [ ] SubQuestionQueryEngine 可分解复杂问题为子问题
- [ ] RouterQueryEngine 路由准确率 ≥90%
- [ ] 现有 RAG 管道功能不受影响（回归测试通过）
- [ ] 单元测试覆盖率 ≥60%
- [ ] 查询延迟（comparison 类）降低 ≥30%

### 集成原则
1. **渐进式集成**：不推翻现有架构，逐模块引入
2. **保留领域定制**：术语标准化、结构化抽取、知识图谱保留
3. **抽象层桥接**：通过适配器模式接入 LlamaIndex
4. **可回滚**：每个集成点保留开关，支持回退到自研实现

---

## 三、不应集成的部分

| 模块 | 原因 | 替代方案 |
|------|------|---------|
| LlamaParse SaaS | 数据安全风险 | 保留本地 MinerU+PaddleOCR 管道 |
| LlamaIndex KnowledgeGraphIndex | Hansight Neo4j+DeepKE 更深度 | 保留现有 graph_store |
| LlamaIndex 嵌入/重排抽象 | Hansight bge-m3+Milvus 更精细 | 保留现有 embedding/reranker |
