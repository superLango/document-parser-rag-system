# 专业术语集模块实施方案（当前项目，2026-08-12）

> 目标：建设 KB 隔离的专业术语集管理模块（术语集 + 术语条目），
> 参考原项目功能与 UI 布局，但按当前项目（React + 浅绿白主题、
> PG+RLS、无 LLM 兼容层、抽取模块后续建设）优化，**不照搬代码**。
> 每阶段完成后按 qa/TESTING_PROCESS.md 铁律执行五层测试。

## 1. 功能范围（参考原项目，按当前项目裁剪）

| 功能 | 原项目 | 当前项目本期 |
|------|--------|--------------|
| 术语集管理（CRUD） | ✅ | ✅ |
| 三种数据源（manual/api/db） | ✅ | ✅（含连接测试/预览/同步，带安全校验） |
| 术语条目管理（CRUD/批量/导出/分类） | ✅ | ✅ |
| 审核流（pending→approve/reject） | ✅ | ✅ |
| 文本标准化替换（standardize_text） | ✅ | ❌（与 RAG/抽取联动时再建，本期只建数据与管理） |
| 术语合并 | ✅ | ❌（后续抽取联动阶段） |
| 与抽取联动（名称展开/Query 词组/字段取值） | ✅ | 预留加载器接口，联动在抽取模块接入 |

## 2. 数据模型（新增 2 表，全部 kb_id + RLS）

### 2.1 term_bases（术语集）

```sql
CREATE TABLE term_bases (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kb_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    name VARCHAR(128) NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    source_type VARCHAR(16) NOT NULL DEFAULT 'manual',  -- manual | api | db
    source_config JSONB NOT NULL DEFAULT '{}',          -- api/db 连接配置（脱敏存储）
    columns JSONB NOT NULL DEFAULT '[]',                -- 列定义 [{name,type,label}]
    column_aliases JSONB NOT NULL DEFAULT '{}',         -- 新表头名 → 原始字段/内置字段
    sync_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    last_synced_at TIMESTAMPTZ,
    status VARCHAR(16) NOT NULL DEFAULT 'active',       -- active | disabled
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ,
    UNIQUE (kb_id, name)
);
```

### 2.2 terms（术语条目）

```sql
CREATE TABLE terms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    kb_id UUID NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    term_base_id UUID NOT NULL REFERENCES term_bases(id) ON DELETE CASCADE,
    term_name VARCHAR(256) NOT NULL,            -- 原始/规范术语名
    standard_name VARCHAR(256) NOT NULL DEFAULT '',  -- 标准术语
    english_term VARCHAR(256) NOT NULL DEFAULT '',
    definition TEXT NOT NULL DEFAULT '',
    category VARCHAR(128) NOT NULL DEFAULT '',
    standard_number VARCHAR(128) NOT NULL DEFAULT '',
    synonyms JSONB NOT NULL DEFAULT '[]',
    aliases JSONB NOT NULL DEFAULT '[]',
    extras JSONB NOT NULL DEFAULT '{}',         -- 分组字段/扩展（group_field 联动预留）
    status VARCHAR(16) NOT NULL DEFAULT 'active',  -- active | pending | rejected
    reviewed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    reviewed_at TIMESTAMPTZ,
    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ,
    deleted_at TIMESTAMPTZ
);
CREATE INDEX idx_terms_kb_base ON terms (kb_id, term_base_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_terms_kb_category ON terms (kb_id, category) WHERE deleted_at IS NULL;
CREATE INDEX idx_terms_kb_status ON terms (kb_id, status) WHERE deleted_at IS NULL;
```

RLS：两表均 `ENABLE/FORCE ROW LEVEL SECURITY`，SELECT=当前 KB 有效成员，
INSERT/UPDATE/DELETE=当前 KB owner/admin/editor（复用 009 策略模式）。

## 3. 后端 API 设计

### 3.1 术语集 `/kb/{kb_id}/term-bases`（新端点 kb_glossary.py）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | / | 成员 | 术语集列表（分页 + keyword） |
| POST | / | editor+ | 新建（manual/api/db） |
| GET | /{base_id} | 成员 | 详情（含词条数/最近同步） |
| PUT | /{base_id} | editor+ | 更新（名称/描述/列定义/别名/同步开关） |
| DELETE | /{base_id} | editor+ | 删除（级联删词条） |
| POST | /test-api | editor+ | API 源连通测试（返回提取行/列预览） |
| POST | /test-db | editor+ | DB 源连通测试 |
| POST | /db-tables | editor+ | DB 表列表 |
| POST | /preview-sql | editor+ | SQL 预览 |
| POST | /{base_id}/sync | editor+ | 从源同步词条 |

### 3.2 术语 `/kb/{kb_id}/terms`（同一端点文件）

