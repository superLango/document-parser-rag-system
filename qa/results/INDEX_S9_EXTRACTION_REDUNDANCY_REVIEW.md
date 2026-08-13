# 抽取配置六项对齐修改 · 冗余/无效代码审查报告

- 日期：2026-08-13
- 审查范围：提交 `33b3ca4` 涉及的六个对齐修改及其相关文件
  - `frontend/src/views/kb/KbExtractionConfigPage.tsx`
  - `frontend/src/views/kb/KbPromptEditorPage.tsx`
  - `frontend/src/views/kb/KbScriptManager.tsx`
  - `frontend/src/api/modules/extractionConfig.ts`
  - `backend/app/services/extraction_config_service.py`
  - `backend/app/api/v1/endpoints/kb_extraction_config.py`
  - 配套测试与 E2E
- 方法：全仓库 `rg` 引用扫描 + 逐文件核对（旧状态变量、旧 testid、旧 API 方法、写死未读字段），并辅以 type-check/ruff 结果。

## 结论

六个对齐修改本身**没有引入新的冗余逻辑或无效引用**；发现的残留均为更早版本遗留的“死 API 方法/写死字段”，建议清理但不影响功能：

1. 前端 `extractionConfigApi.updateSchemaTemplate` —— **零调用方**
   - 位置：`frontend/src/api/modules/extractionConfig.ts:66`
   - 来源：移除“编辑模板”入口后遗留（前端已无任何页面调用 `updateSchemaTemplate`）。
2. 前端 `promptApi.update` —— **零调用方**
   - 位置：`frontend/src/api/modules/extractionConfig.ts:124`
   - 来源：移除 Prompt 新建弹窗的“编辑”分支后遗留（当前编辑内容走 `promptApi.save`）。
3. 后端 Schema `RuleGroupItemSave.id` —— **零读取**
   - 位置：`backend/app/schemas/extraction.py`（`RuleGroupItemSave.id: str | None = None`）
   - `save_rule_group_items` 不读取该字段，前端 `saveItems` 也不传 `id`（早期按 id upsert 方案残留）。
4. 写死但未读的数据列：`rule_group_items.params / enabled`
   - 保存时固定写入 `params={}`、`enabled=True`（`extraction_config_service.py:757-758`），全项目无任何读取；属 S2 早期设计残留，模型列仍保留。
5. 新增测试中未使用变量
   - `qa/integration/test_extraction_s2_api.py::test_rule_group_term_base_category_name` 中 `cat` 赋值后未使用（仅需要创建动作本身）。
6. 保留但当前无调用方的后端端点（建议保留）
   - `PUT /schema-templates/{template_id}`（`update_schema_template`）
   - `PUT /extraction-config/prompts/{prompt_id}`（`update_prompt`）
   - 仓库内前端与测试均未调用，但属于对外 API 契约（原项目也有），如确认无外部调用可另行评估移除。

## 已排除项

- 旧状态变量/弹窗残留：`ruleOpen / ruleItemOpen / promptEdit / openEditPrompt / tplEdit / openRuleItems` 等已全部清除，`rg` 无命中。
- 旧 testid：`btn-rule-items-save / rule-script-* / rule-params-* / btn-prompt-preview / prompt-preview-content` 均无残留。
- 旧字段引用：`query_mode / datasets / params_schema` 在前端与当前后端服务中无残留引用（仅原项目基线内存在）。
- 未使用导入：type-check 通过，三个修改页面无未使用 import。
- 六个修改本身的逻辑：自动选中、Query 关联汇总区（与原项目一致的“双区展示”）、置信度条件提交、只读交互、降级路径均为按需实现，无重复分支或无效代码。

## 建议处理

- 低风险清理：删除 `updateSchemaTemplate`、`promptApi.update` 两个死方法；删除 `RuleGroupItemSave.id`；修正测试未使用变量。
- 需决策：`rule_group_items.params/enabled` 若后续规则参数无计划，可另起迁移删除；若计划启用则保留并在详情返回。
- 保守保留：两个后端 update 端点作为 API 契约保留。

## 清理记录（2026-08-13）

已完成低风险清理：

1. 删除 `frontend/src/api/modules/extractionConfig.ts` 中 `updateSchemaTemplate`；
2. 删除同文件中 `promptApi.update`；
3. 删除 `backend/app/schemas/extraction.py` 中 `RuleGroupItemSave.id`；
4. 修正 `qa/integration/test_extraction_s2_api.py::test_rule_group_term_base_category_name` 未使用变量 `cat`。

验证：type-check、ruff 通过；M34+M33 全量回归 112/112 通过。
待决策项：`rule_group_items.params/enabled` 列是否清理（需迁移，未动）。

## 证据

- `rg -n "updateSchemaTemplate|promptApi\.update" frontend/src` → 仅 API 模块定义，无调用点。
- `rg -n "ruleOpen|ruleItemOpen|promptEdit|openEditPrompt|btn-prompt-preview|query_mode|datasets|params_schema" frontend/src backend/app qa --glob '!qa/results/*'` → 无命中。
- `npm run type-check` / `ruff check` → 通过。
