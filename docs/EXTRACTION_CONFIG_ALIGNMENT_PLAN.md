# 抽取配置四项前端全量对齐方案（除颜色风格外逐项一致）

> 依据：`docs/EXTRACTION_CONFIG_DIFF_REVIEW.md`（P0/P1/P2 差异清单）
> 目标：Schema / Prompt / 规则 / 脚本 四个前端与原项目在交互、页面结构、功能、展现形式上逐项一致，
> 仅颜色风格按当前浅绿白主题。
> 状态：**已执行完成（2026-08-12）**，含 014 迁移适配、四项前端对齐、E2E 与后端全量回归，已提交推送。
> 验收报告：[../qa/results/INDEX_S9_EXTRACTION_TEST_REPORT.md](../qa/results/INDEX_S9_EXTRACTION_TEST_REPORT.md)

## 0. 当前状态与总原则

- 已完成（待继续）：`014_rule_item_script_binding` 迁移已应用两库；`RuleGroupItem` 模型已改为
  `script_id + stage + category_name`（删除 script_name 列）。
- 总原则：
  1. 后端能力先行（规则项脚本绑定、脚本 IO 注册扩展），前端再逐模块对齐；
  2. 前端交互/布局/文案按原项目复刻，组件尽量复用当前 UI 库；
  3. 每模块完成后跑对应 E2E，全部完成后全量回归（M34 + 术语集），再提交推送；
  4. 全局配置、版本管理维持记录项（不动）。

## 1. 后端先行（Step A）

### A1 规则项脚本绑定（014 已落库，需完成服务/端点适配）
- `app/services/extraction_config_service.py`：
  - `get_rule_group`：解析 `script_id → script_name/script_description`（脚本表），规则项返回
    `{id, category_id, category_name, script_id, script_name, script_description, stage, sort_order}`；
  - `save_rule_group_items`：接收 `{category_id, category_name?, items:[{script_id, stage, sort_order}]}`，
    校验 script_id 属于当前 KB（不存在 400），按类别全量替换，保留 params（默认 {}）；
- `app/schemas/extraction.py`：`RuleGroupItemSave` 改为 `{script_id, stage='post', category_name?, sort_order}`（移除 script_name）；
- `app/api/v1/endpoints/kb_extraction_config.py`：无路径变化；
- 测试：更新 `integration/test_extraction_s2_api.py::test_rule_group_flow`（先建脚本，规则项带 script_id/stage，
  断言 script_name/stage 解析）；`boundary` 增加“脚本不存在 400”；S1 模型字段断言更新。

### A2 脚本 IO 注册扩展（供前端右栏复刻）
- `SCRIPT_IO_REGISTRY`：input/output 保持；tools 从字符串列表改为
  `[{name, desc, params:[{name,type,desc}], returns, usage}]`：
  - `get_term_records`、`embed`、`semantic_search`、`match_record` 各带说明与用法示例；
- `script_io_registry()` 返回结构不变（folders），tools 内容升级；
- 测试：`unit/test_extraction_s2_unit.py::test_script_io_registry` 断言 tools 为对象且含 desc/usage。

## 2. Schema 模板页（Step B）

### B1 模板列表
- 空态：EmptyState 风格（图标 LayoutTemplate + “暂无模板” + “创建 Schema 模板以定义抽取结构”）；
- 列表项：名称 + 停用 Badge；选中高亮；**移除“N 个类别”副文本**（原项目无）；
- 新建模板 Dialog：**去掉启用开关**（原项目无）；创建成功后**自动选中新模板**（原项目 selectTemplate(id)）；
- **移除“编辑模板”按钮**（原项目无模板编辑入口）；删除模板 confirm 文案保持。

### B2 模板详情 / 类别行
- 详情标题=模板名 + 描述；操作区：**新建类别** + 删除模板（图标）；
- 类别行徽章：`return_type`、`extraction_strategy`、`使用术语库`、`Query术语集(N)`、`top_k=N`、`停用` + 描述一行；
- 行内操作：添加字段 / 编辑 / 删除（图标按钮）；
- 类别图标块（FolderTree 风格容器）；
- 空态：EmptyState“暂无类别/暂无字段”+ 描述。

