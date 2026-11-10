# 抽取准确率与耗时评测（2026-10-30）

> 目标：扩大语料与文档类型，补样本并准备训练数据，量化真实 Qwen 抽取的准确率与耗时。
> 数据时点：2026-10-30；语料 164 份（20 金标 + 32 扩展 + 112 新类型）；金标评测 20 份；新类型抽样 10 份。

## 0. 结论摘要

| 项 | 结果 |
|---|---|
| 语料规模 | **164 份 / 1776 张表**（有效表 1123，admin 653） |
| 金标准确率（20 份，真实 Qwen） | Record F1 **0.8771**；Field F1 **0.8156**；Value **0.9134**；Evidence **1.0**；Coverage **0.9625** |
| 静默错误 | 金标 **0/20**；全语料 mock **0/164** |
| 耗时（金标 20 份 / 372 页 / 255 表） | p50 **65.7s**、p95 **172.0s**、max 234.8s；**4.29s/页**、6.26s/表、45.1 份/小时 |
| 耗时（新类型 10 份 / 191 页） | p50 **43.0s**、p95 **117.5s**；2.55s/页；74 份/小时；证据率 1.0 |
| 结构缺口 | 164 份语料 T3 **15.67%**；标准类 0%，技术条件 19.4%，质保 51.4%，内部文件 44.3% |
| 训练样本 | 金标 SFT 692/110；新增证据过滤伪样本 58 条；候选集 **750/110**（训练未执行，见 §4） |

**结论**：抽取链路正确性（证据率、silent error）稳定；准确率瓶颈在表头/表格结构化歧义与金标自身歧义，而非数值幻觉（Value 0.9134、Evidence 1.0）。耗时满足“30 页 ≤5 分钟”（31 页实测 168.7s）。

## 1. 语料扩展

### 1.1 选取

从 `data/standards_library/catalog.json`（408 条，180 条重复）按类型配额、页数 4–80、去重（sha+标题）、排除已有运行选取 112 份新文档：

| 类型 | 份数 |
|---|---|
| 技术条件 technical_condition | 19 |
| 制造大纲 manufacturing_outline | 20 |
| 质量保证 quality_assurance | 6 |
| 内部文件 internal_document | 5 |
| 未分类 uncatalogued | 60 |
| 企业标准 enterprise_standard | 1 |
| 类型待定 standard_uncertain | 1 |
| 合计 | **112** |

与 20 份金标 + 32 份扩展合并为 `runs/corpus164`（164 份）。选取脚本 `tools/select_corpus.py`，复跑脚本 `tools/replay_corpus.py`。

### 1.2 分页修复

`markdown/` 语料使用 `<!-- page: N -->` 分页标记，原 `ingest` 只识别 `# Page N`，导致这 144 份文档 `page_count=1`、证据 `page_no=1`。已扩展 `PAGE_RE` 同时识别两种标记（`metal_doc_agent/ingest.py`），重跑后页数、表页号与证据页码正确（回归测试 `tests/test_pipeline.py::PageSplitTests`）。

### 1.3 表型分布（164 份）

| 表型 | 表数 | T1 | T2 | T3 |
|---|---|---|---|---|
| chemical_composition | 188 | 121 | 67 | 0 |
| mechanical_properties | 179 | 32 | 147 | 0 |
| classification | 71 | 29 | 42 | 0 |
| inspection | 320 | 90 | 230 | 0 |
| dimension | 96 | 13 | 83 | 0 |
| unknown | 176 | 0 | 0 | 176 |
| admin（不计入） | 653 | - | - | - |

## 2. 准确率（金标 20 份，真实 Qwen）

### 2.1 总体

| 指标 | 值 |
|---|---|
| Record F1 | **0.8771** |
| Field F1 | **0.8156**（field_fp 19 / field_fn 340） |
| Value accuracy | **0.9134** |
| Evidence rate | **1.0**（8761/8761） |
| Coverage | **0.9625** |
| Comparator mismatch | 42 |
| Unit mismatch | 0 |
| 检测项目准确率 | 0.2444 |
| 分类准确率 | 0.05 |
| 条款准确率 | 0.1392 |
| silent error | **0**（20 份） |

### 2.2 分表型 / 来源

