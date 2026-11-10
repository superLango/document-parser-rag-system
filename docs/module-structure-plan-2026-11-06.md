# 功能模块化改造方案（2026-11-06）

> 平台名称已定为 **HansonDOC 文档结构化平台**（侧栏品牌名 HansonDOC，副标题“文档结构化平台”）。
> 全站不再使用“知识库”“金属标准拆分工作台”“文档智能解析平台”等旧称呼；“标准拆分”仅作为功能模块名保留。

## 1. 目标

- 取消用户侧的“知识库”组织维度，改为固定的功能模块入口。
- 系统统一为四个功能：**标准拆分**、**委托单解析**、**质保书解析**、**委外报告解析**。
- 本期只完成“标准拆分”，复用当前 文档解析 → 结构化抽取 → 复核 → 导出 的完整链路。
- 其余三个模块本期只做入口与占位页：说明能力、支持的输入、状态为规划中，操作禁用。
- **保持现有视觉风格不变**：浅绿主题、Geist 字体、圆角卡片、入场动效、图标体系全部沿用，只调整信息架构与页面结构。

### 已确认决策（2026-11-06）

1. 采用 **方案 B**：知识库降级为不可见的模块工作区，不改表结构。
2. 现有两个知识库的文档、任务、词典别名 **全部合并到标准拆分**，旧知识库归档隐藏。
3. **工作空间与知识库成员两个概念都移除**：模块对当前工作空间全员可见，不再有成员邀请与角色；侧栏不再出现工作空间入口。

## 2. 方案选型

| 方案 | 做法 | 影响 | 结论 |
| --- | --- | --- | --- |
| A 彻底移除知识库 | 新建 module 表，Document 改挂 module_id，重写权限/成员/词典/审计 | 改动大，迁移风险高，需要改数据库结构 | 不采用 |
| B 知识库降级为“模块工作区” | 保留 `knowledge_bases` 表，每个功能模块固定对应一条内置 KB，用户不可见、不可增删改名 | 复用现有文档/任务/词典/权限全部逻辑，改动集中在新模块层与前端 | **推荐** |
| C 只改导航 | 前端隐藏知识库，后端不动 | 无法真正实现按功能隔离，词典与文档仍混在一起 | 不采用 |

方案 B 的要点：

- 新增模块常量：`standard_split` / `order_parse` / `certificate_parse` / `outsource_report`。
- 每个模块首次访问时自动创建（或复用）一条 `knowledge_bases` 记录，`name` = 模块名，`config.module` = 模块 key；用户侧不再出现“知识库”字样。
- `Document.kb_id`、`DocumentTask`、`documents`、`dictionaries/{kb_id}.json` 全部保持不变，只是 `kb_id` 在语义上等于“模块”。
- 旧知识库的文档迁移到“标准拆分”模块，旧 KB 记录保留归档，便于回滚。
- 模块不提供成员邀请、改名、删除；可见性 = 当前工作空间成员，写权限 = 平台角色 admin / editor。
- 知识库成员表保留在数据库但不再被任何页面或接口引用，模块权限统一走平台角色。

## 3. 信息架构

### 3.1 全局侧栏

```
工作台
标准拆分            ← 本期唯一可用模块
委托单解析          ← 占位
质保书解析          ← 占位
委外报告解析        ← 占位
──────────
个人中心
管理（用户管理 / 审计日志，按权限）
其他（帮助文档 / 关于）
```

“知识库”“工作空间”“知识库成员”从主导航彻底移除，相关页面删除。

### 3.2 标准拆分模块内导航

```
概览 / 文档解析 / 结构化抽取 / 任务列表 / 业务词典
```

与原知识库内导航一致，只是标题变为模块名，去掉成员入口与角色徽章。

### 3.3 路由

| 新路由 | 页面 |
| --- | --- |
| `/` | 工作台 |
| `/standard` | 标准拆分 · 概览 |
| `/standard/documents` | 文档解析 |
| `/standard/extraction` | 结构化抽取 |
| `/standard/extraction/:docId` | 抽取详情 |
| `/standard/documents/:docId/viewer` | 原文查看 |
| `/standard/tasks` | 任务列表 |
| `/standard/dictionary` | 业务词典 |
| `/orders` | 委托单解析（占位） |
| `/certificates` | 质保书解析（占位） |
| `/outsource` | 委外报告解析（占位） |

旧路由 `/kb`、`/kb/:kbId/*` 重定向到 `/standard/*`，避免书签失效。

## 4. 后端改造

### 4.1 新增模块层

`apps/api/hanson_api/modules.py`

- `MODULES`：四个模块的 key、名称、说明、状态、默认 schema 模板、默认词典文件、允许的文件类型。
- `ensure_module_kb(db, workspace_id, key)`：按 `config.module` 查找，缺失则创建并写入默认词典种子。
- `resolve_module(db, principal, key)`：校验可见性并返回模块 KB。

### 4.2 新增接口

