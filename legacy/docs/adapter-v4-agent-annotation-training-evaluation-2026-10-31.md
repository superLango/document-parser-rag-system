# adapter-v4：自标注样本训练、评测与解析流程总结（2026-10-31）

## 0. 结果总览

本轮按“没有人工标注样本”的前提，由 agent 自行选取 36 份文档、按自身理解标注（规则抽取 + 证据逐条校验），合并旧金标与伪样本数据训练 adapter-v4，并在模型服务器上用真实 adapter 重跑了三组评测。

20 份既有金标（goldset/v0）主结果：

| 配置 | Record F1 | Field F1 | Value acc | p50 | p95 | 总耗时 |
|---|---|---|---|---|---|---|
| base native | **0.8771** | **0.8156** | 0.9134 | 65.7s | 172.0s | 1595.7s |
| adapter-v3 全映射 | 0.8771 | 0.8106 | 0.9069 | 68.3s | 325.3s | 2464.4s |
| adapter-v3 rules-first | 0.8604 | 0.7999 | 0.9132 | 14.3s | 53.2s | 416.1s |
| **adapter-v4 rules-first** | 0.8604 | 0.8017 | **0.9134** | 16.0s | 60.5s | 488.8s |
| adapter-v4 全映射（19 份） | 0.8706 | 0.7999 | 0.8986 | 468.0s | 2625.6s | 15196.8s |

注：adapter-v4 全映射在 gbt14992_2015 上 3000s 超时（该文档 25 页 13 表），因此只有 19 份，指标不可与 20 份直接比较；全映射逐行调用适配器，序列化推理下不可用于生产。

adapter-v5（用修订后样本训练）复测结果见第 12 节：精度与 v4 持平，vLLM 下 p50 12.9s / p95 44.1s。

结论：**adapter-v4 与 adapter-v3 精度基本持平**（rules-first Field 0.8017 vs 0.7999，Value 0.9134 vs 0.9132），仍略低于 base native（0.8156/0.9134）；**rules-first 把 p50/p95 从 base 的 65.7/172.0s 降到 16.0/60.5s**。新标注数据没有改变既有无标注金标的表现。

## 1. 本轮变更

| 变更 | 说明 |
|---|---|
| 自标注工具 | 新增 `tools/build_agent_gold.py`：选样、规则标注、证据逐条校验、切分、manifest |
| 自标注金标 | `goldset/agent-v1`：36 份、320 条记录、1572 字段，全部带 evidence |
| 训练数据 | `data/m2/sft-v5-candidate`：train 1709 / eval 232（sft-v2 692/110 + sft-agent-v1 1017/122） |
| 训练脚本 | 复用 `training/m2_lora/train_lora.py`、`run_m2_lora.sh`（远端 `hanson_m2/code/`） |
| 推理脚本 | 新增 `training/m2_lora/run_vllm_lora.sh`（vLLM 启动封装） |
| 部署结论 | vLLM 0.26.0 能加载 adapter 但实测未生效，LoRA 推理回退到 transformers shim `serve_adapter.py:9990` |

## 2. 自标注数据集（goldset/agent-v1）

### 2.1 选样

- 候选池：`runs/corpus_all` 的 231 份已入湖文档，排除 `goldset/v0` 已标注的 20 份。
- 过滤：规则抽取记录数 ≥ 2；按语料类型配额选样，配额未满时用剩余候选补齐。
- 结果 36 份，落在要求的 30–50 区间：

| 语料类型（原始） | 份数 | 金标 schema 映射 |
|---|---|---|
| technical_condition | 4 | agreement |
| manufacturing_outline | 7 | other |
| uncatalogued | 20 | other |
| national_or_industry_standard | 4 | other |
| enterprise_standard | 1 | enterprise |

- 切分：22 mini（训练）/ 7 dev（训练）/ 7 heldout（评测）。SFT 数据无泄漏（train 29 份、eval 7 份，交集 0）。

### 2.2 标注方法

1. 用确定性抽取器（`MockExtractor`）在文档的 TableGrid 上生成候选记录：牌号/状态 + 元素或力学属性。
2. 对每个字段校验证据：`evidence.jsonl` 中该 cell 的 `quote` 必须与字段 `raw` 完全一致；任一字段无证据则整条记录丢弃。
3. 输出与 `goldset/v0` 相同的 schema：表级 `table_id/profile/orientation/records`，记录级 `grade/condition/properties{raw,comparator,unit,lower,upper,evidence}`。
4. 标注状态 `reviewed`，note 明确 “agent rules + evidence verification; not human double-blind”。

### 2.3 规模与分布

