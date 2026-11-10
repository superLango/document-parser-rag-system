# adapter-v3 训练、抽取评测与解析流程总结（2026-10-30）

> 模型服务器：`192.168.188.75`（GB10，SSH `grainuser`）；adapter-v3 推理服务 `:9990`。
> 语料：**231 份 / 2116 张表**；金标评测 20 份；新增伪样本 370 条；SFT v4 候选 995/110。
> 结论：**训练与部署完成；adapter-v3 在 20 份金标上未超过 base（Field 0.8106 vs 0.8156），但 rules-first 模式把 p95 从 172s 降到 53s。生产建议保留 base native。**

## 0. 结果总览（20 份金标，同一套代码与金标）

| 配置 | Record F1 | Field F1 | Value | Evidence | p50 | p95 | 总耗时 |
|---|---|---|---|---|---|---|---|
| Base native（Qwen3.5-9B，基准） | 0.8771 | **0.8156** | **0.9134** | 1.0 | 65.7s | 172.0s | 1595.7s |
| adapter-v3 全表头映射（sft_m2，行规则） | 0.8771 | 0.8106 | 0.9069 | 1.0 | 68.3s | 325.3s | 2464.4s |
| adapter-v3 rules-first（sft_m2，行规则） | 0.8604 | 0.7999 | 0.9132 | 1.0 | **14.3s** | **53.2s** | **416.1s** |

- adapter-v3 全表头映射：化学 0.8781、机械 0.7980（base：0.8854 / 0.8000）。
- rules-first：化学与 base 完全一致（0.8854），机械降至 0.7604（规则漏掉部分机械记录）。
- comparator mismatch：base 42、adapter 全映射 42、rules-first 31；unit mismatch 0。
- 证据率三者均为 1.0，silent error 0。

**判读**：伪样本+adapter 训练没有提升金标准确率；base 仍是精度最优。adapter 的价值在于 rules-first 模式大幅降低时延，但需接受机械表召回略降。

## 1. 本轮变更

| 项 | 内容 |
|---|---|
| 模型地址 | `192.168.188.75`；base vLLM 9989 未在该机安装，adapter 服务 9990 已启动 |
| 语料 | 新增 67 份（含 1–3 页合同/短规范与 80+ 页文档），总 **231 份** |
| 样本 | 新增伪样本 **370**（row_record 190、header_mapping 180），覆盖 72 份文档 / 167 张表；SFT v4 候选 **995 train / 110 eval** |
| 训练 | adapter-v3：992 样本、2 epoch、124 步、48 分 05 秒、train_loss 0.0398、eval_loss 0.0669 |
| 程序 | 修复 SFT 行阶段误用 base 客户端；新增 `METAL_DOC_SFT_RULES_FIRST`（规则已完整绑定时不再调模型） |
| 测试 | 引擎 **382** 通过；adapter 单文档冒烟 qdu302 全对 |

## 2. 语料与样本覆盖

### 2.1 语料结构（231 份）

| 指标 | 值 |
|---|---|
| 文档 / 表 | 231 / **2116**（有效表 1326，admin 790） |
| T1 / T2 / T3 | 330 / 729 / **267**（T3 20.14%） |
| 文档级 production | 0.5736 |
| 绑定覆盖率 | 0.9350 |
| silent error | **0/231** |

T3 按类型：标准类 0%、企业标准 0%、国标/行标 0%、制造大纲 8.9%、技术条件 19.4%、未分类 29.9%、内部文件 46.0%、质保 51.4%。T3 集中在质保/合同/内部文件，不是标准表版式问题。

绑定分表型：chemical 0.9751、mechanical 0.9696、classification 0.9745、inspection 0.9765、dimension 0.9027、unknown 0.7795。

### 2.2 样本覆盖

| 项 | 值 |
|---|---|
| 伪样本 | 370（row 190 / header 180） |
| 覆盖文档 | 72 / 231（31.2%） |
| 覆盖表 | 167 / 1326（12.6%） |
| 按类型覆盖文档 | 国标 5/5、企业 3/5、制造大纲 15/24、技术条件 11/31、未分类 35/132、内部 3/6、质保 0/7（金标 20 份按设计排除） |
| 样本分表型 | chemical 207、mechanical 124、inspection 26、dimension 8、classification 5 |

