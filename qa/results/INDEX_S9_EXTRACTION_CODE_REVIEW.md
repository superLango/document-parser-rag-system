# 抽取配置四项功能 · 最终代码审查报告（当前实现 vs 原项目）

- 日期：2026-08-12
- 审查对象：
  - 当前：`frontend/src/views/kb/KbExtractionConfigPage.tsx`、`KbPromptEditorPage.tsx`、`KbRuleGroups.tsx`、`KbScriptManager.tsx`、`components/kb/TestPanel.tsx`
  - 当前后端：`backend/app/services/extraction_config_service.py`、`backend/app/api/v1/endpoints/kb_extraction_config.py`
  - 原项目：`document-parser-rag-system/frontend/src/views/Kb/ExtractionConfig.vue`、`PromptEditor.vue`、`ScriptManager.vue`、`TestPanel.vue`
  - 原项目后端：`document-parser-rag-system/backend/app/api/v1/endpoints/schema_templates.py`、`extraction_config.py`
- 审查方法：源码逐段比对（页面结构、交互、文案、权限、校验、数据模型、接口），非仅 UI 截图。
- 差异分级：P0=功能缺失/可用性缺陷；P1=交互或权限差异（建议处理）；P2=布局/文案/视觉差异（主题差异允许，其余可选）。

## 1. 总体结论

四个功能的**主干交互、页面结构、数据链路与原项目基本一致**（Schema 三层、Prompt 列表+独立编辑器、规则组展开式卡片、脚本左中右+调试），
且已通过 M34 36/36、M33 75/75、E2E 38/38 回归。

但对照源码仍发现 **6 处 P1 差异**和若干 P2 差异，主要集中在：

1. **只读角色的编辑器/脚本页未禁用**（当前前端未做角色只读，原项目做了）；
2. **脚本调试接口权限不一致**（原项目任意成员可运行，当前后端要求 editor）；
3. **规则组类别名未回退术语集名**（术语库来源且名称为空的类别在规则页显示为空）；
4. **Schema 页初始不自动选中第一个模板**（原项目进入即加载第一个模板详情）；
5. **类别弹窗缺少“Query 关联”汇总区**，且置信度阈值不再按抽取策略条件显示；
6. **Prompt 编辑器加载失败回退策略弱于原项目**（原项目回退到 prompt 返回的类别，当前直接置空）。

## 2. Schema 模板页差异

| # | 原项目 | 当前实现 | 级别 | 位置 |
|---|--------|----------|------|------|
| S1 | 进入页签自动选中第一个模板并加载详情 | 初始不选中，右侧显示“选择左侧模板查看类别与字段” | **P1** | 当前 `KbExtractionConfigPage.tsx` load() 未调用选中逻辑；原项目 `loadTemplates()` 自动 `selectTemplate(first)` |
| S2 | 列表项仅名称+停用 Badge，选中 `bg-primary/10` | 列表项增加描述行，选中为卡片边框高亮 | P2 | 当前 `KbExtractionConfigPage.tsx` 模板列表 |
| S3 | 左栏标题“模板”，新建为纯加号图标按钮 | 标题“Schema 模板”，按钮“新建模板”带文字 | P2 | 同上 |
| S4 | 详情标题“请选择模板” | 空态“选择左侧模板查看类别与字段” | P2 | 同上 |
| S5 | 类别展开区只显示字段 | 额外展示 Query 术语集标签（label+参与 Query） | P2（增强） | 当前 `KbExtractionConfigPage.tsx` 类别展开区 |
| S6 | 类别弹窗含“Query 关联（挂载到 Query 的术语集）”汇总区，仅列 in_query 条目 | 无该汇总区，in_query 只作为条目内开关 | **P1** | 原 `ExtractionConfig.vue` 类别对话框；当前类别弹窗 |
| S7 | 术语集空态标题“暂无术语集/添加术语集用于构造动态 Query” | 文案“暂无术语集，添加后用于构造动态 Query”，无图标空态 | P2 | 当前类别弹窗 |
| S8 | 置信度阈值仅在 `extraction_strategy === 'auto'` 时显示与提交 | 无条件始终显示并提交 | P1/P2 | 当前 `KbExtractionConfigPage.tsx` 类别弹窗；原 `ExtractionConfig.vue` v-if |
| S9 | 名称来源术语集标签含说明“（选择后按该字段值循环生成类别）” | 无该说明 | P2 | 当前类别弹窗 |
| S10 | 类别/字段弹窗均有 placeholder 提示 | 部分 placeholder 缺失（如描述、示例） | P2 | 当前弹窗 |