| 指标 | 数值 |
|---|---|
| 文档 / 表 / 记录 / 字段 | 36 / 75 / 320 / 1572 |
| 证据覆盖 | 1572/1572 = 100% |
| 化学元素字段 Top | Cr 133、Mn 124、S 122、C 120、Si 117、P 114、Ni 99 |
| 力学字段 Top | Rm 63、A 50、Rp0.2 48 |
| 比较符 | max 550、eq 452、range 441、text 69、min 60 |
| 表型 | chemical_composition 61 表、mechanical_properties 14 表 |

自洽检查：用规则抽取直接对 `goldset/agent-v1` 打分得到 Record 0.9972 / Field 0.9995 / Value 1.0（36 份）。这说明金标与规则一致，**heldout 衡量的是模型对“规则版式”的复现能力，不是独立人工真值**。

## 3. 训练（模型服务器）

- 训练数据：`data/m2/sft-v5-candidate`
  - train 1709：header_mapping_constrained 68、row_record 361、row_record_perturb 555、clause_extract 64、citation_constraint 661
  - eval 232：header 13、row 41、clause 23、citation 155
  - 字符长度：p50 269 / p90 689 / p99 1001 / max 1097
- 配置：Qwen3.5-9B，LoRA r=16 / alpha=32 / dropout=0.05，max_seq=1536，batch=1，grad_accum=16，lr=1e-4，2 epoch，bf16 + gradient checkpointing。
- 结果（`adapter-v4/run_report.json`、`logs/train_v4.log`）：

| 指标 | 数值 |
|---|---|
| 训练样本 / 评测样本 | 1709 / 232 |
| 步数 | 214 |
| 耗时 | 4952.3s（约 82.5 分钟） |
| train_loss | 0.02612 |
| eval_loss | epoch1 0.04338 / epoch2 0.04298 |

对比 adapter-v3：992 样本、124 步、2884.9s、train_loss 0.03978、eval_loss 0.06688。

## 4. 部署与 vLLM 结论

- 模型服务器：`192.168.1.35`（主机名 `spark-15b6`，GB10，用户 `grainuser`）。
- vLLM 0.26.0：`/home/grainuser/models/venv/bin/vllm`，base `/home/grainuser/models/models/Qwen3.5-9B`。
- 启动问题与修复：EngineCore 子进程找不到 `ninja` 导致 `RuntimeError: Engine core initialization failed`；`run_vllm_lora.sh` 通过 `PATH=$VENV/bin:$PATH` 修复。
- **LoRA 曾未生效，已定位并修复**：`:9991` 加载原始 `adapter-v4` 后，同 prompt 下 base 与 adapter 输出逐字一致；根因是 PEFT 权重键前缀与 vLLM 期望不一致，转换后已验证生效，详见第 11 节。
- 因此评测使用 transformers shim：`serve_adapter.py --adapter adapter-v4 --params inference_params.json --port 9990`，`/health` 返回 `Qwen3.5-9B-adapter-v4`；单请求约 12–13s/170 tokens（GB10 带宽受限）。

## 5. 抽取测试

评测配置：

| 配置 | prompt | rules-first | row SFT |
|---|---|---|---|
| adapter-v4 rules-first | sft_m2 | 1 | 0（表头规则命中时不调模型） |
| adapter-v4 全映射 | sft_m2 | 0 | 30 行/块 |

### 5.1 20 份金标准确率

见第 0 节主表。分表型（rules-first）：

| 表型 | Record F1 | Field F1 |
|---|---|---|
| chemical_composition | 0.9778 | 0.8854 |
| mechanical_properties | 0.8060 | 0.7626 |

逐文档对比（rules-first，adapter-v4 vs adapter-v3）：19/20 份完全一致；仅 qs10_0351_2004 由 0.7647 升到 0.8000。

### 5.2 耗时

| 配置 | 文档数 | p50 | p95 | 总耗时 |
|---|---|---|---|---|
| adapter-v4 rules-first | 20 | 16.0s | 60.5s | 488.8s |
| adapter-v4 全映射 | 19 | 468.0s | 2625.6s | 15196.8s |
| adapter-v4 rules-first（agent 集） | 14 | 26.4s | 59.0s | 418.6s |

全映射慢的原因：`sft_m2` 对每个 block/行都调用适配器，transformers shim 串行执行；gbt1591 2605s、gbt1220 2807s、gbt6892 1778s。rules-first 在规则完整时不调模型，恢复 base 级时延。

## 6. 自标注集评测（agent-v1 dev+heldout，14 份）

| 配置 | Record F1 | Field F1 | Value acc | p50 | p95 |
|---|---|---|---|---|---|
| adapter-v4 rules-first | 0.6258 | 0.6259 | 0.7076 | 26.4s | 59.0s |
| adapter-v3 rules-first | 0.6258 | 0.6259 | 0.7076 | 26.1s | 44.4s |
| 规则抽取（金标自洽，非泛化） | 0.9972* | 0.9995* | 1.0* | — | — |