覆盖率受限的原因：多数新增文档只有审签/清单/质保要求表，缺少可标注的化学/力学记录；header 样本只收绑定覆盖率 ≥80% 且至少 2 个 grade/condition/property 列的表。

### 2.3 SFT 数据

| 数据集 | train | eval | 说明 |
|---|---|---|---|
| `data/m2/sft-v2` | 692 | 110 | 20 份金标，文档级切分 |
| `data/m2/pseudo-v2` | 325 | 0 | 231 份 mock，规则标签，证据校验 |
| `data/m2/pseudo-qwen-v2` | 45 | 0 | 10 份 Qwen 输出，证据校验 |
| `data/m2/sft-v4-candidate` | **995** | 110 | 金标 683 + 伪 312；同输入优先 Qwen 标签；评测集不变 |

## 3. 训练（模型服务器）

- 代码：`/home/grainuser/hanson_m2/code/train_lora.py`；数据 `data-v4/train.jsonl`、`eval.jsonl`；输出 `adapter-v3`。
- 配置：Qwen3.5-9B，LoRA r=16 / alpha=32 / dropout=0.05，max_seq=1536，batch=1，grad_accum=16，lr=1e-4，2 epoch，bf16 + gradient checkpointing。
- 结果：992 条训练（3 条被 tokenizer 过滤）、110 条评测；124 步；**2884.9s**；train_loss **0.03978**；eval_loss **0.06688**（epoch 2）。
- 部署：`serve_adapter.py --adapter adapter-v3 --params inference_params.json --port 9990`；`/health` 返回 `Qwen3.5-9B-adapter-v3`。

## 4. 抽取测试

### 4.1 准确率

| 指标 | base | adapter 全映射 | adapter rules-first |
|---|---|---|---|
| Record F1 | 0.8771 | 0.8771 | 0.8604 |
| Field F1 | **0.8156** | 0.8106 | 0.7999 |
| Value accuracy | 0.9134 | 0.9069 | **0.9132** |
| Evidence / Coverage | 1.0 / 0.9625 | 1.0 / 0.9625 | 1.0 / 0.9625 |
| 化学 Field F1 | 0.8854 | 0.8781 | 0.8854 |
| 机械 Field F1 | **0.8000** | 0.7980 | 0.7604 |

差异集中在两张表：gbt4437（adapter 映射 Table 2/3 时值 0.8734 vs base 1.0）与 qs10（0.9286 vs 0.9333），其余 18 份逐文档一致。说明 adapter 对规则已覆盖的版式没有增益，对歧义表也未稳定超过 native prompt。

### 4.2 耗时

| 配置 | p50 | p95 | 秒/页 | 秒/表 | 总耗时 |
|---|---|---|---|---|---|
| base native | 65.7s | 172.0s | 4.29 | 6.26 | 1595.7s |
| adapter 全映射 | 68.3s | 325.3s | 6.62 | 9.66 | 2464.4s |
| adapter rules-first | **14.3s** | **53.2s** | **1.12** | **1.63** | **416.1s** |

adapter 全映射触发模型 19/20 份、104,116 token；rules-first 13/20 份、24,024 token。

adapter 全映射慢的原因：`sft_m2` 对每个 block 都调用适配器，而 9B transformers 推理缺少 `causal_conv1d`/`fla` 优化内核；gbt14992 仅映射就 719s（base 1.6s）。rules-first 在规则完整时不调用模型，恢复 base 级时延并进一步降低（规则行阶段）。

### 4.3 分文档（adapter 全映射 / rules-first，秒）

| 文档 | 页/表 | 全映射 | rules-first |
|---|---|---|---|
| gbt40303_2021 | 33/16 | 244.9 | 20.8 |
| gbt1591_2018 | 22/15 | 304.5 | 126.7 |
| gbt14992_2015 | 25/13 | 719.7 | 1.6 |
| gbt1220_2007 | 31/24 | 172.9 | 23.3 |
| gbt6892_2015 | 37/29 | 133.9 | 24.5 |
| 其余 15 份 | - | 0.9–183 | 0.9–49 |