## 3. Prompt 模板差异

| # | 原项目 | 当前实现 | 级别 | 位置 |
|---|--------|----------|------|------|
| P1 | 空态为 EmptyState（图标+描述“创建 Prompt 模板以控制模型抽取行为”） | 仅文字“暂无 Prompt 模板” | P2 | 当前 `KbExtractionConfigPage.tsx` prompt 列表 |
| P2 | 新建按钮文案“新建模板” | “新建 Prompt” | P2 | 同上 |
| P3 | 新建弹窗模式选择标签“绑定 Schema 模板（可选）”，选项“不绑定（单个 user 提示词）/绑定 Schema（按类别拆分 user 提示词）” | 标签“模式”，选项“simple/schema” | P2 | 当前 Prompt 弹窗 |
| P4 | 类别选择区标题“选择类别（默认全选）” | 无标题 | P2 | 当前 Prompt 弹窗 |
| P5 | 编辑器只读角色禁用：System/User textarea disabled、占位符按钮 disabled、保存按钮仅 editor 可见 | 编辑器页面无任何角色判断，viewer 可编辑并点击保存（后端会拒绝，但交互错误） | **P1** | 当前 `KbPromptEditorPage.tsx` 全文；原 `PromptEditor.vue` 使用 isEditor |
| P6 | System/User textarea 有 placeholder（“输入系统提示词”“输入 user 提示词”“输入该类别的 user 提示词”） | 无 placeholder | P2 | 当前 `KbPromptEditorPage.tsx` |
| P7 | 可用参数栏 max-h-[480px] | max-h-[520px] | P2 | 同上 |
| P8 | 模板加载失败时回退到 prompt 返回的类别（保留名称与 user_prompt，无字段） | 失败直接 setCategories([])，类别列表丢失 | **P1** | 当前 `KbPromptEditorPage.tsx` load()；原 `PromptEditor.vue` load() |
| P9 | 加载态为居中 spinner | Skeleton 占位 | P2（样式允许） | 同上 |

## 4. 后处理与校验规则差异

| # | 原项目 | 当前实现 | 级别 | 位置 |
|---|--------|----------|------|------|
| R1 | 规则组详情类别名：名称为空且 name_source=term_base 时回退术语集名称 | 直接返回 `c.name or ""`，术语库类别显示为空名 | **P1** | 当前 `extraction_config_service.py::get_rule_group`；原 `extraction_config.py::get_rule_group` |
| R2 | 规则行：上移/下移按钮对所有成员可见，仅移除按钮限 editor | 非管理成员隐藏全部操作按钮 | P2 | 当前 `KbRuleGroups.tsx` 规则行 |
| R3 | 空类别提示图标为 FileBox | FolderTree | P2 | 当前 `KbRuleGroups.tsx` |
| R4 | 规则行拖拽底色 `bg-white/60 dark:bg-muted/40` | `bg-card` | P2（样式允许） | 同上 |
| R5 | 新建规则组/添加规则弹窗字段与校验一致 | 一致 | - | - |

## 5. 脚本管理差异