*规则分数在 36 份上计算，含训练集，仅用于证明标注与规则一致。

adapter-v3 与 adapter-v4 的 14 份聚合指标完全相同（逐文档 10/14 的结果文件字节一致），说明新标注没有改变这一批版式上的模型行为；差异只出现在 `ext_cb3333a17c`，且两者都是 0 分。

逐文档：4 份为 0（v2_c0ead7e694 13 条、ext_1b51e38df2 6 条、v2_94c651e0bd 6 条、ext_cb3333a17c 12 条），原因集中在规则版式与 Qwen 抽取器不一致：

- `ext_cb3333a17c` T2 化学表为 `element_rows`，3 行表头每行只含一个元素（Ti/Al/Mo）；T3 力学表为转置版式，表头是 `σbMPa / σ0.2MPa / δ5%`，`profile.py` 判为 `grade_rows`。规则金标由 MockExtractor 的特性生成，Qwen 路径（规则映射 + 适配器）无法复现。
- 其余 0 分文档同类：多行元素表头、属性行/牌号列转置、缺表头路径。

这是“标注由规则生成、抽取器换成模型”造成的结构性差异，而非单纯模型精度问题。

## 7. 人工复核 JSON

| 文件 | 范围 | 字段 | 匹配 | 不匹配 | 漏抽 | 多字段 | 多记录 |
|---|---|---|---|---|---|---|---|
| `eval/manual-review/adapter-v4-gold-rulesfirst.json` | 20 份金标 | 1199 | 875 (73.0%) | 109 | 215 | 68 | 292 |
| `eval/manual-review/adapter-v4-gold.json` | 19 份金标（全映射） | 1049 | 746 (71.1%) | 125 | 178 | 95 | 264 |
| `eval/manual-review/adapter-v4-agent.json` | 14 份自标注 | 270 | 133 (49.3%) | 94 | 43 | 23 | 8 |

结构：`documents[].tables[].records[].fields[]`，每字段含 `machine/gold/match`，`machine` 为空表示漏抽、`gold` 为空表示多抽；`machine_extra_fields`/`machine_extra_records` 单列，不计入准确率。

## 8. 当前文档解析流程

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
  → 编排（M3）：固定图 ingest→ocr→tablegrid→route→bind→extract→validate→repair→gate
  → 平台：任务队列（lane）、复核工作台、字段事件、发布闸门、分享/审计
```

模型平面：base Qwen（vLLM `:9991`，当前可用）、adapter-v4（transformers `:9990`）、GLM-OCR `:9977`（由 hansonDoc_RAG 提供，见第 13 节）、版面 PP-DocLayoutV3（hansonDoc_RAG parsekit 进程内，无独立 HTTP 端口）。抽取器默认规则优先，模型只在规则无法覆盖或配置为 `sft_m2` 时介入。

## 9. 结论、限制与建议

1. **训练闭环可执行**：36 份自标注 → 1709 条 SFT → adapter-v4（214 步 / 82.5 分钟），数据、脚本、日志、报告齐全。
2. **精度与 v3 持平**：rules-first Field 0.8017、Value 0.9134；base 仍最高（0.8156/0.9134）。新标注未改变既有无标注金标的表现。
3. **时延收益明确**：rules-first p50 16.0s / p95 60.5s，约为 base 的 1/4（p50）/ 1/3（p95）。
4. **全映射不可用**：逐行调用 + 串行推理，p50 468s、p95 2626s，gbt14992 超时；生产不建议启用。
5. **自标注 heldout 暴露版式缺口**：Field 0.6259、Value 0.7076，且 adapter-v3/v4 结果一致；4 份 0 分集中在转置力学表、多行元素表头。建议补规则/样本后重训 v5，并把这类版式加入 header/row 样本。
6. **vLLM LoRA 已修复**：Qwen3.5-9B 下需要把 PEFT 键前缀改写为 `base_model.model.language_model.model.layers...`（`convert_adapter_for_vllm.py`）；修复后 `:9991` 与 base 输出明显不同，可继续作为推理后端。
7. **标注性质**：agent 标注为规则 + 证据校验，不是人工双盲；对外报告应注明。

## 10. 复现与证据

```bash
# 自标注
python -m tools.build_agent_gold --runs runs/corpus_all --out goldset/agent-v1 --limit 40
python -m tools.build_m2_dataset --goldset goldset/agent-v1 --runs runs/corpus_all --out data/m2/train-agent-v1
python -m tools.build_sft_v2 --dataset data/m2/train-agent-v1 --runs runs/corpus_all --out data/m2/sft-agent-v1

# 训练（模型服务器）
DATA_DIR=/home/grainuser/hanson_m2/data-v5 \
OUTPUT=/home/grainuser/hanson_m2/adapter-v4 MAX_SEQ=1536 \
bash /home/grainuser/hanson_m2/code/run_m2_lora.sh

