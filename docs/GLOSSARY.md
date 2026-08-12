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
| 术语条目（term） | 术语集内的单条术语（术语名/标准名/英文/定义/分类/同义词/别名） | status: active/pending/rejected；手动=active、外部同步=pending |
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
| parsekit | 文档解析管线（渲染→擦除→版面→顺序→OCR→拼装） | `backend/app/services/parsekit/` |
| DocLayout-YOLO 权重 | 版面分析模型权重（DocStructBench 2501 版） | `models/doclayout_yolo/doclayout_yolo.pt`，SHA256 锁定，不入 Git |
| GLMOCRBackend | 唯一 OCR 后端（vLLM 9977 OpenAI 兼容） | `backend/app/services/ocr_backend/glmocr.py` |
| ocr_failures | OCR 块级失败记录 | layout.json `ocr_failures`；任务 partial/failed 依据（U13） |
| OCR 失败策略 | `PARSEKIT_OCR_FAILURE_POLICY` | partial（默认）/ failed |
| 页边距过滤 | 版面块/文本层页边距擦除规则 | top≤16%、bottom≥84%，封面页保留 |
| one2one 分支 | DocLayout-YOLO 推理输出分支 | 手动推理取该分支 + NMS |
| rebuild / document_tree | 版面重建与结构树产物 | `backend/app/services/parsekit/rebuild.py`；layout.json `rebuild.document_tree` |
| table_cross_page | 跨页表格标记（U8，仅记录不合并） | 块级 `structural.table_cross_page` |
| pages_cleaned_at | 页面中间产物清理时间（U14） | `documents.pages_cleaned_at`（迁移 007） |
| 页面预览 | 单页 PNG 读取接口 | `GET /kb/{kb}/documents/{id}/pages/{page}` |
| 中间产物保留期 | pages 中间产物保留天数 | `PARSEKIT_INTERMEDIATE_RETENTION_DAYS=7` |
| 上传弹窗 | Phase 5 文档上传 Dialog | ≤100MB、PDF 类型、空文件前端即时校验 |
| 解析进度条 | 解析中阶段进度展示 | rendering→layout→ocr→rebuild，2s 轮询 |
| layout 调试视图 | layout.json 可视化调试 | 块统计 + 结构树 + schema 1.2 |
| 任务列表页 | KB 内任务表格 | `/kb/:kbId/tasks`，含文档 filename |
| 合成评测样本 | Phase 6 生成的企业风格 PDF（含 GT） | `test_doc/generated/`（不入 Git）；GT 在 `qa/evaluation/ground_truth/` |
| U12 指标集 | 评测指标：任务成功率/版面检出误检/标题准确率/OCR 页面正确率/表格还原率 | 门禁阈值见 `evaluate_phase6.py` GATES |
| 版面块类型分组 | 评测匹配时类型归一（title/table/image/formula/text） | `metrics.type_group` |
| 门禁 | 指标未达标即 FAIL 并输出调优项 | `qa/evaluation/reports/phase6_report.md` |