### B3 字段行
- 字段行：FileBox 图标块 + 名称 + 类型 Badge + 必填 Badge + **描述一行**；编辑/删除图标。

### B4 类别弹窗（对齐原项目）
- 校验：manual 名必填；term_base 必选术语集与取值字段；Query 术语集逐项校验
  （label/术语集/值字段必填）；
- Query 术语集条目：**添加后展开编辑，独立“保存”按钮**（saveQuerySource：
  保存时 label 自动替换为术语集名并收起条目）；支持折叠/移除；
- 其余字段（返回类型/策略/固定 Query/类别级覆盖/启用）已一致，保持。

## 3. Prompt 模板页（Step C）

### C1 列表
- **卡片网格**（sm:grid-cols-2）：名称 + 模式徽章（**Schema/简单**）+ 描述 + **提示词内容预览**
  （system||user 前 3 行，代码风格块）；操作：编辑（跳编辑页）/删除；
- 新建 Dialog：**schema 模式选择模板后默认全选类别**；保存前校验“至少选择一个类别”；
- **创建成功后自动跳转编辑页**。

### C2 编辑器（KbPromptEditorPage 重构）
- 顶部信息卡：模式 Badge（Schema 模式/简单模式）+ 启用状态 Badge + Switch；
- System Card：标题“System 系统提示词” + 说明“System 不使用 ${...} 占位符”；
- 占位符：**全部插入 user 提示词**（simple 或当前类别），插入到**光标处**并恢复焦点/选区；
- simple 模式：左 user textarea（id=user-prompt-simple）+ 占位符说明 + “测试组装”按钮；右 TestPanel；
- schema 模式**四栏**：类别列表 / 可用参数 / 当前类别 user 提示词 / TestPanel；
- 可用参数分三组：系统参数（feature/feature_descript/schema/context/return_type/prev_brands）、
  字段（${字段名}）、**术语集/Query 引用**（${label}、${label.分组字段}、${label.值字段}）；
- 渲染（runTest → TestPanel）：
  - `${feature}`→当前类别名（term_base 取名称来源字段第一个值）；`${feature_descript}`→描述；
    `${schema}`→组装 Schema JSON（return_type+properties：type/required/description/example）；
    `${return_type}`；`${context}`/`${prev_brands}` 保留占位符；
  - `${字段名}`→字段名；`${字段.类型/必填/描述/示例/枚举/术语集}`→属性值；
  - `${术语集名.字段}`→**分页加载术语集词条（100/页）缓存**，按 group_field/分组值过滤后
    替换为 `[值1, 值2]`；manual 字段映射（term_name/standard_name/english_term/definition/category/synonyms/aliases/standard_number）；
- 保存：simple 传 system+user；schema 传 system+categories（category_id+user_prompt）；**保存后停留编辑页**；
- 返回按钮文案“返回”，返回 `?tab=prompt`；
- 新增 `frontend/src/components/kb/TestPanel.tsx`（标题“测试效果”，空态提示“点击测试组装按钮预览”，
  显示当前类别 Badge + System/User 两个代码块）。

## 4. 后处理与校验规则页（Step D）

### D1 交互形态
- 改为**展开式卡片列表**：规则组卡片（顶部渐变条 + 图标 + 名称 + “N 类别”“N 规则”Badge +
  Schema 模板名 + 描述 + 展开箭头 + 删除），点击组展开/收起；
- 展开后**懒加载详情**（首次展开请求详情），组内展示类别树；
- 类别行：名称 + “N 规则”Badge + 摘要（后处理 N · 校验 M）+ 添加规则按钮；点击整行展开/收起；
- 移除“左列表+右侧详情”双栏形态。

### D2 规则项
- 显示：脚本名 + **阶段徽章（后处理/校验）** + 脚本描述；
- 排序：**拖拽排序（HTML5 DnD）+ 上移/下移按钮**，操作后自动持久化该类别；
- 移除：confirm 后从列表移除并自动持久化；
- 添加规则弹窗：先选阶段（后处理/校验）→ 脚本下拉只显示该目录**已启用**脚本 → 添加；
  无脚本时提示“该阶段暂无启用脚本，请先在「脚本管理」中创建”。