# 推理服务（transformers shim）
python code/serve_adapter.py --model models/models/Qwen3.5-9B \
  --adapter hanson_m2/adapter-v4 --params hanson_m2/code/inference_params.json --port 9990

# 抽取（adapter-v4 rules-first）
METAL_DOC_EXTRACTOR_PROMPT=sft_m2 METAL_DOC_SFT_RULES_FIRST=1 \
METAL_DOC_SFT_ROW_LIMIT=0 SFT_BASE_URL=http://192.168.1.35:9990/v1 \
SFT_MODEL=Qwen3.5-9B-adapter-v4 \
python -m tools.replay_corpus --selection runs/qwen_gold_v2/selection.json \
  --out-root runs/adapter_v4_gold_rulesfirst --ocr mock --extractor qwen \
  --qwen-base http://192.168.1.35:9990/v1

# 评测与人工复核
python -m metal_doc_agent.cli eval --gold goldset/v0 \
  --runs runs/adapter_v4_gold_rulesfirst --out eval/adapter-v4-gold-rulesfirst
python -m tools.export_manual_review --runs runs/adapter_v4_gold_rulesfirst \
  --gold goldset/v0 --out eval/manual-review/adapter-v4-gold-rulesfirst.json
```

| 证据 | 位置 |
|---|---|
| 自标注金标 | `goldset/agent-v1/`（manifest + 36 docs） |
| 训练数据 | `data/m2/sft-v5-candidate/`（1709/232） |
| 训练报告 | 模型服务器 `hanson_m2/adapter-v4/run_report.json`、`logs/train_v4.log` |
| 金标评测 | `eval/adapter-v4-gold/eval.json`、`eval/adapter-v4-gold-rulesfirst/eval.json` |
| 自标注评测 | `eval/adapter-v4-agent/eval.json`、`eval/adapter-v3-agent/eval.json` |
| 耗时报告 | `eval/extraction-report-adapter-v4*.json/.md`、`eval/extraction-report-adapter-v3-agent.*` |
| 人工复核 | `eval/manual-review/adapter-v4-*.json` |
| vLLM 启动 | `training/m2_lora/run_vllm_lora.sh`、`training/m2_lora/convert_adapter_for_vllm.py`、日志 `hanson_m2/logs/vllm_v4_mapped.log` |
| 修订后金标 | `goldset/agent-v2/`（295 记录） |
| 修订后样本 | `data/m2/sft-agent-v2/`（1053/122）、`data/m2/sft-v6-candidate/`（1745/232） |
| 规则自洽验证 | `eval/agent-v2-mock4c/eval.json` |
| 规则+vLLM 验证 | `eval/agent-v2-v5/eval.json`、`eval/extraction-report-agent-v2-v5.*` |
| adapter-v5 训练 | 服务器 `hanson_m2/adapter-v5/run_report.json`、`logs/train_v5.log` |
| adapter-v5 评测 | `eval/adapter-v5-gold-rulesfirst2/`、`eval/agent-v2-v5/` |
| adapter-v5 复核 | `eval/manual-review/adapter-v5-gold-rulesfirst.json`、`agent-v2-v5.json` |

## 11. 后续修复（2026-10-31）

### 11.1 vLLM LoRA 根因与修复

| 项 | 内容 |
|---|---|
| 现象 | `:9991` `/v1/models` 能看到 `adapter-v4`，但同 prompt 下 base 与 adapter 输出逐字一致（10/10 训练样本） |
| DEBUG 证据 | `No LoRA weights found for module language_model.model.layers.27.self_attn.qkv_proj, skipping.` |
| 根因 | PEFT 保存的键是 `base_model.model.model.layers.*`，去掉 `base_model.model.` 后为 `model.layers.*`；vLLM 的 Qwen3.5 文本主干模块路径是 `language_model.model.layers.*`，全路径匹配失败 |
| 修复 | `training/m2_lora/convert_adapter_for_vllm.py` 重写 256 个张量键为 `base_model.model.language_model.model.layers.*`，生成 `adapter-v4-vllm`；`run_vllm_lora.sh` 用 `ADAPTER_PATH` 指向转换后的目录 |
| 验证 | 转换后同 prompt 下 base 与 adapter 5/10 输出不同，差异符合 SFT 行为（行记录 condition 增加“切向/径向”、条款抽取返回完整句子） |

vLLM 服务（已生效）：

```bash
python code/convert_adapter_for_vllm.py \
  --src /home/grainuser/hanson_m2/adapter-v4 \
  --dst /home/grainuser/hanson_m2/adapter-v4-vllm
VLLM_LOGGING_LEVEL=DEBUG ADAPTER_PATH=/home/grainuser/hanson_m2/adapter-v4-vllm \
  bash code/run_vllm_lora.sh   # :9991
