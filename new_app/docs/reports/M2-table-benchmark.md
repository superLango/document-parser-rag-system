# M2 表格算法基准报告

> 版本：v1.0  
> 日期：2026-11-11  
> 状态：初版（本地 fixture；金标语料与旧基线对比待补）

## 1. 范围

覆盖 `services/ocr/algorithms/` 的表格结构链路：

```text
markdown/HTML -> extract_tables -> parse_table -> TableGrid -> profile -> repairs
```

不含矩阵抽取、条款抽取与 Schema 投影（M3/M5）。

## 2. 环境

| 项 | 值 |
|---|---|
| OS | Windows 11 + WSL2（算法在 Windows Python 运行） |
| Python | 3.13 |
| lxml | 6.1.3 |
| 运行方式 | `python scripts/benchmark/table_benchmark.py` |

## 3. 语料

| fixture | 表格数 | 说明 |
|---|---|---|
| `tests/fixtures/ocr/mechanical.md` | 1 | 3 列力学性能表（牌号 / Rm / A） |

> 当前仅有本地构造样本；真实国标 PDF 金标语料尚未纳入。

## 4. 结果

`repeats = 50`：

| 指标 | 值 | 门槛 | 结论 |
|---|---|---|---|
| 平均解析延迟 | 1.45 ms | ≤ 旧基线 1.2× | 旧基线未测，待补 |
| p95 延迟 | 1.91 ms | — | 记录 |
| 确定性 | True（50 次输出哈希一致） | 必须一致 | 通过 |
| 表格识别 | 1/1 | 全部识别 | 通过 |

输出结构：

| fixture | table | profile | rows | cols | header_rows |
|---|---|---|---|---|---|
| mechanical.md | T1 | mechanical_properties | 3 | 3 | 1 |

## 5. 旧基线对比

旧管线（`legacy/metal-doc-agent`）依赖 `pipeline`、`settings` 与外部 OCR 模型，当前开发网络无法直接运行，因此尚未产出旧基线指标。

回退条件（Field/Record F1 下降、延迟超过 1.2× 等）暂不触发；待模型服务器与环境恢复后补测，再决定是否回退到纯复制重构版本。

## 6. 失败样本

暂无。

已知风险：

- PDF 原生路径依赖 PyMuPDF 表格识别，复杂合并表可能漏列；真实 PDF 需以 GLM 返回的 HTML 为主。
- 跨页续表的编号/表头相似度阈值沿用旧启发式，未在新语料上重新校准。

## 7. 结论与后续

1. 表格结构、表型识别与数据驱动修复链路可用，确定性满足要求。
2. 需补充真实金标表格（目标 ≥20 张，覆盖化学/力学/检验/尺寸/admin）与旧基线指标。
3. 需在模型服务器恢复后完成 GLM 适配器联调与真实 PDF 抽样对比。