| 维度 | Record F1 | Field F1 | Value |
|---|---|---|---|
| chemical_composition | 0.9778 | 0.8854 | - |
| mechanical_properties | 0.8489 | 0.8000 | - |
| digital_native（6 份） | 0.8819 | 0.8814 | 0.9864 |
| hybrid（1 份） | 1.0 | 0.8398 | 1.0 |
| scanned（13 份） | 0.8653 | 0.7834 | 0.8731 |

### 2.3 本轮修复带来的提升

修复 `_expand_grid` 在“牌号 rowspan 覆盖全部表头行”时被清空、导致子表头整体左移一列的问题（`tablegrid/parser.py::_header_grade_shifted`，回归 `test_rowspan_grade_header_not_shifted`）：

| 指标 | 修复前 | 修复后 |
|---|---|---|
| Field F1 | 0.7846 | **0.8156** |
| Value accuracy | 0.8728 | **0.9134** |
| gbt4437 Field F1 | 0.2203 | **0.8398** |
| gbt4437 Value | 0.1884 | **1.0** |

### 2.4 错误分布

| 类别 | 数量 | 说明 |
|---|---|---|
| header | 307 | 同名列歧义（如两列“断后伸长率”，金标区分 A50mm/A）、表头合并 |
| reference | 108 | 引用/方法归一 |
| normalization | 33 | 数值/比较符归一 |
| ocr | 24 | OCR 行错位（如 gbt3191 T6 数据行左移） |
| semantic | 42 | 比较符语义（≥/≤ 方向） |
| coverage | 3 | 覆盖缺口 |

## 3. 耗时

### 3.1 金标 20 份（372 页 / 255 表 / 1647 记录）

| 指标 | 值 |
|---|---|
| 总耗时 | 1595.7s |
| p50 / p95 / max | **65.7s / 172.0s / 234.8s** |
| 均值 | 79.8s |
| 秒/页 / 秒/表 | **4.29 / 6.26** |
| 吞吐 | 45.1 份/小时 |
| 抽取阶段占比 | 98.5% |
| 触发模型 | 17/20 份（3 份规则即可覆盖） |
| Token | 65,787（prompt+completion） |

最慢：gbt1591（22 页/15 表/519 记录，234.8s）、gbt1220（31 页/24 表，168.7s）、gbt6892（37 页/29 表，164.6s）。最快：gbt14992（1.6s）、gbt3880（1.3s）、sjx100（0.9s），均为规则可直接绑定、未触发模型。

### 3.2 新类型 10 份（191 页 / 131 表 / 46 记录）

| 指标 | 值 |
|---|---|
| 总耗时 | 486.3s |
| p50 / p95 / max | **43.0s / 117.5s / 156.8s** |
| 均值 | 48.6s |
| 秒/页 / 秒/表 | **2.55 / 3.71** |
| 吞吐 | 74.0 份/小时 |
| 证据率 / silent | **1.0 / 0**（296/296 字段有证据） |

新类型文档表数多但可抽取记录少（多数为 admin/inspection/dimension 表），因此单份耗时低于金标标准文档。

## 4. 样本与训练

| 数据集 | 训练 | 评测 | 说明 |
|---|---|---|---|
| `data/m2/sft-v2`（金标） | 692 | 110 | 20 份金标，文档级切分 |
| `data/m2/pseudo-qwen-v1` | 27 | 0 | 10 份新类型 Qwen 输出，证据逐字段校验 |
| `data/m2/pseudo-mock-v1` | 32 | 0 | 112 份扩展语料 mock 输出，证据逐字段校验 |
| `data/m2/sft-v3-candidate` | **750** | 110 | 金标 + 58 条去重伪样本；评测集不变 |

- 伪样本只收 `grade_rows` 且每条属性证据存在、`quote == raw`；标记 `pseudo=true`，**不进入评测**。
- 训练未执行：`training/m2_lora/train_lora.py` 需要模型主机 `/home/grainuser/models/models/Qwen3.5-9B` 与 GPU（GB10）；本地仅 RTX 4070 Laptop 8GB 且无主机 shell，无法完成 9B LoRA。数据与命令已就绪：

