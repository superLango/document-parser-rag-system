# 专业术语集 P0 改造报告（创建后全量同步 + 动态列保留展示）

- 日期：2026-08-12
- 依据：`docs/TERMS_COMPARISON.md` §4 P0 清单

## 改造内容

### P0-1 创建后全量同步

- `frontend/src/views/kb/KbGlossaryPage.tsx`：
  - 创建 API/DB 术语集时不再提交预览子集（此前只导入前 5-10 条），只保存配置与列定义；
  - 创建成功后自动调用同步接口全量导入；成功 toast“数据同步完成，导入 N 条”，
    失败 toast“术语集已创建，数据同步失败（可卡片手动同步）”；
  - 未完成数据源测试/预览时禁止创建（按钮禁用 + 提示文案），对齐原项目约束；
  - 创建按钮文案：手动“创建术语集”、API/DB“创建并同步数据”。

### P0-2 api/db 动态列保留与展示

- `backend/app/services/glossary/term_base_service.py`：
  - 新增 `_map_source_row`：column_aliases 映射内置字段的同时，**所有原始字段保留进 extras**
    （datetime/Decimal/bytes 统一 JSONB 安全序列化）；未识别名称列时智能回退
    （name/term/value/名称/术语名称…，再回退第一列）；源 id 写入 extras.external_id；
  - `sync_term_base` 改用 `_map_source_row`，同步即保留全部动态列；
- `backend/app/services/glossary/source_db.py`：`_json_safe` 序列化数据库行值
  （None/datetime/date/time/Decimal/bytes），避免 JSONB 写入失败；
- `frontend/src/views/kb/KbGlossaryEditorPage.tsx`：
  - API/DB 术语集按 `columns + column_aliases` 渲染**动态列表格**（表头显示别名），
    移动端卡片展示前 3 个动态列；
  - 新增“字段配置”弹窗：修改列显示名称（column_aliases），原始字段名保持不变；
  - manual 术语集保持原固定列/表单能力不变；
- 前端创建时保存 `columns` 列定义（供动态列展示）。

## 验证

| 项目 | 结果 |
|------|------|
| 后端五层全量回归 | ✅ 69/69（新增单测 2、集成 1） |
| ruff | ✅ 通过 |
| S4 E2E（含自动全量同步、动态列可见、字段配置改名） | ✅ 13/13 |
| S5 E2E（manual 编辑器回归） | ✅ 16/16 |
| 前端 type-check + build | ✅ 通过 |

新增/更新测试：
- `qa/unit/test_glossary_s2_coverage.py`：_map_source_row（extras 保留/名称回退/别名映射/external_id/JSON 安全）、_json_safe；
- `qa/integration/test_glossary_api.py`：同步保留动态列 extras、名称回退、pending 状态、二次同步 upsert 更新 extras；
- `qa/functional/e2e_glossary.mjs`：本地源增加 spec 动态列，覆盖“创建→自动全量同步→进内页→动态列值→字段配置改名→返回”。

## 说明

- 同步语义保持幂等 upsert（不清空），源端新增/变更会同步，源端删除的词条当前不会自动清理（与 P0 无关，后续如需可增加“按 external_id 清理”开关）；
- api/db 词条仍可执行审核（外部同步默认 pending）；行内编辑仅作用于内置字段，动态列值在数据源维护。
