# 专业术语集：原项目 vs 当前实现完整对比（2026-08-12）

> 调研对象：
> - 原项目 `document-parser-rag-system`：后端 `api/v1/endpoints/kb_term_bases.py`、
>   `kb_terms.py`、`schemas/term.py`、`services/term/term_service.py`、
>   `services/extraction/rule_engine/term_base_loader.py`；
>   前端 `views/Kb/Terms.vue`、`views/Kb/TermSetEditor.vue`、`api/modules/kb.ts`。
> - 当前项目 `hansonDoc_RAG`：后端 `app/models/glossary.py`、
>   `app/services/glossary/*`、`app/api/v1/endpoints/kb_glossary.py`；
>   前端 `views/kb/KbGlossaryPage.tsx`、`KbGlossaryEditorPage.tsx`、
>   `api/modules/glossary.ts`、`lib/glossaryImport.ts`。

## 0. 重要事实（禁止编造项）

1. **原项目仓库缺少 `app/models/` 目录**：`git ls-files backend/app/models` 为空，
   但代码中 `from app.models.term import Term, TermMapping`、迁移 001 中
   `import app.models` 均引用该包。因此原项目术语 ORM 模型文件在本次调研中
   **未找到实际源码**，其表结构只能依据 alembic 001 说明（表名/隔离策略）、
   端点 ORM 用法与前端类型推断。
2. 原项目迁移 001 明确：`terms`、`term_mappings` 启用 kb RLS；
   **`term_bases` 是全局表，不隔离**（注释原文：“kb_members / kb_category_enums /
   term_bases 等全局表不隔离”）。
3. 原项目前端存在 `importTermBaseJson`（/import-json）与
   `importTermBaseFromSource`（/import-from-source）两个 API 封装，但
   后端全文检索**未找到对应端点**，属于前端挂空/死接口。

## 1. 原项目功能全貌

### 1.1 后端端点

`/kbs/{kb_id}/term-bases`（1006 行，统一术语集）：
- CRUD：列表（含词条数）、创建（manual/api/db，editor+）、更新、删除（**硬删**，cascade）
- 数据源：test-api（支持 GET/POST/PUT/DELETE、路径/Query/Header 参数、body、json_path、超时 30s）、
  test-db、db-tables、preview-sql（前 5 条）
- `/{base_id}/terms`：术语集内分页列表，支持 keyword + **search_field 动态列搜索**
  （manual 固定字段 / api-db 按 extras 字段 ilike）
- `PUT /{base_id}/terms/batch`：**批量增改删一次提交**（items + deleted_ids）
- `POST /{base_id}/sync`：**清空现有术语后全量重导**
- 创建时若传 import_data 则直接导入（`_rows_to_terms`）

`/kbs/{kb_id}/terms`（377 行，术语库）：
- 列表（category/status/keyword 过滤）、分类、详情、创建、批量导入（body 数组，无上限）、
  更新、审核（approve→active / reject→**deprecated**）、删除（硬删）、导出（**JSON**）

### 1.2 数据模型（推断）

- `term_bases`：id/kb_id/name/description/source_type/source_config/columns/
  column_aliases/sync_enabled/last_synced_at；**无 status、无 deleted_at、无 created_by**
- `terms`：id/kb_id/term_base_id/term_name/standard_name/definition/category/
  standard_number/synonyms/aliases/extras/status/reviewed_by/reviewed_at；
  **无 deleted_at、无 english_term 独立字段**（英文名存 standard_name）
- `term_mappings`：kb_id/term_id/original_text（同义词持久化映射，Term.mappings 关系）
- 删除语义：全部硬删（db.delete）

### 1.3 服务层能力（term_service.py，558 行）

- `standardize_text`：**文本标准化替换**（术语名+同义词模糊匹配、最长优先、重叠消解、返回替换记录）
- `get_or_create_term`、`add_synonym`（写 synonyms + TermMapping）、`search_terms`、
  `get_term_tree`（术语+映射树）、`merge_terms`（**术语合并**：吸收同义词+迁移映射+删源）、
  `import_terms`（按 term_name 大小写不敏感幂等跳过）
