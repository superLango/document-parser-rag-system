# 黄金集 A/B 标注复核包（WS1）

- 日期：2026-10-26
- 依据：`../../../../metal-standard-agent-plan/stages/01a-M1-验收后优化计划.md` WS1
- 当前状态：A/B 包已生成；**B 份为空模板，等待标注员独立填写**；人工仲裁完成前保留 `owner-override` 标记，不宣称人工 A/B 已完成。

## 1. 目录

| 路径 | 内容 |
|---|---|
| `a/` | A 标注：当前 `goldset/v0/docs` 的 verified 版本，作为对照基线 |
| `b/` | B 标注：已清空记录/检验项/分类项/条款的独立标注模板 |
| `reports/` | `tools/gold_review_batch.py` 生成的逐文档 diff 与汇总 |
| `dryrun/` | AI 独立复核 dry-run：B 草案、A 审计、逐文档 diff、结论；不作为 verified 依据 |
| `assignments.json` | 20 份文档的 A/B 标注员与仲裁人分配表（B/仲裁待指定） |
| `status.md` | WS1 状态看板：A/B 状态、dry-run 差异计数 |
| `arbitration/workbook.csv` | 仲裁工作簿：逐条列出 A/B 差异、A 审计标记，含 decision/note 列 |
| `README.md` | 本说明 |

## 2. 角色

| 角色 | 职责 |
|---|---|
| 标注员 A | 已由 `agent-draft-s7` 完成；如需人工复核，可由人工沿 A 份逐项确认 |
| 标注员 B | 必须独立依据源文 Markdown/PDF 填写 `b/`，不得直接复制 `a/` |
| 领域专家 | 对 A/B 争议项仲裁，写入 `reviewers` 与 `notes` |
| QA | 运行 diff、校验证据、维护报告 |

## 3. B 份填写规则

1. B 份保留表结构（table_id/caption/page_no/profile/orientation），但 `records`、`inspection_items`、`classification_items`、`clauses` 已清空。
2. B 标注员从源文重新填写，不查看 `a/`；完成后把 `annotation.status` 设为 `draft`，`annotator` 填本人。
3. 证据必须写 `page_no/table_id/row/col/quote`；条款证据写 `clause_id/quote`。
4. 不允许用模型预测值反推标注；不确定项写 `status=ambiguous` 并在 `note` 说明。
5. 完成后运行 `gold verify`，确认证据 locator 可定位。

## 4. 一致性门槛

| 指标 | 门槛 |
|---|---|
| `record_key_agreement` | ≥0.99 |
| `cell_value_agreement` | ≥0.98 |
| `comparator_unit_agreement` | ≥0.99 |
| `clause_field_agreement` | ≥0.95 |

门槛与 `metal_doc_agent/goldset_review.py` 的 `DEFAULT_THRESHOLDS` 一致。

## 5. 流程

1. **A/B 独立填写**：B 标注员只看源文，完成 `b/<doc_id>.json`。
2. **逐文档 diff**：
   ```powershell
   python -m metal_doc_agent.cli gold diff --doc gbt1591_2018 `
     --a goldset/v0/review/a/gbt1591_2018.json `
     --b goldset/v0/review/b/gbt1591_2018.json --json
   ```
3. **批量 diff**：
   ```powershell
   python tools/gold_review_batch.py `
     --a goldset/v0/review/a `
     --b goldset/v0/review/b `
     --out goldset/v0/review/reports
   ```
4. **仲裁**：逐条处理 `record_keys_only_a/b`、`value_diffs`、`clause_field_diffs`；领域专家给出结论，更新最终 `goldset/v0/docs/<doc_id>.json` 的 `reviewers` 与 `notes`。
5. **状态升级**：四个指标全部达门槛且争议清零后，`annotation.status=verified`，移除 `owner-override`，记录仲裁人。
6. **复评**：
   ```powershell
   python -m metal_doc_agent.cli gold verify --runs runs/m1_qwen_s8 --json
   python -m metal_doc_agent.cli accept --runs runs/m1_qwen_s8 --strict --json
   ```

## 6. 当前批次状态

- `a/`：20 份，来自当前 verified 基线。
- `b/`：20 份空模板，`annotator=B-unassigned`，`status=draft`。
- `reports/`：批量工具会跳过空 B 并标记 `pending`。
- `dryrun/`：已完成 AI 独立复核（B 来自 `runs/m1_qwen_s8`，仅 chemical/mechanical）；A 审计 5 个标记全部解释为 TableGrid 表头缺陷，未发现 A 确定性错误；详见 `dryrun/conclusion.md`。
- `arbitration/workbook.csv`：507 行待仲裁条目，包含 strict/value diff、A 审计、A/B 记录差异。
- `assignments.json`：B 标注员与仲裁人仍为 TBD。
- `status.md`：20 份文档当前均为 `pending_human_b`。
- `owner-override`：保留，直到人工 A/B 与仲裁完成。

## 7. 备注

- A/B 是治理流程，不是模型评测；不得用 Qwen 预测替代 B 标注。
- 如 B 标注员发现 A 的错误，直接在仲裁记录中登记，不回写 A 副本。
- 所有变更在最终 `goldset/v0/docs` 中留痕，`review/` 目录只作过程证据。