## 5. 人工复核 JSON

- 全量：`eval/manual-review/adapter-v3-gold.json`（20 份、含 machine/gold/证据）
- 仅差异：`eval/manual-review/adapter-v3-mismatches.json`（17 份，聚焦人工核对）
- rules-first 版本：`eval/manual-review/adapter-v3-rulesfirst-gold.json`

结构：

```json
{
  "totals": {"fields": 1199, "match": 885, "mismatch": 120, "gold_only": 194,
             "extra_fields": 77, "extra_records": 292},
  "documents": [{
    "doc_id": "qdu302_2015",
    "tables": [{
      "table_id": "T2", "profile": "mechanical_properties",
      "header_paths": [["牌号"], ["热处理状态"], ["抗拉强度Rm/MPa"]],
      "records": [{
        "grade": "2A14",
        "fields": [{
          "property": "Rm", "match": true,
          "machine": {"raw": "430", "comparator": "min", "unit": "MPa",
                       "evidence": {"page_no": 5, "table_id": "T2", "row": 2, "col": 3, "quote": "430"}},
          "gold": {"raw": "430", "comparator": "min", "unit": "MPa",
                   "gold_evidence": {"page_no": 5, "table_id": "T2", "row": 2, "col": 3}}
        }]
      }]
    }]
  }]
}
```

复核方式：按 `documents[].tables[].records[]` 逐条看 `fields[].match`；`machine` 为空表示漏抽，`gold` 为空表示多抽，`machine_extra_fields` 为金标未标注的额外字段（不计入准确率，仅参考）。adapter 全映射总计：字段 1199，匹配 885（73.8%），不匹配 120（10.0%），漏抽 194（16.2%）。

## 6. 当前文档解析流程

```text
上传/入湖
  → ingest 读取 PDF/Markdown，分页（# Page N 或 <!-- page: N -->），生成文档元数据
  → OCR（mock 或 GLM-OCR）输出页 Markdown / 版面 sidecar（bbox）
  → TableGrid 解析 HTML 表格：rowspan/colspan、表头路径、合并单元、单位、脚注、表型、方向、跨页块
  → 配方路由：结构签名 → production / explore / human；列绑定 bind_columns
  → 抽取：
       ├─ 规则优先：表头别名、元素/属性规范化、矩阵条件（温度/方向/厚度）
       ├─ 模型：native 或 SFT（header_mapping_constrained + row_record）
       └─ 非记录项：检验项目、分类/新旧牌号
  → 归一化/校验：数值、比较符、区间、单位、证据必须可解析
  → 项目清单/条款/引用：检测项目发现、条款抽取、引用与跨标准任务
  → 证据：每字段 cell 级 evidence（页/表/行/列/quote），可附版面 bbox
  → 业务词典对齐：项目/方法/类别匹配，未命中进入 new_terms
  → 链接与覆盖：表格-条款链接、项目覆盖审计、模板覆盖计划
  → 审计：L0–L2 校验、静默错误、风险分级（high 阻断、medium 复核）
  → 结果：result.json + tablegrid/ + evidence.jsonl + trace.json + audit.md
  → 编排（M3）：固定图 ingest→ocr→tablegrid→route→bind→extract→validate→repair→gate，预算/检查点/trace
  → 平台：任务队列（lane）、复核工作台、字段事件、发布闸门、分享/审计
```

各阶段代码位置：

| 阶段 | 代码/产物 |
|---|---|
| 入湖/分页 | `metal_doc_agent/ingest.py` → `pages.json` |
| OCR | `metal_doc_agent/ocr/` → 页 Markdown + layout |
| 表格 | `metal_doc_agent/tablegrid/parser.py`、`profile.py` → `tablegrid/T*.json` |
| 路由/绑定 | `recipes/routing.py`、`recipes/binding.py` → `column_bindings.json` |
| 抽取 | `extraction/qwen.py`、`extraction/mock.py`、`matrix.py`、`nonrecord` |
| 归一化/校验 | `tablegrid/normalize.py`、`validation.py`、`review/audit.py` |
| 项目/条款/引用 | `items/discover.py`、`clauses`、`references.py`、`cross_standard.py` |
| 证据 | `evidence.jsonl`；`pipeline.attach_evidence_bboxes` |
| 词典对齐 | `alignment.json`、`new_terms.json` |
| 覆盖/链接 | `coverage/plan.py`、`links.json`、`coverage_audit.json` |
| 编排 | `orchestration/graph.py`（预算、修复、检查点、发布闸门） |
| 平台复核 | `apps/api`（field_reviews / review-risks / review）、`apps/web` 字段复核 tab |

