# PROVENANCE

记录从 `legacy/` 复制并重写到 `new_app/` 的代码来源。

| 新文件 | 旧来源（legacy 路径） | 复用类型 | 改动摘要 | 验证 |
|---|---|---|---|---|
| `services/ocr/algorithms/normalize.py` | `metal-doc-agent/metal_doc_agent/tablegrid/normalize.py` | 复制后重写 | 只保留表格结构所需工具（`clean_text`/`parse_unit`/`is_numeric_like`/`looks_like_grade`/`is_footnote_row`/`canonical_element`），移除值归一化与属性绑定 | `tests/algorithm/table` |
| `services/ocr/algorithms/table_grid.py` | `metal-doc-agent/metal_doc_agent/tablegrid/parser.py` | 复制后重写 | 改用新 pydantic 契约，去掉 pipeline/settings 依赖；保留 rowspan/colspan 展开、表头路径、跨页合并与块拆分 | `tests/algorithm/table` |
| `services/ocr/algorithms/profile.py` | `metal-doc-agent/metal_doc_agent/tablegrid/profile.py` | 复制后重写 | 改用新契约；保留表型特征与 `grade_rows`/`element_rows` 判定 | `tests/algorithm/table` |
| `services/ocr/algorithms/repairs.py` | `metal-doc-agent/metal_doc_agent/tablegrid/repairs.py` | 参考重写 | 按 M2 文档的 `match`/`action` 规则格式重写；保留 `patch_cells`/`replace_rows`/`delete_rows`/`rebuild_grid` 等确定性动作 | `tests/algorithm/table` |
| `services/shared/storage.py` | `new_app/services/orchestration/storage.py`（M1 自研） | 迁移 | 参数化 `StorageConfig`，供 orchestration 与 ocr 共用 | `tests/test_storage.py` |
| `services/shared/text.py` | `metal-doc-agent/metal_doc_agent/tablegrid/normalize.py::clean_text` | 迁移 | 提取为共享文本归一化，供 OCR 与配方匹配共用 | `tests/algorithm/table`、`tests/contract/recipes` |
| `services/recipe_registry/package.py` | `metal-doc-agent/metal_doc_agent/contracts.py`（`Recipe`/`RecipeSignature`） | 参考重写 | 改为 recipe-package 2.0 manifest，增加 semver、engine_api、digest 与不可变校验 | `tests/contract/recipes/test_package.py` |
| `services/recipe_registry/matcher.py` | `metal-doc-agent/metal_doc_agent/recipes/signature.py` | 复制后重写 | 使用新 `TableGrid` 契约与共享 `clean_text`，打分与阈值保持一致 | `tests/contract/recipes/test_matcher.py`、`scripts/benchmark/route_parity.py` |
| `services/recipe_registry/registry.py` | `metal-doc-agent/metal_doc_agent/recipes/router.py`、`lifecycle.py` | 参考重写 | 用 `stable/candidate/shadow/deprecated` 通道指针替代 L0–L5，增加版本不可变与 history | `tests/contract/recipes/test_registry.py` |

> legacy 来源为 2026-11-11 清理前归档版本；归档后的 `legacy/` 只读，不再更新。

## 规则

1. 旧代码只读参考，不允许直接 `import`。
2. 复制后必须去掉旧依赖（pipeline/jobs/settings），改为新接口。
3. 每个复制文件必须有来源头注释。
4. 必须补单元测试与基准测试。
5. 未记录来源的代码不得合入。
