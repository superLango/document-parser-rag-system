# 专业术语集功能对齐方案（原项目 main 分支 → 当前项目）

> 依据：`document-parser-rag-system` main 分支（术语模块唯一存在分支）真实源码
> （Terms.vue / TermSetEditor.vue / kb_term_bases.py / kb_terms.py / term_service.py / term_base_loader.py / kb.ts）。
> 注意：main 分支缺 app/models 目录，模型字段为推断；dev 分支无术语模块。

## 1. 原项目功能全景（用户可见/接口可见）

### 1.1 术语集主页（Terms.vue）
- 卡片列表：名称/描述/来源徽标/词条数/上次同步；刷新；hover 查看/同步/删除（confirm）
- 新建向导：基本信息 + 三源选择
  - API：GET/POST、url、json_path、路径/Query/Header 参数动态增删（启用开关）、POST body、测试接口（状态码/条数/前 5 条预览）
  - DB：主机/端口/用户/密码/库/字符集、测试连接（成功自动拉表）、表/SQL 切换、预览前 5 条
  - 创建约束：api/db 必须先测试/预览成功；按钮“创建并导入数据”
  - manual 创建后直接进编辑器；api/db 创建后自动全量同步 → 进编辑器
- 同步/删除均带 confirm（同步提示“现有数据将被覆盖”）

### 1.2 术语集编辑器（TermSetEditor.vue）
- 返回列表；术语集信息（名称/描述可编辑，manual 保存全部时提交）；词条数/上次同步展示
- 字段级搜索：search_field 下拉（manual 固定字段 / api-db 动态列）+ 关键词
- manual：添加一行、行内编辑（术语/英文/别称 chips/定义/分类/同义词 chips）、删除标记/恢复、
  新增/已修改标记、保存全部（一次提交增改删 + 名称/描述）、分页
- api/db：只读动态列表格（数据来自 extras，表头用 column_aliases）、从数据源同步、修改字段（别名面板）

### 1.3 后端接口
- 术语集 CRUD + 数据源 test-api/test-db/db-tables/preview-sql
- `GET /{base_id}/terms`：分页 + keyword + search_field（动态列 extras ilike）
- `PUT /{base_id}/terms/batch`：items（新增/更新）+ deleted_ids 一次保存
- `POST /{base_id}/sync`：**清空现有术语后全量重导**
- `/terms` 术语库：列表（category/status/keyword）、分类、创建、批量导入、更新、审核
  （approve→active / reject→deprecated）、删除、导出 JSON
- 服务层：standardize_text、get_or_create_term、add_synonym（TermMapping）、search_terms、
  get_term_tree、merge_terms、import_terms、TermBaseValueLoader（分组+缓存+取值）

### 1.4 前端有封装但无 UI/后端缺失（挂空，不实现）
- importTermBaseJson（/import-json）、importTermBaseFromSource（/import-from-source）：前端封装存在，后端无端点

## 2. 当前项目已具备（与目标一致或已增强）

- 术语集 CRUD、卡片列表、三源创建向导、创建后自动全量同步、编辑信息、删除确认
- 词条筛选（关键词/分类/状态）、新建/编辑表单、CSV/JSON 批量导入、审核（通过/驳回）、CSV 导出、分页、移动端
- api/db 动态列展示、字段配置（显示名 + 术语名称列指定）
- term_base_loader（分组+缓存+active 过滤）

## 3. 差距清单（需补齐/对齐）