```

### 11.2 版式规则补充（转置力学表 / 多行元素表头）

改动：

| 文件 | 变更 |
|---|---|
| `tablegrid/profile.py` | 元素列判定：多数列末级表头是元素符号时判 `grade_rows`，不再误判 `element_rows`；新增 `property_rows` 方向（力学属性写在表头、值在单行） |
| `extraction/mock.py` | 化学表允许无牌号列（单记录）；新增条件列（“元素”列→熔炼/成品分析）；跳过脚注行与重复元素行；力学表允许无牌号列（单记录） |
| `extraction/qwen.py` | 与上对应：无牌号列时生成 `grade=None` 记录；化学单记录模式跳过元素名行；力学无牌号时不再强制文档牌号；牌号列识别加入 材质/钢号/材料/钢类 |
| `tools/build_agent_gold.py` | 新增 `--reuse`（保持原 36 份文档与切分重新标注）；新增从表格单元格重建 evidence 指针，覆盖新规则提取到的 cell |

效果（4 份原先 0 分文档）：

| 文档 | 修订前记录 | 修订后记录 | 规则重放得分 |
|---|---|---|---|
| ext_cb3333a17c | 12（垃圾键） | 2（T2 11 元素 + T3 Rm/Rp0.2/A/HB） | 1.0 / 1.0 / 1.0 |
| v2_c0ead7e694 | 13（垃圾键） | 4（T3 12 元素 + T4×2 + T5×1） | 1.0 / 1.0 / 1.0 |
| ext_1b51e38df2 | 6（垃圾键） | 1（304H，wt% / 化学成分） | 1.0 / 1.0 / 1.0 |
| v2_94c651e0bd | 6（垃圾键） | 5（T3 12 元素 + T4×3 + T5×1） | 1.0 / 1.0 / 1.0 |

`eval/agent-v2-mock4`：4 份文档 Record 1.0 / Field 1.0 / Value 1.0 / Evidence 1.0（规则与修订后金标一致）。

### 11.3 新标注与样本

- `goldset/agent-v2`：仍为 36 份，记录 295 条，化学表 72、力学表 34（力学表从 14 增至 34，转置/单记录表被正确纳入）。
- `data/m2/train-agent-v2`：header 61 / row 213 / perturb 368 / citation 271；dev、heldout 同步更新。
- `data/m2/sft-agent-v2`：train 1053 / eval 122。
- `data/m2/sft-v6-candidate`：**train 1745 / eval 232**（sft-v2 692 + sft-agent-v2 1053）。
  - header 92（+24）、row 341、perturb 587（+32）、clause 64、citation 661。
- 新增样本示例：`ext_cb3333a17c:header_mapping_constrained` 中，化学表 11 个元素列逐个映射为 property；转置力学表 `σbMPa/σ0.2MPa/δ5%` 映射为 Rm/Rp0.2/A，`HB(d)` 映射为 HB。

下一步建议：用 `sft-v6-candidate` 训练 adapter-v5（数据已就绪，远端需拷贝 `data-v6`），再用 vLLM（转换后的 adapter）重跑 agent-v2 heldout，验证版式缺口是否收敛。

### 11.4 规则 + vLLM 适配器验证（agent-v2 heldout，14 份）

| 配置 | Record F1 | Field F1 | Value acc | p50 | p95 |
|---|---|---|---|---|---|
| agent-v1 金标 + 旧规则（adapter-v4，transformers） | 0.6258 | 0.6259 | 0.7076 | 26.4s | 59.0s |
| **agent-v2 金标 + 新规则（adapter-v5，vLLM）** | **0.8301** | **0.7829** | **0.9655** | 17.2s | 46.4s |

4 份原先 0 分文档全部恢复：`ext_cb3333a17c` 4 条、`v2_c0ead7e694` 4 条、`ext_1b51e38df2` 6 条、`v2_94c651e0bd` 5 条；其余文档记录数也有增加（转置/单记录力学表被纳入）。

## 12. adapter-v5 训练与复测（2026-10-31）

- 数据：`sft-v6-candidate`（训练时版本 train 1792 / eval 232；随后金标元数据修正，最终样本 1745/232）。
- 配置同 v4：Qwen3.5-9B，LoRA r=16 / alpha=32 / dropout=0.05，max_seq=1536，batch=1，grad_accum=16，lr=1e-4，2 epoch。
- 结果：224 步、**4822.6s（80.4 分钟）**、train_loss **0.02338**、eval_loss 0.03693（epoch 2），输出 `adapter-v5`。
- 部署：`convert_adapter_for_vllm.py` 转换后由 vLLM `:9991` 加载，base 与 adapter 输出 5/10 不同，确认生效。

20 份金标（rules-first，vLLM）：

| 配置 | Record F1 | Field F1 | Value acc | p50 | p95 | 总耗时 |
|---|---|---|---|---|---|---|
| adapter-v4（transformers，旧规则） | 0.8604 | 0.8017 | 0.9134 | 16.0s | 60.5s | 488.8s |
| **adapter-v5（vLLM，最终规则）** | 0.8604 | **0.8017** | **0.9134** | **12.9s** | **44.1s** | **328.6s** |

v5 与 v4 精度持平，vLLM 推理使 p50/p95 降低约 20–27%。

重要过程记录：首轮 v5 评测 Field 0.6137 的回退并非模型问题，而是新方向规则对既有表格过度生效（jx25/gjb2057a/mas7079/qs10 由 1.0 降为 0）。已回退方向判定，改为在 `element_rows` / 无牌号力学表内部做单记录兜底；回退后金标恢复 0.8017，agent-v2 的 4 份硬版式仍为 1.0。

人工复核：

| 文件 | 范围 | 字段 | 匹配 | 不匹配 | 漏抽 | 多字段 | 多记录 |
|---|---|---|---|---|---|---|---|
| `eval/manual-review/adapter-v5-gold-rulesfirst.json` | 20 份金标 | 1199 | 875 (73.0%) | 109 | 215 | 68 | 292 |
| `eval/manual-review/agent-v2-v5.json` | 14 份自标注 | 332 | 171 (51.5%) | 156 | 5 | 35 | 6 |

自标注集漏抽仅 5 个字段，说明版式覆盖显著改善；剩余差异主要是多抽字段与条件/单位不一致。

下一步：用最终 `sft-v6-candidate`（1745/232）重训 adapter-v6 并复测（训练约 80 分钟）；数据与脚本已就绪。

## 13. GLM-OCR 正确接入（hansonDoc_RAG）与 GBT2965-2007 复跑（2026-10-31）

更正：此前“模型服务器没有可用 GLM-OCR”的判断有误。模型服务器 `192.168.1.35` 上有 hansonDoc_RAG 项目，GLM-OCR 是其中的 vLLM 服务。

### 13.1 服务与正确用法

| 组件 | 位置/端口 | 说明 |
|---|---|---|
| GLM-OCR vLLM | `:9977`，`/home/grainuser/hansonDoc_RAG/scripts/start_glm_ocr.sh` | 模型 `hansonDoc_RAG_deploy/models/glm-ocr/GLM-OCR`，`max-model-len 32768`、gpu-util 0.16、kv-cache fp8 |
| 版面 PP-DocLayoutV3 | `hansonDoc_RAG/backend/app/services/parsekit` 进程内 | **没有 HTTP 端口**，必须调用 parsekit 才能获得块级版面 |
| 解析入口 | `app.services.parsekit.pipeline.parse_pdf` | 渲染→页眉页脚擦除→版面→阅读顺序→块级 GLM-OCR→拼装 Markdown（`<!-- page: N -->`） |

启动要点：脚本会调用 `models/venv/bin/vllm`，需把它加入 PATH（否则 `FileNotFoundError: ninja`）：

```bash
PATH=/home/grainuser/models/venv/bin:$PATH bash scripts/start_glm_ocr.sh --detach
```

单独跑时不要用 `python script.py` 直接 import `app`（Python 只把脚本目录放进 `sys.path`），需显式指定后端根：

```bash
cd /home/grainuser/hansonDoc_RAG/backend
PYTHONPATH=/home/grainuser/hansonDoc_RAG/backend \
GLMOCR_SERVER_URL=http://127.0.0.1:9977/v1/chat/completions \
venv/bin/python /home/grainuser/hanson_m2/code/parse_with_rag.py <pdf> <out_dir>
```

`parse_with_rag.py` 的 `progress` 回调签名不固定（`rebuild` 只传阶段名），需写成 `lambda *args: ...`。

### 13.2 三种 OCR 路线对比（GBT2965-2007，同一 adapter-v5 + rules-first）

| OCR 路线 | 页 | 表 | 记录 | 检验项目 | 条款 | 状态 | 主要差异 |
|---|---|---|---|---|---|---|---|
| **hansonDoc_RAG parsekit（版面 + GLM-OCR 块级）** | 10 | 9 | 44 | **9** | **56** | **pass** | 表题 表1–表B.2、T6 9 项齐全、T3 持久强度与 B.1 杂质合计已抽、标题与 β 符号正确 |
| 全页 Qwen VL OCR（`runs/gbt2965_2007`） | 10 | 9 | 44 | 9 | 55 | pass | 记录与前者逐字段一致；标题误取“前 言”、β 被识别为 beta |
| 全页 GLM-OCR（`runs/gbt2965_2007_glm`） | 10 | 10 | 51 | 9 | 0 | review | 无版面结构：表型混淆、跨页表拼接错位、条款为 0 |

结论：GLM-OCR 只有在**版面分块**的前提下才优于全页转录；直接把整页丢给 GLM-OCR 反而破坏表格结构。生产链路应使用 hansonDoc_RAG parsekit 产出 Markdown，再交给 metal-doc-agent。

### 13.3 本次修复（均由 RAG 输出暴露）

| 问题 | 位置 | 修复 |
|---|---|---|
| 表题 `*表3*` 不被识别，产生多余条款 | `tablegrid/parser.py::find_caption`、`coverage/outline.py`、`extraction/clauses.py` | 匹配前去掉 `*` 强调符 |
| GLM 的 colspan 脚注行（同一长文本铺满整行）被当成检验项目 | `extraction/nonrecord.py::_footnote` | 新增 `_colspan_note`：≥2 格重复的长文本行视为脚注 |
| 分块表头少一个 colspan 时，`牌号` rowspan 被误清空，列整体左移一格 | `tablegrid/parser.py::_expand_grid` | 继承单元格为表头词（牌号/级别/钢级…）且新行无数字时保留；数据行仍按原逻辑清空 |
| `standard_no` 为空导致审计 review | 文件命名 | 源文件命名为 `GBT2965-2007.md`，`ingest.parse_standard_no` 正常解析 |
| `TB2` 的淬火/时效两行同牌号同条件，被合并为一条（后者覆盖前者） | `extraction/qwen.py` | 新增 `remark_cols`：`备注`/`说明` 列值命中淬火/时效/退火等条件词时作为 condition，两行拆成两条记录 |
| 牌号尾部的脚注字母未剥离（`TC6a`、`TC11a`） | `extraction/qwen.py::_row_grade` | 从表内 `aTC6…` 脚注行提取标记字母，牌号尾部命中时剥离 → `TC6` |
| 表6 表头被识别为 2 行，`化学成分` 项漏抽（8/9） | `tablegrid/parser.py::_is_header_like` | 首列命中表头词但含裸数字（3.2/4.1）的行按数据行处理，表头回到 1 行，检验项目 9/9 |
| 表3 持久强度 σ100h/σ50h/σ35h、表B.1 其余单个杂质/其余杂质总和未抽 | `extraction/qwen.py` | 新增 `_persistence_property`、`_residue_property` 列映射；杂质合计默认“不大于”（max） |
| 表3 脚注 OCR 输出 `σ100hgeqslant590MPa` | `tablegrid/normalize.py::clean_text` | 反斜杠移除前先替换 `\\geqslant`→`≥`、`\\leqslant`→`≤`、`\\geq`/`\\leq` |

回归：`tests/test_tablegrid.py`、`test_tablegrid_v1.py`、`test_normalize.py`、`test_nonrecord.py`、`test_pipeline.py`、`test_routing.py`、`test_qwen_extractor.py`、`test_qwen_sft.py`、`test_matrix_extraction.py` 共 76 项全部通过。

### 13.4 交付物与证据

| 证据 | 位置 |
|---|---|
| 抽取结果（GLM-OCR/RAG 版） | `docs/gbt2965-2007-extraction-result.json` |
| OCR Markdown / 版面 | `metal-doc-agent/runs/gbt2965_2007_rag/GBT2965-2007.md`、`layout.json` |
| 完整运行产物 | `metal-doc-agent/runs/gbt2965_2007_rag/`（result.json、evidence.jsonl、tablegrid/、trace.json…） |
| 解析脚本 | 服务器 `/home/grainuser/hanson_m2/code/parse_with_rag.py` |
| 解析日志 | 服务器 `/home/grainuser/hanson_m2/logs/rag_parse_gbt2965.log` |

耗时：RAG 解析 33.1s（10 页 / 168 块，0 失败）；抽取 0.03s（新增字段映射后规则完整覆盖，未触发模型）；总计约 35s，44 条记录、264 条证据、9 个检验项目，质量 `pass`、0 条审计问题。

`TB2` 现已拆为“淬火性能 / 时效性能”两条记录（保留 ≤980 与 1370 两组值），`TC6a`/`TC11a` 已归一为 `TC6`/`TC11`。

回归验证（20 份金标，rules-first + adapter-v5 via vLLM `:9991`，`runs/adapter_v5_gold_t6fix`、`eval/adapter-v5-gold-t6fix`）：

| 配置 | Record F1 | Field F1 | Value acc | 检验项目 acc | 证据率 | 覆盖率 | 20 份总耗时 |
|---|---|---|---|---|---|---|---|
| v5 基线（`adapter-v5-gold-rulesfirst2`） | 0.8604 | 0.8017 | 0.9134 | 0.2444 | 1.0 | 0.9625 | 328.6s |
| **修复后（remark/脚注/rowspan/T6 表头/T3+B.1 字段）** | **0.8604** | **0.8208** | **0.9368** | **0.30** | 1.0 | 0.9625 | 320.7s |

记录 F1 持平，Field F1 +1.9pt、Value acc +2.3pt、检验项目准确率 +5.6pt；`gjb5301_2004` T5 的 4 行表头曾因 rowspan 守卫过宽而错位，已补充“新行含数字则仍清空”的条件并复测恢复。T6 表头修正后 9 个检验项目全部抽出。

## 14. 对接 hansonDoc_RAG 抽取结果 Schema（2026-10-31）

目标结构取自 hansonDoc_RAG 的 **产品标准抽取模板**（`schema_templates.id=6e2ad0d7-f92a-4663-b5cf-ae01c2378fa7`，KB `25e7d8ef…`），其 `pipeline._result` 输出形态为：

```json
{
  "schema_template_id": "...",
  "schema_name": "产品标准抽取模板",
  "categories": [
    {"feature": "标准信息", "records": [{...}], "rejected": [],
     "missing_fields": [...], "hit_score": null, "hit_count": 1}
  ],
  "summary": {"total_records": 196, "kept_categories": 6, "categories_attempted": 6,
              "skipped": [], "recall": {...}},
  "timing": {"total_sec": 0.25}
}
```

模板类别：`标准信息`（object，标准名称/标准编号）、`热处理制度`（array，材料牌号/工艺名称/保温温度/保温时间/冷却介质…）、以及术语集展开的“检测项目”类别（feature 为 `化学成分 / 室温拉伸 / 高温拉伸 / 高温光滑持久 / 夏比冲击 / 布氏硬度 …`，字段为 项目名称/材料牌号/标准要求/单位/试验温度/方向/试样状态/取样说明…）。

### 14.1 转换方式

新增 `metal-doc-agent/tools/export_hanson_schema.py`，从 metal-doc-agent 的 `result.json`（表 + 记录）做投影，不改现有抽取链路：

| metal-doc-agent | hansonDoc_RAG schema |
|---|---|
| `document.standard_no / title` | 标准信息.标准编号 / 标准名称 |
| 热处理表行（`加热温度，保温时间，冷却方式`） | 热处理制度：按“。”/“；”拆工序，解析保温温度/时间/冷却介质 |
| `chemical_composition` 记录属性 | 化学成分：每条属性一条记录，`标准要求` 带 ≤/余量 |
| `mechanical_properties` 中 Rm/Rp0.2/A/Z（无温度） | 室温拉伸，试验温度=室温，方向按上下文“纵向” |
| 带温度条件的 Rm/Rp0.2/A/Z | 高温拉伸，试验温度=350℃ 等 |
| σ100h/σ50h/σ35h | 高温光滑持久（无温度则室温持久） |
| `na`（原表 `-`） | 不生成记录 |

运行：

```bash
python -m tools.export_hanson_schema --run runs/gbt2965_2007_rag \
  --out ../docs/gbt2965-2007-hansonDoc-schema.json \
  [--template-id <id> --template-name <name>]
