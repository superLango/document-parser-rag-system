# M2 表格算法基准报告

> 版本：v1.1  
> 日期：2026-11-11  
> 状态：已完成（5 个金标样本，新算法与旧算法持平）

## 1. 范围

覆盖 `services/ocr/algorithms/` 的表格结构与表型链路：

```text
markdown/HTML -> extract_tables -> parse_table -> TableGrid -> profile -> repairs
```

不含记录绑定、矩阵/条款抽取与 Schema 投影（M3/M5）。

## 2. 环境

| 项 | 值 |
|---|---|
| OS | Windows 11（算法基准） |
| Python | 3.13 |
| lxml | 6.1.3 |
| 旧算法 | `legacy/metal-doc-agent`，隔离 `sys.path` 导入，不进入产品代码 |
| 命令 | `python scripts/benchmark/table_gold_eval.py` |

## 3. 金标语料

`new_app/tests/golden/table/`：

| case | 来源 | 表格 | 覆盖点 |
|---|---|---|---|
| `mechanical-basic` | 构造 | 3×3 力学性能 | 基础表头、单位 |
| `chemical-elements` | 构造 | 3×8 化学成分 | 元素列识别、化学表型 |
| `merged-header` | 构造 | 2 行表头 | rowspan + colspan |
| `inspection-items` | 构造 | 3×5 检验项目 | 检验表型、序号列 |
| `qdu-p5-mechanical` | 真实扫描件 + GLM-OCR | 8 列、2 行表头、3 条性能数据 | 真实 OCR 输出、rowspan 数据格、尾部 colspan 正文噪声 |

金标只声明结构字段（profile / orientation / n_cols / header_rows / header_paths / data_rows），避免与值抽取语义耦合。

## 4. 指标定义

| 指标 | 定义 |
|---|---|
| profile | 第一张表的表型与金标一致 |
| orientation | 方向（grade_rows / element_rows）一致 |
| cols | 列数一致 |
| header_rows | 表头行数一致 |
| header_path | 逐列表头路径完全匹配的比例 |
| cell | 金标 data_rows 范围内逐单元格文本匹配率 |

## 5. 结果（5 个样本，宏平均）

| 指标 | 新算法 | 旧算法 | 门槛 | 结论 |
|---|---|---|---|---|
| profile | 1.0000 | 1.0000 | ≥ 旧基线 | 通过 |
| orientation | 1.0000 | 1.0000 | ≥ 旧基线 | 通过 |
| cols | 1.0000 | 1.0000 | ≥ 旧基线 | 通过 |
| header_rows | 1.0000 | 1.0000 | ≥ 旧基线 | 通过 |
| header_path | 1.0000 | 1.0000 | ≥ 旧基线 | 通过 |
| cell | 1.0000 | 1.0000 | ≥ 旧基线 | 通过 |
| 平均延迟 | 4.11 ms | 4.43 ms | ≤ 旧基线 1.2× | 通过 |

逐样本结果见脚本输出；5 个样本新旧算法指标完全一致。

## 6. 关于旧抽取层指标

legacy 文档记录的 20 份金标抽取值：

- Record F1 `0.8771`、Field F1 `0.8156`、Value `0.9134`、Evidence `1.0`、Coverage `0.9625`
- 来源：`legacy/docs/extraction-accuracy-latency-2026-10-30.md`

这些是 **OCR + 表格结构 + 记录绑定 + Qwen 抽取** 的端到端指标，包含本阶段不实现的记录绑定与模型抽取，因此不能与 M2 的结构指标直接比较，也不作为 M2 门槛。M3/M5 完成记录绑定后，再按同一口径复测。

## 7. 结论

1. 表格结构、表型识别与修复链路在 5 个金标样本上与旧算法完全持平，延迟略优。
2. 真实扫描件（Q-Du 第 5 页）经 GLM-OCR 后，新算法正确还原 8 列、2 行表头与 3 条性能记录。
3. M2 回退条件（Field/Record 下降 >0.01、延迟 >1.2×）未触发，不需要回退到纯复制版本。

## 8. 后续

- 扩充金标语料至 20+ 表，覆盖分类表、尺寸偏差表、跨页续表。
- M3/M5 完成后按抽取层口径复测 Record/Field F1。
- 对 GLM 输出中的尾部 `colspan` 正文噪声，M3 在表格边界识别中处理。