| # | 功能 | 原项目行为 | 当前项目 | 优先级 |
|---|------|-----------|----------|--------|
| G1 | API 参数面板 | 路径/Query/Header 参数增删+启用、POST body、timeout | 仅 headers 文本 + GET/POST + json_path | P0 |
| G2 | manual 行内批量编辑 | 添加行/行内编辑/chips/删除标记/保存全部（batch save） | 单条表单 + 批量导入 | P0 |
| G3 | 批量保存端点 | `PUT /{base_id}/terms/batch`（items+deleted_ids） | 无（仅批量导入） | P0 |
| G4 | 字段级搜索 | search_field（manual 固定字段/api-db 动态列） | 无 | P0 |
| G5 | api/db 只读模式 | 只读动态列+同步+字段配置，无增删改 | 可编辑/审核/删除 | P0（需确认） |
| G6 | 同步语义 | 清空后全量重导 | 幂等 upsert（源端删除不清理） | P0（需确认） |
| G7 | 服务层能力 | standardize_text/merge_terms/TermMapping/search_terms/get_term_tree | 已裁剪（C6 仅 loader） | 抽取阶段 |
| G8 | 状态命名 | reject→deprecated | reject→rejected | 保留 rejected（语义等价） |
| G9 | 审核/导出/批量导入 UI | 后端有接口、前端无 UI | 当前已实现 UI（增强） | 保留 |

## 4. 分阶段实施计划（每阶段铁律验证）

### 阶段 A：管理与编辑对齐 —— ✅ 已完成（2026-08-12，含“不要增强、全部复刻”收尾）

> 用户追加要求：**不要增强，全部复刻**。已移除当前项目独有的 UI 增强：
> 审核（通过/驳回）、CSV 导出、CSV/JSON 批量导入、编辑信息弹窗、分类/状态筛选、
> 字段配置“术语名称列”单选；保留原项目交互：单弹窗创建向导、创建后进入编辑器、
> 卡片 hover 查看/同步/删除、同步/删除 confirm、术语集信息卡片、行内表格批量编辑、
> 定义列/编号列/搜索按钮、api/db 只读动态列 + 修改字段（右侧滑出面板）。
> 后端能力（batch save、search_field、清空重导、api/db 只读校验、审核/导出接口）保留，
> 前端不再暴露审核/导出/批量导入 UI。
1. G1 API 参数面板（path/query/header 增删+enabled、POST body、timeout）——后端已支持，补前端向导；
2. G3 后端 `PUT /{base_id}/terms/batch`（新增/更新/删除一次提交，≤5000）；
3. G2 manual 编辑器改为行内表格批量编辑（添加行/行内输入/chips/删除标记恢复/保存全部），
   保留批量导入/审核/导出为增强；
4. G4 字段级搜索（后端 list 支持 search_field，前端搜索下拉）；
5. G5 api/db 编辑器只读动态列（隐藏新建/编辑/删除/批量导入，保留同步+字段配置）；
6. G6 同步改为“全量对齐”（同步后源中已不存在的词条删除），对齐原项目；
7. 同步/删除 confirm（同步提示覆盖/清理语义）。

### 阶段 B：服务层能力（抽取联动阶段，待确认）
- standardize_text、术语合并、TermMapping 同义词映射、search_terms、get_term_tree；
- 建议在抽取模块建设时一并实现，本期不重复建设（C6 已登记 loader 接口）。

## 5. 待确认决策点

1. G5：api/db 词条是否严格按原项目**只读**（隐藏新建/编辑/审核/删除/批量导入）？推荐：是（对齐原项目），
   审核/批量导入等增强保留在 manual 术语集。
2. G6：同步是否改为**清空重导**（源端删除词条会被清理，但会丢弃该术语集下手工补充/审核状态）？推荐：是（对齐原项目）。
3. G7：服务层能力（standardize_text/合并/TermMapping）是否本期实现？推荐：抽取联动阶段实现（原项目也无 UI/端点）。
4. 原项目挂空功能（import-json / import-from-source）确认不实现（后端不存在）。

## 6. 验收（每阶段铁律）

- 后端五层全量回归 + ruff；
- S4/S5 E2E 按新功能扩展（向导参数、行内编辑、batch save、字段搜索、api/db 只读、同步清理）；
- type-check + build；入口闭环（列表→创建→内页→返回）继续强制。
