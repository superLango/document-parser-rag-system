# 业务常量与自定义术语对照表

| 术语/常量 | 含义 | 取值/规则 |
|-----------|------|-----------|
| KB（知识库） | 系统隔离与权限的边界单位 | UUID；显式成员制 |
| 六层隔离 | PostgreSQL RLS / Milvus Collection / MinIO bucket / Nebula space / Redis 前缀 / 配置覆盖 | 见 `docs/ARCHITECTURE.md` |
| 五维向量 | path / title / content / type / structural 五个向量字段 | 权重 0.15 / 0.20 / 0.45 / 0.05 / 0.15 |
| RRF | Reciprocal Rank Fusion 融合 | rrf_k=60；dense_weight=1.0；keyword_weight=1.2 |
| BM25 稀疏 | KB 级词法检索模型 | `data/bm25/{kb_id_hex}.json` |
| gliclass | 零样本类别分类过滤 | 阈值 0.5 / Phase2 置信度 0.35 |
| Popo / MinerU-Popo | 版面后处理（跨页表格合并、标题重建、图文关联） | vLLM :9999 |
| GLM-OCR | 主 OCR（PP-DocLayoutV3 + 区域级并行） | vLLM :9977，fullpage |
| LangExtract / BaseExtract | 双轨抽取引擎（质量优先 / 稳定优先） | `llm.engine` 切换 |
| feature / 类别 | Schema 模板中的抽取类别节点 | `name_source=term_base` 时可展开 |
| Schema 模板 / Prompt 模板 | 抽取结构定义 / 提示词定义 | 每 KB 配置，缺失即报错 |
| 术语集（term base） | 名称/同义词/查询词/字段值集合 | 替代旧“数据集” |
| 术语绑定 | 类别字段 ↔ 术语集值映射 | `(category_id, field)` → term_base |
| Hook 接口 | 6 个标准接口（extract_candidates/build_category_schema/validate_record/post_process/category_match/build_doc_info_prompt） | `kb_hooks/{kb_id_hex}/hooks.py` |
| process_status | 一体化流程状态 | queued / ocr_processing / ocr_done / extracting / completed / failed |
| Task.status | 任务状态 | queued / running / success / failed |
| Document.status | 文档解析状态 | ready / processing / completed / failed |
| 雪花 ID | 128 位 Base62 ID（约 22 字符） | 公开接口 task_id 防枚举 |
| trace_id | 链路追踪 ID | 请求头 `X-Trace-Id`；响应体回传 |
| 错误码分段 | 5 位整数 | 1xxxx 参数 / 2xxxx 鉴权 / 3xxxx 业务 / 5xxxx 系统 |
| 角色 | owner / admin / editor / viewer + is_superuser | 显式成员制 |
| 领域模板 | 4 个内置模板 | material_testing / medical_device / contract / general_qa |
| RAG 意图 | 查询意图分类 | document_search / knowledge_graph / summarization / comparison / general |
| 统一响应体 | `{code, message, data, trace_id}` | code=0 成功 |
| 限流分级 | auth 5/min、upload 10/min、AI 20/min、默认 60/min、公开上传 10/min、公开查询 60/min | slowapi |
| 配置原则 | 无静默回退、全量校验 | `ensure_extraction_config_valid` |
| 系统角色（System Role） | 平台级角色 | super_admin / admin / member / pending |
| 空间角色（Workspace Role） | 工作空间内角色 | owner / admin / editor / viewer |
| 权限点（Permission Code） | 细粒度权限标识 | `{resource}.{action}`，如 `kb.create`、`user.manage` |
| 双层 RBAC | 系统角色 + 空间/资源角色的两级权限模型 | 见 `docs/RBAC_RESEARCH_PLAN.md` |
| 资源 ACL | 单个资源上的访问控制 | 成员表 + 角色 + 状态 + 有效期 |
| 邀请单（Invitation） | 带 token/角色/过期时间的加入凭证 | 参考 Dify/Open WebUI 邀请与审批 |
| Pending | 待审批账号状态 | 可登录但仅访问个人中心与审批页 |