- `term_base_loader.py`（204 行）：TermBaseValueLoader，按 term_base_id 分组加载 active 词条并缓存，
  支持 group_field 分组、column_aliases 反向解析、get_group_values、invalidate —— 供抽取规则引擎取值

### 1.4 前端

`Terms.vue`（术语集主页，Dark-Tech 深色主题）：
- 创建向导单弹窗三步：基本信息 → 数据源类型（manual/api/db 卡片）→ 对应配置
- API 配置：方法（GET/POST）、**路径/Query/Header 参数增删 + 启用开关**、POST body、json_path、
  测试按钮显示“测试成功（N 条数据）”+ 前 5 条预览表
- DB 配置：连接成功后才展开表/SQL 选择 + 预览前 5 条
- 创建：manual 创建后**直接跳转编辑器**；api/db **必须先测试/预览成功**，
  按钮为“创建并导入数据”，**创建时不传 import_data，创建后自动调 sync 全量导入**，
  同步失败提示“请在详情页手动同步”，完成后跳转编辑器
- 卡片：整卡可点击进编辑器，hover 显示 查看/同步/删除（同步/删除带 confirm，同步提示“覆盖现有数据”）

`TermSetEditor.vue`（术语集编辑器）：
- manual：**行内表格批量编辑**（新增行/修改标记/删除标记/恢复，chips 管理同义词与别称，
  “保存全部”一次 batch save，含术语集名称/描述保存）
- api/db：**只读动态列展示**（数据全来自 extras，表头用 column_aliases 显示名），
  提供“从数据源同步”与“修改字段”（右侧滑出别名面板，改显示名不改变量名）
- 搜索支持**字段级搜索**（manual 固定字段 / api-db 动态列）
- viewer 只读，editor+ 可编辑

## 2. 当前实现功能全貌

后端：
- `term_bases` + `terms` 两表全部带 kb_id + RLS（迁移 010），**软删**（deleted_at +
  部分唯一索引支持同名重建）；terms 有独立的 standard_name 与 english_term
- 术语集 CRUD、test-api/test-db/db-tables/preview-sql（**SSRF 防护、凭据 Fernet 加密、
  响应掩码、10s 超时、5MB 上限、SQL 表名反引号转义**）