| 方法 | 路径 | 权限 | 说明 |
|------|------|------|------|
| GET | / | 成员 | 分页列表（term_base_id/category/status/keyword 过滤） |
| GET | /categories | 成员 | 分类列表（去重） |
| GET | /export | 成员 | 导出 CSV（当前 KB） |
| GET | /{term_id} | 成员 | 详情 |
| POST | / | editor+ | 创建 |
| POST | /batch | editor+ | 批量导入（≤5000 条/次） |
| PUT | /{term_id} | editor+ | 更新 |
| PUT | /{term_id}/review | editor+ | 审核（approve/reject） |
| DELETE | /{term_id} | editor+ | 删除 |

### 3.3 安全与健壮性优化（相对原项目）

1. **外部数据源 SSRF 防护**：api/db 源地址仅允许 http/https（api）与 mysql（db），
   禁止解析到回环/链路本地/云元数据地址（127.0.0.0/8、169.254.0.0/16、0.0.0.0、::1），
   连接超时 10s、响应体上限 5MB；
2. **凭据脱敏**：source_config 中 password 等字段入库前加密或掩码存储，API 响应脱敏；
3. **导入校验**：批量 ≤5000 条/次，字段长度限制（术语名 ≤256、定义 ≤2000、同义词/别名 ≤50 个），
   同 (kb_id, term_base_id, term_name) 幂等（更新或跳过，配置化）；
4. **审核流**：新建词条默认 active（手动）；外部同步词条默认 pending，需 review；
5. **并发**：同步/批量导入使用行锁/幂等 upsert，避免重复词条。

## 4. 前端设计（浅绿白主题，参考原项目布局优化）

### 4.1 术语集主页 `KbGlossaryPage`（路由 glossary）

- 顶部：PageHeader（专业术语集）+ 新建按钮（editor+ 可见）
- 术语集卡片网格（参考原项目 Terms.vue 布局）：
  名称 / 来源类型徽标（手动=浅绿、API=浅蓝、DB=浅紫，按 UI_THEME 色阶调整）/
  词条数 / 最近同步时间 / 同步开关 / 操作（编辑、同步、删除）
- 空态：无术语集引导创建
- 新建向导弹窗：三步 Tabs（数据源选择 → 源配置（manual 表单 / API 表单+测试 / DB 表单+连接+表/SQL 预览）→ 列映射确认）

### 4.2 术语集编辑器 `KbGlossaryEditorPage`（路由 glossary/:baseId）

- 顶部：返回 + 术语集名 + 词条数 + 操作（批量导入、导出、审核模式切换）
- 筛选：关键词搜索 + 分类下拉 + 状态下拉（全部/待审核/已通过/已驳回）
- 表格：术语 / 标准名 / 英文 / 分类 / 同义词 / 状态徽标 / 操作（编辑、审核、删除）
- 批量导入弹窗：粘贴 CSV/JSON 或上传文件，预览前 10 条，确认导入
- 新增/编辑弹窗：术语表单（术语名/标准名/英文/分类/标准号/定义/同义词/别名/扩展字段）
- 移动端：卡片式列表替代表格（横向滚动表格 + 卡片切换）

## 5. 分阶段实施计划（每阶段铁律验收）

### S1：数据库与后端模型
- 新增 `010_term_glossary.py` 迁移（2 表 + 索引 + RLS）
- `app/models/glossary.py`（TermBase / Term）
- `app/models/__init__.py` 注册
- 测试 M33-S1：迁移幂等/RLS/模型约束（L1/L2/L4）

### S2：术语集 API（含外部源安全校验 + 定时同步）
- `app/api/v1/endpoints/kb_glossary.py` 术语集端点
- `app/services/glossary/term_base_service.py`（CRUD + 外部源测试/预览/同步 + SSRF 校验 + 凭据脱敏）
- `app/services/glossary/source_api.py` / `source_db.py`（异步 httpx / aiomysql 客户端，超时与大小限制）
- `app/services/glossary/term_base_loader.py`：**最小数据读取接口（分组+缓存），docstring 登记"仅供抽取联动复用，禁止抽取阶段重复建设"**
- `app/tasks/arq_worker.py`：注册 `sync_term_bases_cron`（cron 小时可配置，扫描 sync_enabled 术语集同步）
- 测试 M33-S2：L1-L5（viewer/editor/非成员/跨 KB/SSRF/超时/并发/cron 同步）

### S3：术语 API
- 术语 CRUD / 批量导入 / 审核 / 导出 / 分类 / 过滤（同一端点文件）
- `app/services/glossary/term_service.py`
- 测试 M33-S3：L1-L5（幂等/上限/审核流/导出编码/并发导入）

