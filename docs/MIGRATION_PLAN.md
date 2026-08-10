# 系统迁移计划（按既定思路：先框架 → 登录权限 → 工作台，再逐域迁移）

> 本文档是本项目**唯一权威迁移路线**，与旧版 `document-parser-rag-system/` 的
> 功能一一对应。每完成一个阶段，系统保持可运行、可验证。

## 0. 总体思路

1. **先搭骨架**：仓库、规范、前后端工程结构。
2. **先做登录与权限**：用户体系是后续一切功能的安全底座，原系统所有
   登录/权限/审计能力全部迁移并升级，不遗漏。
3. **工作台先行**：登录后进入美观大气的工作台，展示项目信息与运行状态。
4. **主流程按域逐步迁移**：知识库 → 文档解析 → 抽取 → 术语 → 问答 → 图谱
   → 公开接口/嵌入 → 旧系统下线。每步独立验收，不做大爆炸式重写。

## 1. 阶段 0：框架搭建 + 登录权限 + 工作台（本次已完成）

### 已交付

| 项 | 说明 |
|----|------|
| 工程结构 | `backend/`（FastAPI + SQLAlchemy + Alembic）、`frontend/`（React 19 + TS + Tailwind 4） |
| 主数据库 | PostgreSQL，库名 `hanson_doc_rag`，迁移脚本 `alembic/versions/001_initial_auth.py` |
| 登录 | JWT access + refresh、登录失败计数、账户锁定、最近登录记录 |
| 注册 | 开放注册（`ALLOW_REGISTRATION` 可关闭），默认普通用户 |
| 个人中心 | 资料更新、修改密码（强度校验 + 历史禁用 + 记录历史） |
| 密码重置 | 令牌式重置（模型与端点已就绪，邮件下发待通知中心阶段接入） |
| 用户管理 | 超管 CRUD、软删除、启用/禁用、超管切换、重置密码（防自删/自禁/自降） |
| 审计日志 | 装饰器式审计（脱敏、失败也留痕）、筛选/统计/详情、异常告警日志 |
| 权限基础设施 | 超管守卫、RBAC 角色常量（owner/admin/editor/viewer）、KBContext/RLS 依赖骨架、IP 白名单、分级限流 |
| 工作台 | 项目信息、用户统计、近 7 天登录趋势、最近活动、系统信息 |
| 前端主题 | 浅绿 + 白（见 `docs/UI_THEME.md`） |

### 已迁移的原功能对照

| 原功能 | 原位置 | 新位置 |
|--------|--------|--------|
| 登录/刷新/me/资料/注册/改密/重置 | `backend/app/api/v1/endpoints/auth.py` | `backend/app/api/v1/endpoints/auth.py` + `services/auth_service.py` |
| 用户管理 7 个端点 | `endpoints/users.py` | `endpoints/users.py` + `services/user_service.py` |
| 审计日志 3 个端点 | `endpoints/audit_logs.py` | `endpoints/audit_logs.py` + `services/audit_service.py` |
| 审计装饰器/脱敏/异常检测 | `middleware/audit_log.py` | `middleware/audit_log.py`（告警以结构化日志替代站内通知，通知中心阶段恢复） |
| JWT/密码/策略 | `core/security.py`、`core/password_policy.py` | 同路径，重构为服务层调用 |
| 鉴权依赖/RBAC/RLS | `api/deps.py` | 同路径（KB 表已建，端点待 KB 阶段启用） |
| 前端登录/个人中心/用户管理/审计 | `frontend/src/views/*`（Vue） | `frontend/src/views/*`（React） |

### 验收标准

- [ ] `alembic upgrade head` 在 `hanson_doc_rag` 库执行成功
- [ ] 首次启动自动创建初始超管（`ADMIN_USERNAME`/`ADMIN_PASSWORD`）
- [ ] 登录成功签发双令牌；连续 5 次失败锁定 30 分钟
- [ ] 普通用户无法访问 `/admin/*` 与 `/users`、`/audit-logs`
- [ ] 所有敏感操作在审计日志可见，密码字段落库前脱敏
- [ ] 前端工作台展示项目信息与统计，登录后默认进入

