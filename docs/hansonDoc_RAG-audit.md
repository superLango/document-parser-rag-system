# hansonDoc_RAG 代码审计报告（初稿）

> 阶段：M1.9a
> 状态：draft v0.1（基于只读审计）
> 日期：2026-10-27
> 审计对象：`grainuser@192.168.188.75:~/hansonDoc_RAG`（commit `c74ea91`）
> 约束：**只读审计，未修改 188.75 原项目任何文件**；所有迁移/改造在当前项目 `f:\hanson\hanson_doc_parse` 内进行。

---

## 1. 审计范围与方法

### 1.1 范围

- 后端：文档/任务/Outbox/arq、parsekit、存储、RBAC/审计、术语集、integration、LLM 客户端、抽取 V3。
- 前端：路由、页面、API 模块、状态管理。
- 依赖与配置：`backend/requirements.txt`、`frontend/package.json`、部署配置。

### 1.2 方法

- 源码阅读（只读）；
- 文档与实现对照（`docs/`、README、代码注释）；
- 已知问题清单复核；
- 依赖清单检查；
- 未做运行时渗透测试/压测（后续 M1.9 补）。

### 1.3 结论口径

| 处置 | 含义 |
|---|---|
| 迁移 + 审计 | 代码可复用，但必须修复审计问题、补测试后迁移 |
| 改造 + 审计 | 思路可用，需裁剪/改造后迁移 |
| 重写 | 接口/逻辑保留，代码重写 |
| 删除 | 不进入当前项目，彻底移除 |

---

## 2. 模块处置清单

| 模块 | 路径 | 处置 | 理由 | 审计重点 |
|---|---|---|---|---|
| parsekit | `backend/app/services/parsekit/` | 迁移 + 审计 | 解析链路成熟 | 并发、失败语义、文本层双源、产物契约 |
| 文档模型/服务 | `backend/app/models/document.py`、`services/document_service.py` | 迁移 + 审计 | 文档/任务基础 | 状态机、删除/清理、幂等 |
| 任务/Outbox/arq | `backend/app/tasks/`、`models/document.py` 中 Outbox/DLQ | 迁移 + 审计 | 可靠性设计可复用 | 重试、心跳、事务边界、状态回写 |
| 存储 | `backend/app/services/storage.py` | 迁移 + 审计 | MinIO 封装 | 对象键、越权、生命周期 |
| RBAC/审计 | `backend/app/services/rbac_service.py`、`security.py`、`middleware/audit_log.py` | 迁移 + 审计 | 知识库隔离保留，不简化 | RLS 绕过、审计完整性、越权 |
| 知识库/工作空间 | `models/knowledge_base.py`、`workspace.py`、`services/kb_service.py` | 迁移 + 审计 | 业务确认不简化，后续完善 | RLS、成员/群组授权、邀请 |
| API Key | `models/api_key.py`、`services/` | 迁移 + 审计 | 外部对接需要 | 哈希、作用域、撤销、审计 |
| 术语集 | `backend/app/models/glossary.py`、`services/glossary/` | 改造 + 审计 | 改为业务词典/别名 | 同步语义、pending/active、误合并 |
| integration | `backend/app/api/v1/endpoints/integration.py`、`services/integration_service.py` | 重写/改造 | 引擎任务入口 | 认证、幂等、限流、错误码 |
| LLM 客户端 | `backend/app/services/llm/llm_client.py`、`kb_resource_service` | 迁移 + 审计 | OpenAI 兼容 | 超时、重试、并发、JSON |
| 抽取 V3 | `backend/app/services/extraction/pipeline.py`、`category_builder*.py` | 删除 | 41 类检索式，不符合标准拆分 | 不迁移 |
| `table_to_rows` | `backend/app/services/extraction/table_to_rows.py` | 删除 | 不展开 rowspan/colspan | 不迁移 |
| chunker/retrieval | `backend/app/services/indexing/` | 删除 | 本期不做 RAG | 不迁移 |
| 前端主框架 | `frontend/src/views/`、`api/modules/` | 按 `frontend-scope.md` 取舍 | 保留/改造/删除 | 迁移部分审计 |
| RAG/图谱 | 占位/旧版 | 删除 | 不属于标准拆分 | 不迁移 |

---

## 3. 已知问题与风险

> 严重度：S1 阻断/安全，S2 高，S3 中，S4 低。标“待复核”的需在 M1.9 代码级确认。