- 同步：`sync_term_base` 幂等 upsert（不删除源端已消失词条），外部词条默认 pending
- 术语 CRUD、分类、审核（active/pending/**rejected**）、批量导入（≤5000、幂等、批内去重）、
  CSV 导出（UTF-8 BOM）
- arq cron 定时同步（TERM_SYNC_CRON_HOURS）
- `term_base_loader.py`：C6 预留最小加载器（分组 + 缓存），docstring 登记仅供抽取复用

前端：
- `KbGlossaryPage`：卡片网格 + 三源向导（manual 表单 / API 地址+方法+headers 文本+json_path+
  密码 / DB 主机+端口+账号+库+表/SQL），创建时**把预览数据作为 import_data 随创建提交**，
  卡片可点击进编辑器 + “管理”按钮
- `KbGlossaryEditorPage`：关键词/分类/状态筛选、单条表单（新建/编辑 Dialog）、
  CSV/JSON 批量导入（预览前 10 条）、审核（通过/驳回）、CSV 导出、删除确认、移动端卡片
- 权限：viewer 只读可导出；editor+ 可写

## 3. 逐项对比表

| 维度 | 原项目 | 当前实现 | 评价 |
|------|--------|----------|------|
| 隔离 | term_bases 全局表不隔离；terms/term_mappings RLS | term_bases、terms 均 kb_id + RLS | 当前更符合“知识库即隔离边界” |
| 删除 | 硬删 | 软删（可恢复） | 当前更安全 |
| 字段 | 英文名存 standard_name，无独立 english_term | standard_name + english_term 分离 | 当前语义更清晰 |
| 状态 | active/pending/deprecated | active/pending/rejected | 语义等价 |
| 审核 | create 时 reviewer 记为创建者；reject→deprecated | 创建不记审核人；reject→rejected | 当前更规范 |
| 安全 | 无 SSRF、凭据明文入库且接口原样返回、SQL 表名直接拼接 | SSRF + Fernet 加密 + 掩码 + 超时/上限 + SQL 转义 | 当前大幅领先 |
| 同步语义 | **清空后全量重导** | **幂等 upsert，不清空** | 当前不会丢手工词条，但源端删除不同步 |
| 创建导入 | **创建后自动全量 sync** | **仅导入预览 5-10 条** | ⚠️ 当前是最大功能缺口，见 §4 |
| api/db 原始字段 | 全部存 extras，动态列展示/按列搜索/别名编辑 | 仅映射内置字段，extras 只存 external_id | ⚠️ 非标准字段会丢，见 §4 |
| API 参数 | 路径/Query/Header 参数 + body + 超时 | headers 文本 + GET/POST + json_path | 当前较简 |
| manual 编辑 | 行内表格批量编辑（增改删+保存全部） | 单条表单 + 批量导入 | 交互差异，原项目更适合批量录入 |
| 批量导入 | body 数组、无上限、不幂等 | ≤5000、幂等、批内去重、前端预览 | 当前更健壮 |
| 导出 | JSON | CSV（Excel 友好） | 当前更实用 |
| 定时同步 | 无（仅手动） | arq cron 可配置 | 当前更强 |
| 文本标准化/合并/映射表 | standardize_text、merge_terms、TermMapping | 有意裁剪，C6 只预留 loader | 抽取联动阶段需决策是否补齐 |
| 前端主题/技术栈 | Vue + Dark-Tech | React + 浅绿白 | 按项目既定方向 |
| 同步前确认 | 有 confirm（提示覆盖） | 无确认 | 建议补 |
| 测试 | 未见 QA 铁律/测试资产 | 五层铁律 + 入口闭环 E2E | 当前领先 |

## 4. 需要补齐/决策的差异（按优先级）

1. **P0：创建后全量同步**。当前“创建即导入”只写预览子集（API 10 条 / DB 5 条），
   与用户“把查询到的内容插入进去”的意图不符。建议采用原项目方案：
   创建时保存配置 → 创建后自动调用 sync 全量导入 → 失败时明确提示可手动同步；
   或在创建接口内由后端直接全量拉取。
2. **P0：api/db 动态列保留与展示**。同步时所有原始字段写入 extras，
   编辑器按 columns 动态列展示，并提供字段别名（column_aliases）修改显示名；
   否则非标准字段（如牌号、规格等业务列）会丢失。
3. **P1：API 参数面板**。补齐路径/Query/Header 参数、POST body、超时配置，
   替代当前单行 headers 文本。
4. **P1：manual 行内批量编辑**（可选）：增加“添加一行/保存全部”以对齐原项目录入效率。
5. **P1：同步确认**：手动同步前提示“将按数据源覆盖式更新词条”。
6. **P2（抽取联动阶段）**：standardize_text、术语合并、TermMapping 同义词映射
   是否按原项目补齐，需结合抽取模块方案决策（当前 loader 已预留入口）。

## 5. 结论

当前实现不是原项目代码的迁移，而是按“KB 隔离 + RLS + 浅绿白 React”架构重写，
安全与健壮性（SSRF、凭据加密、软删、幂等导入、上限校验、定时同步、五层测试）
全面优于原项目。但功能性上存在两个 P0 差距（创建后全量同步、api/db 动态列保留），
以及若干 P1 交互差异（API 参数、manual 批量编辑、同步确认）。
建议在 S6 或抽取联动前按 §4 清单补齐 P0，其余按优先级决策。