| # | 原项目 | 当前实现 | 级别 | 位置 |
|---|--------|----------|------|------|
| M1 | viewer 只读：脚本名 disabled、说明显示纯文本、代码 textarea readonly、启用 Switch 仅 editor | 当前仅隐藏按钮/开关，名称、说明、代码仍可编辑（保存会被后端拒绝） | **P1** | 当前 `KbScriptManager.tsx` 中栏；原 `ScriptManager.vue` |
| M2 | 脚本调试任意成员可执行（后端无 editor 限制，调试参数 textarea 在选中脚本时也可编辑） | 后端 `run_script` 要求 editor，viewer 点击运行会 403；前端仍显示运行按钮 | **P1** | 当前 `kb_extraction_config.py::run_script`；原 `extraction_config.py::run_script_endpoint` |
| M3 | 删除脚本后编辑器重置为空代码 | 重置为默认模板代码 | P2 | 当前 `KbScriptManager.tsx::confirmDelete` |
| M4 | 行号栏与代码区不同步滚动 | 增加滚动同步 | P2（增强） | 当前 `KbScriptManager.tsx` |
| M5 | 顶部说明、目录折叠、“停”标记、右栏四面板、调试双栏 | 一致 | - | - |

## 6. 后端接口/数据模型差异

| # | 原项目 | 当前实现 | 级别 | 位置 |
|---|--------|----------|------|------|
| B1 | Schema 类别模型含 `query_mode`、`datasets`（UI 未直接暴露） | 当前 `SchemaCategory` 无这两列；请求 Schema 也无该字段 | P2（记录项） | 原 `schema_templates.py` vs 当前 `models/extraction.py` |
| B2 | 脚本模型含 `params_schema`、`sort_order` | 当前 `KbScript` 无 `params_schema`/`sort_order`，列表不返回 | P2（记录项） | 原 `extraction_config.py::list_scripts` vs 当前 `models/extraction.py` |
| B3 | schema 模式保存 Prompt：仅更新已存在的类别记录 | 当前先删后插全量重建（模板类别固定时结果等价） | P2 | `save_prompt_content` |
| B4 | 规则项保存前先 flush 删除再插入（避免唯一约束冲突） | 当前直接执行 delete 后 add（SQLAlchemy 同会话提交，行为已验证通过） | - | `save_rule_group_items` |
| B5 | 脚本运行注入 `KbScriptTools`，任意成员可执行 | 当前要求 editor，且注入 `_load_term_data` 只读数据 | P1 | 见 M2 |
| B6 | 端点前缀 `/kbs/{kb_id}/...` | 当前 `/kb/{kb_id}/...`（项目统一路由，非本功能差异） | - | - |

## 7. 页面闭环与权限核查

- 入口闭环：Schema/Prompt/规则/脚本均通过 KB 内部“抽取配置”菜单进入；Prompt 创建后跳独立编辑页、返回列表状态一致；E2E S3-S7 38/38 覆盖闭环。
- 权限核查：列表页写操作按钮按 `canManage` 隐藏（viewer 只读）；**但编辑器页与脚本中栏存在 viewer 可编辑的 UI 缺口（P5/M1）**，后端仍正确拒绝。
- 确认弹框：均使用自建 Dialog（非浏览器 confirm），与原项目一致。

## 8. 未迁移能力（记录项，用户已确认暂不实现）

1. 全局配置（retrieval/llm/kb_tool）——原项目首个页签；
2. 版本管理（快照/详情/对比/回滚）；
3. 原项目 `/rules`、`/validation`、`/bindings` 规则注册表/校验/绑定接口与页面（已由“规则组+脚本”替代）；
4. 脚本 `params_schema` 动态参数表单（原项目后端存在，前端未暴露）。

## 9. 处置建议（按优先级）