| # | 问题 | 证据 | 严重度 | 处置 |
|---|---|---|---|---|
| A1 | integration 端点无认证，内部用 superuser 会话绕过 RLS | `backend/app/api/v1/endpoints/integration.py`：`_superuser_ctx` + 无依赖鉴权 | S1 | **已关闭（P0）**：不迁移旧入口；平台端点强制 JWT/API Key + 知识库成员校验，无 superuser 会话；引擎端口可选 `ENGINE_INTERNAL_TOKEN` |
| A2 | 独立结果页路由无登录保护 | `frontend/src/router/index.tsx`：`/integration/task/:taskId` 无 `RequireAuth` | S1 | **已关闭（P0）**：改为 15 分钟 HMAC 签名分享令牌，过期/篡改返回 401 |
| A3 | `return_type=object` 未实现，标准信息返回错误数组 | `docs/EXTRACTION_ISSUE_ANALYSIS_20260817.md`；`lang_pkg_extractor._parse_result` | S2 | 旧抽取不迁移；新引擎按 schema 输出 |
| A4 | `table_to_rows` 不做 rowspan/colspan 合并 | `backend/app/services/extraction/table_to_rows.py` 注释 | S2 | 删除；改用 TableGrid |
| A5 | 大表被 chunk 切碎，检索窗口决定完整性 | `docs/EXTRACTION_ISSUE_ANALYSIS_20260817.md`；`pipeline.py` 上下文拼接 | S1（业务） | 删除检索式主路径；引擎按表/条款覆盖 |
| A6 | 41 类固定类别 + 检索式抽取，无法证明覆盖 | `docs/V3_FINAL_PIPELINE.md`；`category_builder*.py` | S2 | 删除；M1.7 ItemInventory |
| A7 | `match_record` 语义优先 + 阈值硬编码，存在误合并 | `backend/app/services/extraction/script_tools.py`：`_match_threshold=0.90`、编辑距离 0.85 | S2 | 改造：精确/别名优先，阈值按业务标定 |
| A8 | 术语集同步语义可能丢审核状态/源端删除不清理 | `docs/TERMS_ALIGNMENT_PLAN.md` G6；`term_base_service.py` | S2（待复核） | 改造：版本化 + 差异同步 + pending 保留 |
| A9 | 任务失败/重试/状态回写不一致风险 | `docs/STRUCTURED_EXTRACTION_DESIGN_PLAN.md` B11；`tasks/` | S2（已改造） | 状态机/抢占/心跳回收/锁定重试测试 |
| A10 | 依赖未锁定（大量 `>=`） | `backend/requirements.txt` | S2（部分关闭） | 直接依赖已 `==` 锁定；pip-audit/许可证扫描待 CI |
| A11 | 前端仅 `tsc --noEmit`，无单元测试 | `frontend/package.json` scripts | S3 | 迁移部分补测试；主链路 E2E |
| A12 | RLS/多租户复杂，需确认审计而非裁剪 | `docs/ARCHITECTURE.md` 六层隔离 | S3 | 保留知识库隔离，迁移+审计 |
| A13 | OCR/解析失败语义 partial/failed 需确认 | `docs/DOCUMENT_PARSING_PLAN.md` U13 | S3（待复核） | 迁移时统一错误码 |
| A14 | 前端大页面耦合抽取配置/术语集/结果 | `KbExtractionDetailPage.tsx` 等 | S3 | 改造时拆分标签页/移除旧配置 |

---

## 4. 安全与数据审计

### 4.1 认证/授权

- integration 无认证/Superuser 绕过：必须重写；
- 独立结果页无登录：必须加短期令牌；
- RBAC 保留，但多租户/工作空间/群组按需裁剪；
- API Key 仅保留业务对接需要的最小能力。

### 4.2 文件与存储

- 上传类型/大小校验已有，迁移时保留；
- 对象键需检查路径注入/越权；
- 生命周期/清理策略保留；
- 证据文件走对象存储，不塞数据库大字段。

### 4.3 数据隔离

- 业务确认知识库/工作空间/群组不简化，保留多租户隔离；
- 六层隔离不直接照搬，但 RBAC/RLS 能力保留并审计；
- 所有查询/写入必须带知识库上下文；
- 迁移时保留审计，删除不必要的复杂度但不裁剪功能。

### 4.4 依赖

- `requirements.txt` 大量 `>=`，需锁定并做漏洞/许可证扫描；
- 前端依赖较干净，需锁定 `pnpm-lock`；
- 移除 RAG/检索/旧抽取相关依赖，减少攻击面。

---

## 5. 迁移前必须关闭的审计项

- [ ] A1 integration 认证/越权；
- [ ] A2 结果页鉴权；
- [ ] A4/A5/A6 确认不迁移旧抽取/表格/检索路径；
- [ ] A7 匹配阈值与误合并；
- [ ] A8 术语集同步语义；
- [x] A9 任务状态机；
- [ ] A10 依赖锁定与扫描；
- [ ] A12 数据隔离方案；
- [ ] 迁移模块补单元/契约测试；
- [ ] 高风险项为 0 才允许迁移。

---

## 6. 审计门与后续

### 6.1 G1.9a 审计门

- 模块处置清单完整（迁移/改造/删除）；
- 已知问题逐项有结论；
- 高风险（S1）= 0，或已隔离/不迁移；
- 依赖/安全/数据隔离报告完成；
- 迁移代码测试计划就绪。

### 6.2 后续（M1.9）

- 迁移代码先修 bug、补测试，再合并；
- 每次迁移提交附审计项关闭记录；
- 删除模块同步移除依赖/路由/菜单/表；
- 运行静态检查（ruff/mypy/bandit 或等价）+ CI；
- 不修改 188.75 原项目。

---

## 7. 已确认决策（2026-10-27）

1. 知识库/成员/工作空间/群组/邀请**不简化**，后续继续完善；
2. **需要 API Key/外部对接**，保留 API Key 能力；
3. 业务词典**允许人工别名与 pending 条目**；
4. 复核**单角色**即可，不做多人/多角色流转。

## 8. 说明

- 本报告是初稿，未做运行时渗透/压测；
- 标注“待复核”的项需在 M1.9 代码级确认；
- 审计只读，188.75 原项目未发生任何变更。