### D3 新建规则组
- 弹窗顺序：名称 → Schema 模板 → 描述；**默认选中第一个模板**；
- 文案：“规则组名称（可不填，默认取 Schema 模板名）”。

## 5. 脚本管理页（Step E）

### E1 整体布局
- 顶部说明栏：两行说明（“编写可复用的 Python 处理脚本，按调用时机组织目录，支持在线调试。” +
  “脚本需定义 def run(args): ...，返回 dict。”）+ **保存脚本按钮**；
- 左栏目录**可折叠**（点击展开/收起 + 箭头 + 数量 Badge），脚本列表项带“停”标记（enabled=false），
  目录内“新建脚本”按钮；
- 中栏：顶部名称输入 + 启用 Switch + “启用/关闭”文本 + 未保存标记 + 删除按钮；
  下方目录/说明信息行；**代码编辑器带行号栏 + “Python · N 行”角标**；
- 右栏**四面板**：可传入参数 / 返回参数 / kb_tool 可用工具（含 desc/params/returns/usage 折叠说明）/
  **可用术语集**（get_term_records 用法示例，点击折叠）；
- 底部调试：**左右两栏**（请求参数 JSON / 返回结果），按钮“运行调试”，
  结果以 `JSON.stringify({ok,result}|{ok:false,error})` 结构化展示；
- 新建脚本后 dirty=true（未保存标记）。

### E2 IO 注册
- 依赖 A2 的 tools 对象结构；术语集面板直接列当前 KB 术语集（已有 termBases 数据源，前端拉取）。

## 6. E2E 与回归

- 更新：`e2e_extraction_schema.mjs`（S3：空态描述/自动选中/徽章/Query 保存）；
  `e2e_extraction_prompt.mjs`（S4：创建后跳转/默认全选/四栏/术语集渲染/保存停留）；
  `e2e_extraction_rules.mjs`（S5：展开式/阶段/脚本绑定/添加弹窗/排序/自动持久化）；
  `e2e_extraction_scripts.mjs`（S6：行号/目录折叠/四面板/调试布局/运行调试文案）；
  `e2e_extraction_full_flow.mjs`（S7：联动按新交互调整）；
- 后端：M34 全量回归（含 014 适配）、术语集回归 110+；
- 质量门禁：type-check/build/ruff（改动文件）、控制台无错误、覆盖率统计表更新。

## 7. 风险与影响

- 规则项模型变更（script_name→script_id）会丢弃既有 script_name 数据（当前仅测试数据，无真实数据）；
- Prompt 编辑器重构较大（四栏 + 渲染引擎），需保留现有 E2E 关键断言并补充；
- 脚本编辑器行号实现为行号栏 + textarea 同步滚动（简单方案，不做富编辑器）。

## 8. 待确认

1. 确认按本方案执行（含已落库的 014 继续适配）；
2. 若不想改动规则项模型，可回退 014 并维持 script_name 自由填写（与原项目不一致，仅此点例外）；
3. 模板“编辑模板”与新建模板“启用开关”为当前增强，按“一致”原则移除，确认；
4. 其余按方案默认执行。


## 9. 执行记录（2026-08-12）

- Step A 后端：014 迁移、RuleGroupItem 模型/Schema/服务适配、IO 工具对象目录完成；
- Step B Schema 页：模板列表/详情/类别/字段/Query 术语集按原项目对齐；
- Step C Prompt 页：列表卡片网格 + 四栏编辑器 + 测试组装；
- Step D 规则页：展开式卡片 + 懒加载 + 拖拽排序 + 添加规则弹窗（阶段→启用脚本）；
- Step E 脚本页：目录折叠 + 行号 + 四面板 + 双栏调试；
- 回归：M34 36/36 + M33 75/75；E2E 38/38 + 术语集 26/26；type-check/build/ruff 通过；
- 附带修复：测试库链头断言随 014 更新、整体验收清单随 V3 定版更新、sync_executor 对 claimed outbox 补标 done。