### S4：前端术语集主页
- `api/modules/glossary.ts` + types
- `KbGlossaryPage`（卡片网格 + 新建三源向导 + 测试/预览 + 操作）
- 路由注册（替换 glossary 占位）
- 测试 M33-S4：tsc/build + Playwright E2E（卡片/新建 manual/API 测试/权限/移动端）+ 截图入帮助文档；
  遵守 [TESTING_PROCESS.md 第 6 节入口闭环铁律](../qa/TESTING_PROCESS.md)：真实 HTTP 源走通
  卡片入口→创建→数据落库（词条数）→点击卡片进内页→返回列表

### S5：前端术语管理
- `KbGlossaryEditorPage`（筛选/表格/批量导入/审核/导出）
- 帮助文档更新
- 测试 M33-S5：E2E（筛选/导入/审核/导出/权限/移动端）；
  遵守入口闭环铁律：列表卡片→管理页→操作→返回列表状态一致

### S6：整体验收
- 真实链路（建术语集 → manual 录入 → 批量导入 → 审核 → 导出 → API 源同步）
- M33 全量五层 + 覆盖率统计表归档 `qa/results/INDEX_S8_GLOSSARY_TEST_REPORT.md`

## 5.1 定时同步配置（C3）

- `TERM_SYNC_CRON_HOURS`：cron 小时列表（默认 `[3]`，每日 3 点；可配 `[2,14]` 等）
- `TERM_SYNC_BATCH_LIMIT`：单轮同步术语集数量上限（默认 20）
- 同步语义：扫描 `sync_enabled=true AND status=active` 的术语集，
  按 (kb_id, term_base_id, 外部唯一标识) 幂等 upsert（外部无唯一标识时按 term_name），
  更新 `last_synced_at`；单术语集失败记录日志不中断整轮。

## 5.2 迁移代码审查（硬性规则，每阶段强制）

1. **不迁移无用/废弃逻辑**：原项目术语模块中已裁剪能力（standardize_text、术语合并、
   旧全局 terms.py 兼容端点、Dark-Tech 配色等）不得以“顺手保留”形式带入；
2. **交付前审查清单**：
   - 无调试残留（`print`/`DBG` 日志/`if False`/临时脚本）；
   - 无未使用 import、未使用变量、死分支；
   - 无原项目文件整体复制（含注释与命名习惯）；新代码符合当前项目规范（ruff/mypy/tsc）；
   - 配置、常量、术语命名有明确用途并写入 GLOSSARY（业务术语表）；
3. **审查记录**：每个阶段报告附「迁移审查清单」，列出检查项与结论；
4. **测试代码同样审查**：测试中不得出现 noop 占位、`if False else None` 之类残留。

## 6. 新增文件总览

后端：
- `alembic/versions/010_term_glossary.py`
- `app/models/glossary.py`
- `app/services/glossary/{__init__,term_base_service,term_service,source_api,source_db,term_base_loader}.py`
- `app/api/v1/endpoints/kb_glossary.py`（术语集 + 术语端点）
- `app/schemas/glossary.py`

前端：
- `src/api/modules/glossary.ts`、`src/api/types.ts`（TermBase/Term 类型）
- `src/views/kb/KbGlossaryPage.tsx`、`KbGlossaryEditorPage.tsx`
- `src/router/index.tsx`（glossary、glossary/:baseId）
- `src/content/help.ts` + `docs/HELP_DOCS.md`

测试：
- `qa/unit|integration|boundary|security/test_glossary*.py`
- `qa/functional/e2e_glossary.mjs`
- `qa/results/INDEX_S8_GLOSSARY_TEST_REPORT.md`

## 7. 测试模块登记

qa/TESTING_PROCESS.md 新增 M33 专业术语集（S1-S6），并发用例：
并发创建同名词条（幂等）、并发批量导入、并发同步、跨 KB 并发隔离。

## 8. 待确认内容

| # | 事项 | 推荐 | 说明 |
|---|------|------|------|
| C1 | api/db 数据源 | 本期支持（带 SSRF/凭据脱敏）或仅 manual | 企业内网可连内网 API/DB；若本期只做 manual，S2/S4 相应裁剪 |
| C2 | 审核流 | 保留（外部同步 pending → review） | 标准文档术语建议留审核 |
| C3 | 同步方式 | **手动同步 + arq cron 定时同步（本期实现）** | `sync_term_bases_cron` 每日/可配置小时扫描 `sync_enabled=true` 的术语集执行增量同步，幂等 upsert |
| C4 | 批量导入上限 | 5000 条/次 | 可调 |
| C5 | 术语默认状态 | 手动=active，外部同步=pending | 与 C2 绑定 |
| C6 | term_base_loader 加载器 | **S2 建立最小数据读取接口并在方案/代码中登记归属**，抽取阶段直接复用不重复建设 | 在 `app/services/glossary/term_base_loader.py` 提供 load_term_base（按 kb+base 分组读取+缓存），docstring 注明仅供抽取联动使用 |
| C7 | 术语集编辑器形态 | 独立路由页 glossary/:baseId | 与原项目 TermSetEditor 一致 |