```bash
python training/m2_lora/train_lora.py \
  --model /home/grainuser/models/models/Qwen3.5-9B \
  --train data/m2/sft-v3-candidate/train.jsonl \
  --eval data/m2/sft-v3-candidate/eval.jsonl \
  --output /home/grainuser/hanson_m2/adapter-v3
```

## 5. 扩展语料结构指标

### 5.1 T3 按文档类型

| 类型 | 表数 | T3 | T3 比例 |
|---|---|---|---|
| 标准（金标/国标/行标/企业） | 225+70+23 | 0 | **0%** |
| 制造大纲 | 202 | 18 | 8.9% |
| 技术条件 | 103 | 20 | 19.4% |
| 未分类 | 401 | 91 | 22.7% |
| 内部文件 | 61 | 27 | 44.3% |
| 质保 | 37 | 19 | 51.4% |
| 合计 | 1123 | 176 | **15.67%** |

T3 集中在质保/内部文件/合同类文档（审批流程、变更单、要求矩阵）与图纸测量表；标准类文档 T3 为 0。5% 目标适用于标准类生产语料，扩展到非抽取型文档后必然抬升；本轮已将 admin（封面/审签/清单/引用标准）从 T3 分母剔除。

### 5.2 绑定覆盖率（164 份）

| 表型 | 列数 | 已绑定 | 覆盖率 |
|---|---|---|---|
| chemical_composition | 1869 | 1822 | 0.9749 |
| mechanical_properties | 1447 | 1403 | 0.9696 |
| classification | 369 | 360 | 0.9756 |
| inspection | 2115 | 2061 | 0.9745 |
| dimension | 981 | 883 | **0.9001** |
| unknown | 1016 | 728 | 0.7165 |
| 合计 | 7797 | 7257 | 0.9307 |

dimension 在图纸/日文/英文表上出现未绑定列，是后续配方扩展的首要对象。

## 6. 限制与后续

1. **金标非人工双盲**：20 份金标为 agent-draft + 一致性审计；gbt3191 T6 等存在表头行误判与金标条件歧义，准确率含金标噪声。建议对 5 份 heldout 做人工 A/B。
2. **同名列歧义**：两列“断后伸长率”需按表注/列序区分 A50mm/A（gbt4437 T3），当前只保留一列。
3. **OCR 行错位**：个别表数据行缺单元格（gbt3191 T6），需行级修复或人工。
4. **模型调用是选择性的**：17/20 份触发模型，3 份纯规则；耗时分布同时受表数与规则覆盖率影响。
5. **训练未执行**：受模型主机访问与本地显存限制；样本与命令已交付。

## 7. 复现与证据

```bash
# 语料选取与重放
python -m tools.select_corpus --out runs/corpus_v2/selection.json
python -m tools.replay_corpus --selection runs/corpus_v2/selection.json \
  --out-root runs/corpus_v2 --ocr mock --extractor mock
# 真实 Qwen 金标 / 新类型
python -m tools.replay_corpus --selection runs/qwen_gold_v2/selection.json \
  --out-root runs/qwen_gold_v2 --ocr mock --extractor qwen \
  --qwen-base http://192.168.1.35:9989/v1
python -m tools.replay_corpus --selection runs/qwen_diverse/selection.json \
  --out-root runs/qwen_diverse --ocr mock --extractor qwen \
  --qwen-base http://192.168.1.35:9989/v1
# 评测与报告
python -m metal_doc_agent.cli eval --gold goldset/v0 --runs runs/qwen_gold_v2 --out eval/qwen-gold-v2
python -m tools.extraction_report --gold-runs runs/qwen_gold_v2 --mock-runs runs/mock_gold_v2 \
  --eval eval/qwen-gold-v2 --diverse-runs runs/qwen_diverse \
  --out eval/extraction-report.json --md eval/extraction-report.md
```

| 证据 | 位置 |
|---|---|
| 准确率/耗时明细 | `eval/extraction-report.json` / `.md` |
| 金标评测 | `eval/qwen-gold-v2/eval.json` / `.md` |
| 新类型抽样 | `runs/qwen_diverse/timings.jsonl` |
| 164 份审计 | `eval/m4-164.json` / `.md`（silent 0） |
| 冷启动/结构 | `eval/coldstart-164.json`、`eval/recipes/binding-coverage-164.json` |
| 训练候选集 | `data/m2/sft-v3-candidate/`（750/110） |