1. **Prompt 编辑器与脚本页补齐只读角色交互**：`KbPromptEditorPage.tsx` 增加 `canManage`（或 auth store 判断），禁用输入与保存；`KbScriptManager.tsx` 中栏名称/说明/代码按 `canManage` 只读化。
2. **脚本调试权限对齐原项目**：`kb_extraction_config.py::run_script` 去掉 `_require_editor`（保留 KB 成员+RLS），或前端隐藏 viewer 的运行按钮（两者取其一，推荐对齐原项目“任意成员可试运行”）。
3. **规则组类别名回退术语集名**：`extraction_config_service.py::get_rule_group` 按原项目逻辑批量解析 `name_term_base_id` 回退显示名。
4. **Schema 页初始自动选中第一个模板**：`load()` 后若 `templates.length > 0 && !selectedId` 自动 `setSelectedId(templates[0].id)`。
5. **类别弹窗对齐**：增加“Query 关联”汇总区；置信度阈值加 `extraction_strategy === 'auto'` 条件；术语库名称来源补充说明文案。
6. **Prompt 编辑器加载回退**：模板详情加载失败时使用 prompt 返回的 categories（含 category_name/user_prompt）降级。
7. 其余 P2 文案/图标差异按需补齐；主题色与组件视觉差异按约定保留。

## 10. 证据文件

- 当前前端：[KbExtractionConfigPage.tsx](/home/grainuser/hansonDoc_RAG/frontend/src/views/kb/KbExtractionConfigPage.tsx)、[KbPromptEditorPage.tsx](/home/grainuser/hansonDoc_RAG/frontend/src/views/kb/KbPromptEditorPage.tsx)、[KbRuleGroups.tsx](/home/grainuser/hansonDoc_RAG/frontend/src/views/kb/KbRuleGroups.tsx)、[KbScriptManager.tsx](/home/grainuser/hansonDoc_RAG/frontend/src/views/kb/KbScriptManager.tsx)
- 当前后端：[extraction_config_service.py](/home/grainuser/hansonDoc_RAG/backend/app/services/extraction_config_service.py)、[kb_extraction_config.py](/home/grainuser/hansonDoc_RAG/backend/app/api/v1/endpoints/kb_extraction_config.py)
- 原项目前端：[ExtractionConfig.vue](/home/grainuser/hansonDoc_RAG/document-parser-rag-system/frontend/src/views/Kb/ExtractionConfig.vue)、[PromptEditor.vue](/home/grainuser/hansonDoc_RAG/document-parser-rag-system/frontend/src/views/Kb/PromptEditor.vue)、[ScriptManager.vue](/home/grainuser/hansonDoc_RAG/document-parser-rag-system/frontend/src/views/Kb/ScriptManager.vue)
- 原项目后端：[schema_templates.py](/home/grainuser/hansonDoc_RAG/document-parser-rag-system/backend/app/api/v1/endpoints/schema_templates.py)、[extraction_config.py](/home/grainuser/hansonDoc_RAG/document-parser-rag-system/backend/app/api/v1/endpoints/extraction_config.py)


## 11. 修改记录（2026-08-12）与第六项详细说明

### 前五项已按原项目对齐

| # | 差异 | 修复方式 | 涉及文件 |
|---|------|----------|----------|
| 1 | Prompt 编辑器 / 脚本页 viewer 只读 | 编辑器增加 `canManage`：System/User textarea、类别 user 提示词、占位符按钮、启用 Switch 禁用，保存按钮仅管理角色可见；脚本页名称输入禁用、说明改为文本展示、代码 readOnly、调试参数按原项目规则只读 | `KbPromptEditorPage.tsx`、`KbScriptManager.tsx` |
| 2 | 脚本调试权限 | 后端 `run_script` 移除 `_require_editor`，KB 任意成员可试运行（保留 RLS 与审计）；安全测试由“403 拒绝”改为“viewer 可运行” | `kb_extraction_config.py`、`test_extraction_s2_security.py` |
| 3 | 规则组术语库类别名 | `get_rule_group` 批量解析空名 term_base 类别并回退术语集名；新增集成测试 | `extraction_config_service.py`、`test_extraction_s2_api.py` |
| 4 | Schema 页自动选中 | `load()` 后自动选中第一个模板（`setSelectedId(prev => prev ?? items[0]?.id)`），删除选中模板后回落到第一个 | `KbExtractionConfigPage.tsx` |
| 5 | 类别弹窗 | 新增“Query 关联（挂载到 Query 的术语集）”汇总区（含主查询/精简上限、精简开关、取消关联）；置信度阈值仅在 `extraction_strategy === 'auto'` 时显示并提交 | `KbExtractionConfigPage.tsx` |
| 6 | Prompt 编辑器模板加载失败降级 | 后端 `_serialize_prompt`/`get_prompt` 的 categories 补 `category_name`（列表/详情/保存均批量解析）；前端 catch 分支降级使用 prompt 返回类别（无字段），保留类别名与已保存 user_prompt；新增集成断言与 E2E 降级场景 | `extraction_config_service.py`、`extractionConfig.ts`、`KbPromptEditorPage.tsx`、`test_extraction_s2_api.py`、`e2e_extraction_prompt.mjs` |