## 2. 阶段 1：知识库与文档管理

- 后端：`/kbs`、`/kbs/{kb_id}`、成员管理、领域模板应用、KB 物理资源生命周期
  （Milvus/MinIO/Nebula/Redis/RLS）。
- 前端：知识库列表、新建向导、概览、成员管理。
- 复用权限：KBContext、`require_role`、六层隔离（表与常量已就绪）。
- 涉及旧代码：`endpoints/kbs.py`、`kb_config.py`、`services/kb/*`、`domain_templates/*`。
- 验收：成员制生效，viewer 只读、editor 可上传、owner 可删除；RLS 验证跨 KB 不可见。

## 3. 阶段 2：文档解析（OCR + Popo + 五维向量）

- 后端：上传/下载/预览、任务队列（arq）、GLM-OCR、MinerU-Popo 重建、
  五维向量入库、BM25 模型、文档查看器数据。
- 前端：文档列表、上传/批量上传、任务进度（SSE/轮询）、PDF 预览、版面叠加。
- 涉及旧代码：`endpoints/kb_documents.py`、`kb_tasks.py`、`services/ocr/`、
  `services/popo/`、`services/vector/`、`tasks/*`。
- 验收：上传 PDF → 完成解析 → 五维向量可检索；任务状态恢复。

## 4. 阶段 3：结构化抽取与配置中心

- 后端：Schema/Prompt/规则/脚本/版本管理、配置校验、v3 抽取管线
  （类别构建 → 混合检索 → LangExtract/BaseExtract 双轨 → 脚本后处理）。
- 前端：抽取配置、Prompt 编辑器、脚本管理、抽取结果/历史。
- 涉及旧代码：`endpoints/extraction_config.py`、`kb_extraction.py`、
  `services/extraction/**`、`extraction_config/**`。
- 验收：配置缺失即报错；双引擎可切换；结果落库可回看。

## 5. 阶段 4：术语集

- 后端：术语集 CRUD、术语绑定、同步（API/DB）、文本标准化。
- 前端：术语集编辑、术语审核、绑定配置。
- 涉及旧代码：`endpoints/kb_term_bases.py`、`kb_terms.py`、`services/term/`。
- 验收：标准化替换、绑定值注入 Schema 白名单。

## 6. 阶段 5：RAG 问答

- 后端：查询理解、混合检索（Dense + BM25 + RRF）、重排、上下文组装、
  LLM 生成（SSE + 溯源）、会话历史。
- 前端：问答页面（流式输出、来源引用）、会话列表、导出。
- 涉及旧代码：`endpoints/kb_qa.py`、`kb_qa_history.py`、`services/rag/**`。
- 验收：流式回答带引用；按 KB 隔离；重排服务补全（原系统已置空待重构）。

## 7. 阶段 6：知识图谱

- 后端：实体关系抽取、NebulaGraph 分 space 存储、子图查询、优雅降级。
- 前端：图谱可视化（Sigma.js）、实体搜索、子图展开。
- 涉及旧代码：`endpoints/kb_graph.py`、`services/graph/**`。
- 验收：Nebula 不可用返回空数据而非 500。

## 8. 阶段 7：公开接口 / 嵌入预览 / 通知 / 备份 / 运维

- 公开一体化抽取（upload/status/result/preview）、嵌入预览页面、
  通知中心（审计异常告警恢复站内通知）、KB 备份恢复、系统清理、
  Prometheus 指标、深健康检查。
- 验收：外部系统可按 `docs/API_CONTRACT.md` 对接，契约不变。

## 9. 阶段 8：旧系统下线

- 数据核对（用户/审计/知识库/文档/抽取结果）。
- 删除 `document-parser-rag-system/` 冻结基线。
- 文档归档，`README` 与 `AGENTS.md` 更新为最终形态。

## 10. 风险与约束

- 每个阶段提交前必须 `alembic upgrade head` + 后端测试 + 前端 `type-check`。
- 数据库迁移前备份；`hanson_doc_rag` 库名固定，不再变更。
- 公开 API 契约（统一响应体/错误码/SSE）全程不变。
- 未迁移功能在旧目录只读保留，不得边迁移边改旧代码。