| 接口 | 说明 |
| --- | --- |
| `GET /v1/modules` | 四个模块 + 每个模块的文档数、任务数、待复核数 |
| `GET /v1/modules/{key}` | 单模块详情（描述、状态、文件类型） |
| `GET /v1/modules/{key}/dictionary` | 模块词典（替代 `/knowledge-bases/{id}/dictionary`） |
| `POST /v1/modules/{key}/dictionary/aliases` | 模块别名维护 |
| `GET /v1/modules/{key}/dictionary/pending` | 模块待处理新词 |

### 4.3 现有接口调整

- `POST /v1/documents`、`GET /v1/documents`、`GET /v1/tasks`：新增 `module` 参数；保留 `kb_id` 兼容。
- 解析入队的 `dictionary_path` 改为模块词典路径。
- `GET /v1/knowledge-bases*` 保留给内部脚本，前端不再调用。
- API Key 的 `kb_ids` 语义改为模块 key 列表，旧值按映射表兼容。

### 4.4 数据迁移

1. 备份 `postgres` 卷与 `engine-data`（含 `/data/engine/jobs`、`/data/engine/dictionaries`）。
2. 选定一条“标准拆分”模块 KB（优先复用最早创建的知识库），把其余所有知识库的文档、任务、复核记录改挂过去；旧 KB 记录标记归档。
3. 合并词典：全部知识库的别名取并集写入模块词典，`version` 递增；冲突项保留双方别名。
4. 写迁移记录表（旧 kb_id → 模块 key），提供回滚脚本。
5. 旧 KB 记录标记 `archived`，不再出现在任何接口。

## 5. 前端改造

保留全部样式 token 与组件，只改结构：

| 文件 | 改动 |
| --- | --- |
| `layouts/AppShell.tsx` | 侧栏改为四个功能入口；标题映射改为模块名；移除知识库/工作空间入口 |
| `router/index.tsx` | 新路由表；旧 `/kb/*` 重定向 |
| `views/KnowledgeBasesPage.tsx` | 删除（其能力合并到工作台模块卡片） |
| `views/KbDetailLayout.tsx` | 改为 `ModuleLayout`：模块名 + 模块内导航，去掉成员/角色 |
| `views/KbOverviewPage.tsx` | 改为 `StandardOverviewPage`：模块说明、统计、快捷入口 |
| `views/KbDocumentsPage.tsx` | 请求改为 `module=standard_split`，其余不动 |
| `views/KbStructuredExtractionPage.tsx` | 同上 |
| `views/KbTasksPage.tsx` | 同上 |
| `views/DictionaryPage.tsx` | 接口改为模块词典 |
| `views/KbMembersPage.tsx` | 删除 |
| `views/WorkspacesPage.tsx` | 删除（工作空间概念移除） |
| `api/modules/workspaces.ts` | 删除 |
| `views/DashboardPage.tsx` | 四个功能卡片（三个禁用）+ 标准拆分统计与最近任务 |
| `views/ModulePlaceholderPage.tsx` | 新增：模块说明、支持文件、规划中状态、禁用上传 |
| `api/modules/modules.ts` | 新增模块接口封装 |

页面视觉不变：沿用现有卡片、页头、表格、徽章、动效；只替换文案与导航层级。

## 6. 分期计划

| 阶段 | 内容 | 产出 |
| --- | --- | --- |
| P0 | 方案确认（本文件） | 评审通过 |
| P1 | 后端模块层 + 模块接口 + 词典映射 | `/v1/modules` 可用，测试通过 |
| P2 | 前端导航/路由/模块骨架/占位页 | 四个入口可进入，标准拆分页可打开 |
| P3 | 标准拆分全链路迁移（文档→解析→抽取→复核→导出→分享） | 浏览器实测通过 |
| P4 | 数据迁移 + 旧路由重定向 + 回滚脚本 | 原有文档出现在标准拆分下 |
| P5 | 收尾：清理知识库页面、API Key 语义、文档更新 | 发布 r7 镜像 |

## 7. 验收标准

- 侧栏仅四个功能入口，全站不再出现“知识库”和“成员管理”。
- 标准拆分：上传 PDF → 解析 → 查看结构化结果 → 字段复核 → 导出 hansonDoc → 分享，全链路通过。
- 业务词典在标准拆分模块内可检索、可加别名，且只影响该模块。
- 三个占位页可进入，上传/解析按钮为禁用并说明“规划中”。
- 既有文档、历史版本、复核记录、分享链接均正常。
- 配色、字体、圆角、阴影、动效与当前版本一致。

## 8. 风险与对策

| 风险 | 对策 |
| --- | --- |
| 文档归属迁移不可逆 | 迁移前备份数据库与 engine-data，保留旧 KB 记录与映射表 |
| 词典合并冲突 | 别名并集、版本递增，冲突项人工复核 |
| API Key 旧 `kb_ids` 失效 | 保留旧值映射，接口同时接受 kb_id 与 module key |
| 分享链接失效 | 分享 token 绑定 document_id，不受 KB 语义影响，回归验证即可 |
| 三个新模块后续接入 | 模块层已预留 schema 模板、文件类型、词典种子，后续只需补解析服务 |