```

### 14.2 GBT2965-2007 效果

输出 `docs/gbt2965-2007-hansonDoc-schema.json`：6 个 feature、195 条记录；字段完整性见 `docs/gbt2965-2007-hansonDoc-field-audit.md`。

| category | 记录数 | 说明 |
|---|---|---|
| 标准信息 | 1 | GB/T 2965-2007《钛及钛合金棒材》 |
| 热处理制度 | 26 | 23 个牌号；TA19/TB2/TC6 各拆 2 道工序 |
| 化学成分 | 32 | 4 牌号 ×（Ti+Fe+C+N+H+O+其余单个+其余总和） |
| 室温拉伸 | 112 | 表2 24 条 × 4 项 + 表B.2 4 条 × 4 项 |
| 高温拉伸 | 12 | 表3 Rm |
| 高温光滑持久 | 12 | σ100h/σ50h/σ35h 中非 `-` 的 12 个值 |

字段完整性：2498 个字段单元，已填 2148（86.0%），空 350（原文未给出或不适用，一律留空）。空缺全部有据：表A.1 未给工艺名及装炉/升温等参数、化学成分不适用方向/尺寸/试验温度、表B 附录未给方向/尺寸/试样状态。数值准确性已逐表对照 PDF 页图：标准信息 1/1、化学成分 32/32、室温拉伸 112/112、高温 12/12、持久 12/12、热处理 26/26 一致。

`schema_template_id/name` 默认取上述模板，如线上 KB 使用其他模板可用参数覆盖；`hit_score` 置空、`hit_count` 记为记录数。原文没有的字段直接留空（不写“未规定/未注明”），`missing_fields` 仍按 hansonDoc_RAG 的 `missing_required_fields` 语义输出。