回归结果：M34+M33 后端 112/112；E2E Schema 9/9、Prompt 9/9（新增降级场景）、规则 7/7、脚本 8/8、联动 6/6，合计 39/39；type-check/build/ruff 通过。

### 第六项详细说明：Prompt 编辑器模板加载失败的降级差异

**现象**：schema 模式的 Prompt 编辑器在加载 Schema 模板详情失败时，原项目会降级为“可继续编辑已保存的类别提示词”，当前实现会直接显示“暂无类别”，整个编辑器不可用。

**为什么会有这条路径**：schema 模式编辑器依赖两个接口：
1. `GET /extraction-config/prompts/{id}` —— 返回 Prompt 基本信息与已保存的各类别 `user_prompt`；
2. `GET /schema-templates/{id}` —— 返回类别的字段、名称来源、Query 术语集等结构信息。

编辑器真正需要的“每个类别一段 user 提示词”来自接口 1，接口 2 只是提供字段列表和术语集参数供占位符插入。

**原项目的处理**（`PromptEditor.vue` `load()`）：
```
try { tpl = await kbApi.getSchemaTemplate(...) } catch {
  // 模板加载失败，回退到 prompt 返回的类别（无字段）
  categories = cats.map(c => ({ id, name, user_prompt, fields: [] }))
}
```
即：模板详情请求失败时，用 prompt 接口返回的 `categories`（原项目后端通过 join SchemaConfig 返回了 `category_id/category_name/user_prompt`）构造类别列表。效果是：
- 类别列表仍可见、可切换；
- 每类别的 user 提示词仍可查看和编辑；
- 只是字段/术语集占位符面板不可用；
- 保存时后端仍能按 category_id 写入，数据不会丢。

**当前实现的处理**（`KbPromptEditorPage.tsx` `load()`）：
```
try { tpl = await extractionConfigApi.getSchemaTemplate(...) } catch { setCategories([]) }
```
失败后类别列表被清空，编辑器显示“该 Schema 模板下没有选中类别”，连已保存的类别 user_prompt 也无法查看或编辑。

**为什么当前版本即使想降级也降不了**：当前后端 `_serialize_prompt` 返回的 categories 只有 `{ category_id, user_prompt }`，没有 `category_name`（原项目 `_load_prompt_categories` 会 join SchemaConfig 返回名称）。所以前端即使仿照原项目写降级逻辑，也拿不到类别显示名。要真正对齐，需要两处配合：
1. 后端 `_serialize_prompt` / `get_prompt` 的 categories 增加 `category_name`（对齐原项目接口契约）；
2. 前端 `load()` 的 catch 分支改为使用 `p.categories` 构造 `EditorCategory`（`fields: []`）。

**触发场景与影响面**：
- 模板详情接口超时或 500（服务异常）；
- 绑定模板被删除后（`schema_template_id` 置空但 PromptContent 仍在），编辑器打开即失败；
- 属于容错/可用性差异，不影响正常主流程，但会让“模板异常时 Prompt 内容不可读不可改”。

**已修改（2026-08-12）**：按上面两条实施——后端 `_serialize_prompt`/`get_prompt`/列表/保存均返回 `category_name`；前端 `load()` catch 分支用 `p.categories` 构造 `EditorCategory(fields: [])` 降级。E2E 以“拦截模板详情请求”场景验证降级后类别名与已保存提示词仍可见可编辑。