模型平面：base Qwen `:9989`、adapter `:9990`、GLM-OCR `:9977`、Layout `:9978`。抽取器默认规则优先，模型只在规则无法覆盖或配置为 `sft_m2` 时介入。

## 7. 结论、限制与建议

1. **训练可执行、可复现**：adapter-v3 在 GB10 上 48 分钟完成，服务已可用；训练数据、命令、报告齐全。
2. **精度没有提升**：adapter-v3 全映射 Field 0.8106（base 0.8156），rules-first 0.7999；伪样本带来的版式覆盖未转化为金标收益。
3. **时延可大幅下降**：rules-first 把 p50/p95 降到 14.3s/53.2s（base 65.7/172.0），代价是机械表 Record F1 0.849→0.806。
4. **生产建议**：默认保留 base native；对时延敏感场景可启用 rules-first，但需接受机械表召回下降；adapter 继续扩充高质量人工标注样本后再评估。
5. **限制**：新主机未安装 vLLM，base 9989 不可用；base 指标沿用同模型旧主机结果。金标为 agent-draft + 一致性审计，非人工双盲；gbt3191/gbt4432 等表仍受 OCR 行错位影响。

## 8. 复现与证据

```bash
# 训练（模型服务器）
DATA_DIR=/home/grainuser/hanson_m2/data-v4 \
OUTPUT=/home/grainuser/hanson_m2/adapter-v3 MAX_SEQ=1536 \
bash /home/grainuser/hanson_m2/code/run_m2_lora.sh
# 推理服务
bash -lc 'python code/serve_adapter.py --model models/models/Qwen3.5-9B \
  --adapter hanson_m2/adapter-v3 --params hanson_m2/code/inference_params.json --port 9990'
# 抽取（adapter rules-first）
METAL_DOC_EXTRACTOR_PROMPT=sft_m2 METAL_DOC_SFT_RULES_FIRST=1 \
METAL_DOC_SFT_ROW_LIMIT=0 SFT_BASE_URL=http://192.168.188.75:9990/v1 \
SFT_MODEL=Qwen3.5-9B-adapter-v3 \
python -m tools.replay_corpus --selection runs/qwen_gold_v2/selection.json \
  --out-root runs/adapter_v3_gold_rulesfirst --ocr mock --extractor qwen \
  --qwen-base http://192.168.188.75:9989/v1
# 评测与人工复核
python -m metal_doc_agent.cli eval --gold goldset/v0 \
  --runs runs/adapter_v3_gold_rulesfirst --out eval/adapter-v3-gold-rulesfirst
python -m tools.export_manual_review --runs runs/adapter_v3_gold \
  --gold goldset/v0 --out eval/manual-review/adapter-v3-gold.json
```

| 证据 | 位置 |
|---|---|
| adapter 全映射评测 | `eval/adapter-v3-gold/eval.json` / `.md` |
| adapter rules-first 评测 | `eval/adapter-v3-gold-rulesfirst/eval.json` / `.md` |
| 耗时报告（全映射 / rules-first） | `eval/extraction-report-adapter-v3.*`、`eval/extraction-report-adapter-v3-rulesfirst.*` |
| 人工复核 JSON | `eval/manual-review/adapter-v3-gold.json`、`adapter-v3-mismatches.json` |
| 训练数据 | `data/m2/sft-v4-candidate/`（995/110） |
| 样本覆盖 | `eval/pseudo-coverage.json` |
| 231 份语料结构 | `eval/corpus-231-structure.json`、`eval/m4-231.*`、`eval/coldstart-231.*` |
| 训练日志/报告 | 模型服务器 `hanson_m2/logs/train_v3.log`、`adapter-v3/run_report.json` |
