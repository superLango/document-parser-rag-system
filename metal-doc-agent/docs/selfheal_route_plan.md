# 自愈路线（Self-Heal Route）实施方案与开发计划

> 目标：在不改动当前已部署解析路线（r7-95）的前提下，新增一条独立的“自动审查 + 用户反馈 + 受控修复”路线。  
> 原则：**现有路线零改动、零回归；新路线独立部署、默认关闭；只读现有产物；修复分级、沙箱验证、自动回滚。**

---

## 0. 现状固化与独立路线约束（2026-11-10）

> 本节是后续所有开发的前置约束：先冻结现有路线，再新增自愈路线。自愈路线只读现有产物，不修改现有引擎、平台 API、前端路由与结果页渲染逻辑。

### 0.1 当前路线基线

| 项 | 基线 |
|---|---|
| 部署版本 | r7-95（以线上 `HANSON_RELEASE_TAG` 为准；仓库最近报告为 r7-61） |
| 引擎测试 | `python -m pytest --collect-only -q`：574 |
| 平台测试 | 63 |
| Web 测试 | 5 |
| 模型平面 | GB10 `spark-15b6`：GLM-OCR 9977（seq12/gpu0.4）、Layout CPU 9978、Layout GPU 9979、Qwen3.5-9B adapter-v5 9991 |
| 不可误杀 | NIII `server.py`（基线 PID 2138/2139）属于其他项目 |
| 基线文件 | `data/selfheal/baseline/current_route_baseline.json` |
| 模型平面快照 | `data/selfheal/results/baseline_model_plane.txt` |

配置哈希已记录在基线 JSON 中（`column_aliases.json`、`table_repairs.json`、`recipes/*`、`schema_templates/product_standard.json`、两份 `pyproject.toml`、`pnpm-lock.yaml`）。任何改动这些文件的提交都必须显式说明属于 L2 候选还是现有路线修复。

### 0.2 零影响隔离规则

1. **代码隔离**：自愈代码只新增在 `metal_doc_agent/selfheal/` 与 `apps/selfheal`（或平台内独立 `selfheal` 路由模块）；现有 `pipeline.py`、`api.py`、`apps/api/hanson_api/router.py`、`KbExtractionDetailPage.tsx` 只允许增加 feature flag 控制的挂载点，不改变原有分支。
2. **默认关闭**：`SELFHEAL_ENABLED=0`。关闭时不注册路由、不启动 worker、不建表、不写 `data/selfheal/` 以外任何文件。
3. **只读现有产物**：自愈只读 `METAL_DOC_DATA/jobs/<job_id>/`；不写入、不移动、不删除现有产物。
4. **数据隔离**：独立 SQLite/DB、独立队列、独立产物目录 `data/selfheal/`；平台现有表不新增字段、不改语义。
5. **配置隔离**：生产 `configs/` 只读；L2 只写 `data/selfheal/overlays/<id>/configs/`；候选配方通过现有 `recipes/lifecycle.py` 与 `shadow.py` 流程晋升。
6. **前后端隔离**：平台 API 不新增对现有端点行为的修改；前端只在结果页增加受 flag 控制的“问题反馈”入口，不改变现有 tab、布局与请求链路。
7. **运行时隔离**：独立 `selfheal-api` / `selfheal-worker`，独立端口与镜像 tag；现有 `engine-api`、`worker-prod`、`worker-explore`、`platform-api` 的镜像和命令不变。

### 0.3 零影响验收（Phase 0 必须执行）

1. 固定 5 份文档（覆盖国标、军标、采购规范、扫描件、表格密集），`SELFHEAL_ENABLED=0` 跑现有 pipeline。
2. 对基线 JSON 中的 stable 产物做规范化 SHA256 对比；排除 `state.json`、`trace.json`、`metrics.json`、`artifacts.json`、`audit.md`、页图与 layout 侧车。
3. 现有 574 引擎测试、63 平台测试、5 Web 测试全部通过。
4. 现有模型平面四个端口（9977/9978/9979/9991）保持 200；验证 35B 时临时停止，验证后按基线参数恢复，GLM-OCR 必须使用 `seq12/gpu0.4`，不能用仓库脚本默认的 `seq2/gpu0.16`。

### 0.4 当前结论

- 现有路线已冻结为“可回滚基线”：代码、配置、测试数量、模型平面参数与产物哈希口径均已记录。
- 自愈路线业务代码已按 Phase 1-4 落地，全部位于 `metal_doc_agent/selfheal/`、`apps/selfheal/` 与新增测试文件；未修改任何现有引擎/平台/前端文件。
- 默认 `SELFHEAL_ENABLED=0`：不建表、不注册路由、不写文件；全量引擎测试 613 通过，2 个失败为本次改造前已存在的基线问题（见 0.5）。

### 0.5 Phase 0 执行结果（2026-11-10）

**执行方式**：全流程由 `data/selfheal/phase0/auto_phase0.py` 自动化完成（模型切换也在脚本内），支持断点续跑；每一步写入 `state.json`，日志在 `data/selfheal/phase0/logs/auto/`。

**抽取 A/B（20 份金标，mock OCR，同一 Markdown 输入，`product_full`）**

| 变体 | 记录 F1 | 字段 F1 | 值准确率 | 证据覆盖 | 必填覆盖 |
|---|---:|---:|---:|---:|---:|
| 9B native（非流式） | 0.8646 | 0.8273 | 0.9373 | 1.0 | 0.9625 |
| 9B sft_m2（rules-first, row_limit=0） | 0.8479 | 0.8164 | 0.9371 | 1.0 | 0.9625 |
| 35B native（NVFP4, 32K, 1 seq） | 0.8646 | 0.8273 | 0.9373 | 1.0 | 0.9625 |

- 35B 门禁：record F1 / field F1 相对 9B native 的比值均为 1.0（阈值 0.95），**PASS**。
- 关键发现：本路线的模型只负责“列角色映射”，数值由确定性代码写入，因此 35B 与 9B 在 20 份语料上产出完全等价的记录；35B 没有抽取质量收益，但单文档耗时更低（qdu302 11.7s vs 52.2s，9B 自定义服务为串行 HF generate）。
- 决策：**抽取仍用 9B adapter-v5**（成熟、显存占用低、已 SFT）；35B 用于审查、归因与修复规划。
- 9B 服务是 `lora-infer-v1` 非流式接口，必须 `QWEN_STREAM=0`；否则客户端收不到 SSE 帧，全部模型调用返回空串并静默回退到规则（本次已修正，避免 A/B 被污染）。

**35B 审查准入（48 个审计包：40 注入 + 8 正确）**

| prompt | 严格召回（字段+类型） | 任意召回 | 误报率（正确包被判问题） | 平均耗时 |
|---|---:|---:|---:|---:|
| v1（基础规则） | 0.55 | 0.725 | 0.625 | 18.5s |
| v1 重评分（字段名归一） | 0.65 | 0.725 | 0.625 | 18.5s |
| v2（补充记录约定） | 0.725 | 0.775 | 0.625 | 15.6s |

- 注入类型召回（v2）：wrong_value 0.875、wrong_unit 0.875、extra_value 0.75、wrong_requirement 0.625、missing_value 0.5。
- 误报主要来自三类：把 `condition` 合并列当成结构错误、把原文 `-` 当成缺失、对已判一致的记录仍输出 finding。
- 结论：**未达到无人值守准入门槛（误报率 62.5%）**。审查只能以“候选 finding + 证据门禁 + 确定性规则优先”的方式运行，finding 默认进入 `proposed`，不得直接自动应用；已通过证据门禁与 L1/L2 门禁兜底。
- 结果文件：`data/selfheal/phase0/audit/results_35b*.jsonl`、`summary_35b_v2.json`。

**模型平面恢复**

- 35B 验证/运行前停止 GLM-OCR/Layout/adapter-v5，结束后由 `restore_after_35b.sh` 恢复。
- 复验：9977/9978/9979/9991 全部 200；公网 35032/35033/35034/35035 全部 200；GLM-OCR 为 `--max-num-seqs 12 --gpu-memory-utilization 0.4`。
- 汇总：`data/selfheal/phase0/summary.md`、`summary.json`。

### 0.6 自愈路线实现状态（Phase 1-4）

| 能力 | 实现 | 测试 |
|---|---|---|
| 契约/配置/SQLite 隔离 | `selfheal/contracts.py`、`config.py`、`storage.py`（8 张 `sh_*` 表） | `tests/test_selfheal_storage.py` |
| 自动审查 | `selfheal/audit.py`：审计包、确定性规则（证据缺失/引文不符/单位缺失/重复记录）、模型 finding 校验与证据落点 | `tests/test_selfheal_audit.py` |
| 用户反馈 | `selfheal/feedback.py`：目标校验、引文/证据定位、`needs_more_info` 回复 | `tests/test_selfheal_pipeline.py` |
| L1 文档级修复 | `selfheal/l1.py`：沙箱重解析、`repair_diff.json`、生产配置零写入 | 同上 |
| L2 配置修复 | `selfheal/l2.py` + `sandbox.py`：白名单算子、overlay 项目根、shadow 复跑、候选配方 | `tests/test_selfheal_l2_l3.py` |
| L3 代码修复 | `selfheal/l3.py`：文件白名单/≤5 文件/≤200 行/必须含测试；默认 `propose_only`；仅 `SELFHEAL_AUTO_MERGE=1` 且有 `.git` 才 `git apply` | 同上 |
| 门禁 | `selfheal/gates.py`：证据、复现、目标指标、无新增错误、迭代上限、回归（可注入） | `tests/test_selfheal_pipeline.py` |
| 编排/归因去重 | `selfheal/pipeline.py`：反馈与审计 finding 统一走 L1→L2→L3，findings 去重 | `tests/test_selfheal_integration.py` |
| 独立服务 | `selfheal/api.py` + `apps/selfheal/main.py`（:8100）、`worker.py`、独立 SQLite、`/selfheal/ui` 反馈面板 | `tests/test_selfheal_api.py` |
| 部署隔离 | `infra/docker/compose.selfheal.yaml`（独立 compose 文件，默认不启动） | 零影响测试 |
| 开发自动化 | `data/selfheal/dev/phases.py`：dev0-dev5 逐阶段跑测试，失败即停 | 全部 PASS |

- 全量回归：`python -m pytest -q` → **613 passed, 2 failed**；两个失败是本次改造前已存在的基线问题：
  1. `test_hanson_schema_export.py::...test_slim_projection_from_job_artifacts`：标题空格规范化期望不一致；
  2. `test_m5_infra.py::...test_secret_scan_passes`：仓库内存在本地 `infra/docker/.env`（2026-11-07 创建，非本次新增）。
- 自愈路线未修改任何现有引擎/平台/前端文件；`SELFHEAL_ENABLED=0` 时不创建数据库/目录，仅保留 `/healthz`。

### 0.7 单模型切换与共存执行结果（2026-11-10）

**决策**：Qwen3.6-35B-A3B 替代 Qwen3.5-9B 作为唯一 LLM；35B 与 GLM-OCR/Layout 同时常驻，不再做模型切换。

**5 份 PDF 端到端 A/B（真实 GLM-OCR，非 mock）**

| 变体 | 记录 F1 | 字段 F1 | 值准确率 | 证据覆盖 | 必填覆盖 | 总耗时 |
|---|---:|---:|---:|---:|---:|---:|
| 9B + GLM-OCR | 0.525 | 0.5589 | 0.5971 | 1.0 | 0.95 | 725.2s |
| 35B + GLM-OCR | 0.525 | 0.5589 | 0.5971 | 1.0 | 0.95 | 632.8s |

- 896 条记录中仅 2 处字段级差异，指标完全一致；35B 总耗时低约 13%。
- 端到端指标低于 mock-OCR A/B（0.86/0.83）是真实 OCR 噪声导致，与模型选型无关；两种模型面对同一 OCR 输出表现一致。

**共存实测**

| 项 | 实测 |
|---|---|
| GLM-OCR | 9977，32K / seq8 / gpu 0.30 |
| Layout | 9978 CPU、9979 GPU，不变 |
| Qwen3.6-35B | 9991（公网 35035），16K / seq1 / gpu 0.40 / kv fp8 |
| 两模型加载后可用内存 | 41.9GB |
| 5 份 PDF 压测期间可用内存 | 约 38GB |
| OOM 看门狗 | 运行中，只杀 35B 进程组 |
| 公网端口 | 35032/35033/35034/35035 全 200 |

结论：此前“不能同跑”是“35B 32K + GLM 0.4 + 9B”三模型叠加导致的内存预算不足，不是架构不兼容；去掉 9B 并重调 GLM 的 KV 预算后可以稳定共存，且仍有约 38GB 余量。

**配置变更**

- `infra/docker/compose.yaml` 默认值：`METAL_DOC_EXTRACTOR_PROMPT=native`、`METAL_DOC_SFT_RULES_FIRST=0`、`QWEN_MODEL=Qwen3.6-35B-A3B-NVFP4`、`QWEN_CONCURRENCY=1`、`MODEL_TIMEOUT=300`。
- `infra/docker/compose.selfheal.yaml`：`SELFHEAL_MODEL_URL=http://192.168.188.75:9991/v1`（与抽取共用同一 35B）。
- 端口不变：9991 由 9B 换成 35B，公网仍是 35035，平台与前端零改动。
- 向后兼容：35B 同时注册别名 `Qwen3.5-9B-adapter-v5`、`adapter-v5`、`Qwen3.5-9B`，未升级的引擎容器在滚动窗口内仍能调用同一个 35B。

**运维脚本**

- 切换：`/home/grainuser/hanson_selfheal/ops/switch_single_llm.sh`
- 回滚：`/home/grainuser/hanson_selfheal/ops/rollback_single_llm.sh`（恢复 GLM seq12/gpu0.4 + 9B adapter-v5）
- 基线快照：`data/selfheal/baseline/single_llm_plane.json`

**剩余约束**

- 35B 上下文为 16K；实测抽取从不超限，审查仅 0.68% 的表超限，详见 0.8。
- 审查误报率仍为 0.625，finding 只作为候选，必须过证据与修复门禁。
- 35B 无抽取 LoRA，必须使用 `native` prompt；`sft_m2` 只适用于 9B adapter。

### 0.8 35B 上下文容量评估（2026-11-10，暂不改动）

对 `markdown/` + `标准文件/` 全量 436 份文档、6,026 张表做提示词规模测算（脚本 `data/selfheal/phase0/measure_prompt_sizes.py`，结果 `prompt_size_report.json`）：

| 调用类型 | 超过 16K 的表 | P50 | P95 | P99 | 最大 |
|---|---:|---:|---:|---:|---:|
| 抽取（表头映射） | 0 / 6,026 | 490 | — | 1,300 | 13,723 |
| 审查（每表审计包） | 41 / 6,026（0.68%） | 934 | 8,271 | 13,182 | 86,704 |

- 抽取只发送“表头 + 前 3 行样本”，16K 足够，无需调整。
- 审查超限集中在 8 类文档（大量为同一文档的重复上传）：GJB 5301-2004、GB/T 1591-2018、43d4e4…、5c7ee8…、99c14a…（含 266 列 OCR 破碎表）、bd8857…（汇编手册）、da6e78…、fde3d2…。
- 决策：**暂不改 16K、不做分块**。极端表出现时再按以下顺序处理：
  1. 行/列分块审查（6K token 预算/块，按 `record_id` 合并），保持 16K；
  2. 选择性审查（仅 chemical/mechanical、`n_cols ≤ 40`），跳过汇编手册与宽表；
  3. 确定性规则优先，模型只审被规则标记的行；
  4. 默认提到 24K（GLM 降到 `0.27/seq7`），覆盖 P99；
  5. 低频按需切 32K（GLM 降到 `0.24/seq6`），仅用于个别大表。
- 触发条件建议：分块前先统计新语料中“审计包 > 16K”的比例；超过 2% 或单月出现 > 50 次时再实施方案 1/2。

---

## 1. 范围与边界

### 1.1 本路线要解决的问题

1. 解析完成后自动审查 schema 与原文是否一致（对不对、准不准、全不全）。
2. 用户在结果页提交问题反馈，系统自动处理并回复。
3. 自动生成并验证修复方案：
   - L1 文档级修复（只影响当前文档）
   - L2 配置/配方修复（同类表型）
   - L3 代码级修复（沙箱、测试、回归、灰度）
4. 无人工审核，依赖证据门禁、自动测试、回归集、灰度与自动回滚。

### 1.3 单模型选型：Qwen3.6-35B-A3B

新方案统一使用 **Qwen3.6-35B-A3B**，同时承担抽取、审查、反馈归因、L1/L2 修复决策和 L3 补丁提案。是否替换现有 `Qwen3.5-9B-adapter-v5`，由 Phase 0 的 A/B 门禁决定。

选择理由：

- 35B 总参数、仅 3B 激活（MoE），推理算力低，适合单服务器
- Agentic coding 能力强，SWE-bench Verified 73.4，适合 L3 代码补丁
- 原生支持长上下文，审查可以按表/按类别裁剪
- 开放权重，可本地 4-bit 部署

| 任务 | Qwen3.6-35B-A3B | 说明 |
|---|---|---|
| 结构抽取 | 可用，但需 A/B | 现 9B 是抽取 SFT adapter，35B 需 prompt/LoRA 适配验证 |
| 单表/单行证据审查 | 可用 | 审计包裁剪到单类别/单表，输出受控 JSON |
| 跨表/跨章节一致性 | 比 9B 强 | 仍以确定性校验 + TableIR 为主 |
| 用户反馈归因 | 可用 | 固定分类 + few-shot |
| L1 文档级修复 | 可用 | 重解析 + 证据对比 |
| L2 配方/列绑定 | 可用 | 限制在算子白名单 + JSON schema |
| L3 代码补丁 | 可用，但默认只出提案 | 沙箱 + 测试 + 回归 + 灰度后才允许合并 |

**单模型切换门禁（Phase 0）：**

1. 同一批 50 份高质量文档、同一 OCR 缓存、同一 prompt 风格。
2. 对比 9B vs 35B：schema 行数、空要求率、记录/检验项、错误数、耗时。
3. 35B 抽取质量不得低于 9B 的 95%；否则先做 prompt 适配或 LoRA，再决定是否替换。
4. 若 35B 抽取明显掉点，保留 9B 做抽取、35B 做审查/修复（临时双模型），或继续微调 35B；不强行单模型。

### 1.4 量化与单服务器部署（最低显存、精度损失可控）

“占用最低且精度不过多缺失”的理论结论：**4-bit AWQ/GPTQ 权重 + FP8 KV cache**。实测模型机已有 NVFP4 权重，优先采用 NVFP4（见 1.7）；3-bit/2-bit 不建议用于正式抽取。

| 精度 | 35B 权重显存 | GB10 119GB 可用内存 | 说明 |
|---|---|---|---|
| BF16 | ~70GB | 可行但占用大 | 不推荐，留给 OCR/layout/其他服务不足 |
| FP8 | ~35GB | 可行 | 精度优先时可选，仍留 ~80GB |
| 4-bit AWQ/GPTQ（备选） | ~18-20GB | 可行 | 精度损失通常 1-2%；需另下载/转换，实测未采用 |
| **NVFP4（Blackwell 原生）** | **~10-12GB（实测 24.67GB 权重）** | **已实测可用** | vLLM 0.26.0 + FlashInfer CUTLASS；32K 通过 |
| 3-bit | ~13-15GB | 可行 | 精度损失明显，不推荐正式抽取 |

> 实测更新（2026-11-10）：模型机已有 `Qwen3.6-35B-A3B-NVFP4`（24.67GB，6 分片），无需下载；vLLM 0.26.0 自动选择 `compressed-tensors` + FlashInfer CUTLASS。32K 上下文实测总占用约 73GB，可用内存约 49.6GB，不能与 GLM-OCR/9B 同时常驻。详见 1.7。

部署建议：

1. **GB10（119GB 可用）**
   - NVFP4 单模型（实测），权重 24.67GB；32K 总占用约 73GB
   - 不能与 GLM-OCR、layout、9B 同时常驻；验证/运行前需停现有模型
   - `max_model_len=16384~32768`，`max_num_seqs=1~2`（GB10 内存带宽有限，并发不宜过大）
   - 若后续做精度对比，再评估 AWQ/GPTQ 4-bit
2. **24GB 级显卡**
   - 35B 4-bit 可跑但很紧，只适合单请求/离线
   - 不建议与 OCR/layout 同卡
3. **16GB 级显卡**
   - 35B 4-bit 放不下；3-bit 精度损失大，不建议
   - 退路：Qwen3-14B 或 Qwen2.5-Coder-7B 4-bit，仅做低风险修复提案
4. **单模型调度**
   - 抽取和审查串行调用，避免同时占用两份 KV cache
   - 审查/修复走离线队列，低峰期执行
   - L3 代码修复使用同一模型，限制 `max_tokens` 和 diff 范围

### 1.5 现有模型服务器实测配置与约束

已核查模型服务（`39.107.239.208` / 内网 `192.168.188.75`）：

- 硬件：**NVIDIA GB10（aarch64 + CUDA 13），约 119GB 可用统一内存**
- 当前在线：
  - Qwen3.5-9B + adapter-v5（自定义 `lora-infer-v1` 服务，`:35035`）
  - GLM-OCR vLLM（`:35032`，32K，kv-cache fp8）
  - PP-DocLayoutV3 layout（GPU `:35034`，CPU fallback `:35033`）
- 历史约束：
  - 两个 9B 服务同时在线时占用约 98GB/119GB，仅剩约 20GB
  - 32K / 0.25 曾因无 KV cache 启动失败；当前按 16K / 0.35 / 2 seq 运行
  - GB10 内存带宽有限，9B 单请求约 12-13s/170 tokens；长上下文会放大开销
  - `causal_conv1d` / `flash-linear-attention` 未安装，线性注意力走 PyTorch 参考实现

对 35B-A3B 单模型的影响：

1. **内存足够**：4-bit 约 20GB，替换 9B 后可留约 90GB，适合并发和后续其他用途。
2. **运行时是主要风险**：Qwen3.6-35B-A3B 是较新的 MoE/多模态模型，GB10 的 aarch64 + CUDA 13 环境未必有现成 vLLM/SGLang 支持；必须先做最小启动验证。
3. **解码速度不一定比 9B 快**：虽然只有 3B 激活，但每 token 仍要读 35B 权重；GB10 带宽受限，实际 tokens/s 需实测。
4. **上下文不能开太大**：建议 16K-32K，不要使用 200K；审查按表裁剪。
5. **单模型替换门禁**：先并行跑 9B 与 35B 做 A/B；35B 抽取质量 ≥ 9B 的 95%、延迟可接受，才退役 9B。

结论：**GB10 上已验证 NVFP4 可用（24.67GB 权重，32K 总占用约 73GB，不能与 9B/GLM 同时常驻）；AWQ/GPTQ 仅作为后续精度对比备选。先完成 9B vs 35B 抽取 A/B，再谈替换 9B。**

### 1.6 调研结论与决策记录（2026-11-09）

| 决策项 | 结论 | 依据 |
|---|---|---|
| 自愈路线模型 | Qwen3.6-35B-A3B 单模型 | 35B total / 3B active，coding 与审查能力足够，单模型运维简单 |
| 是否立即替换 9B | 不立即替换，先 A/B | 9B 是抽取 SFT adapter，35B 需要 prompt/LoRA 适配验证 |
| 量化版本 | 默认 NVFP4（已实测）；AWQ/GPTQ 作为备选 | GB10 119GB；NVFP4 权重 24.67GB，32K 总占用约 73GB，不能与 9B/GLM 同时常驻 |
| 是否使用 FP8/BF16 | FP8 可选，BF16 不推荐 | FP8 约 35GB；BF16 约 70GB，影响并发和后续其他服务 |
| 上下文与并发 | 16K-32K，1-2 seq（实测 32K/1 seq，2 路并发） | GB10 带宽受限，长上下文和并发会放大延迟 |
| 运行时风险 | 高，必须先做最小启动验证 | GB10 为 aarch64 + CUDA 13，缺 `causal_conv1d` / `flash-linear-attention` |
| 35B 抽取门槛 | 质量 ≥ 9B 的 95%，延迟可接受 | 否则保留 9B 做抽取，35B 仅做审查/修复，或先微调 |
| L3 代码修复 | 默认只出提案 | 沙箱 + 测试 + 回归 + 灰度后才允许合并 |
| 新路线隔离 | `SELFHEAL_ENABLED=0` 默认关闭 | 独立服务、独立队列、独立产物、现有路线零改动 |

Phase 0 必须先完成：

1. GB10 上 Qwen3.6-35B-A3B 4-bit/NVFP4 最小启动验证（能否加载、能否稳定输出 JSON、32K 是否 OOM）。
2. 9B vs 35B 抽取 A/B（同一批 50 份、同一 OCR、同一 prompt）。
3. 35B 审查准入基准（注入错误召回率、正确文档误报率）。
4. 量化版本对比（4-bit vs NVFP4）与 tokens/s、内存、单文档耗时。

代码修复请求裁剪：

- 只给相关文件片段、失败测试、报错栈、目标 diff 范围
- 输出统一 diff，不执行代码
- 每次只修一个根因，不做大范围重构

新增配置：

```text
QWEN_MODEL=Qwen3.6-35B-A3B-NVFP4      # GB10；统一抽取/审查/修复
QWEN_MODEL_URL=...                     # 单模型端点（实测 :9988）
SELFHEAL_MODEL=Qwen3.6-35B-A3B-NVFP4
SELFHEAL_AUDIT_MODEL=Qwen3.6-35B-A3B-NVFP4
SELFHEAL_CODE_MODEL=Qwen3.6-35B-A3B-NVFP4
SELFHEAL_CODE_AGENT=off                # 默认只出提案
SELFHEAL_AUTO_MERGE=0                  # 默认不自动合并
QWEN_MAX_MODEL_LEN=32768
```

> 实测：首次启动需 FlashInfer JIT 编译（`MAX_JOBS=1~2`，约 30-40 分钟），之后启动约 3-4 分钟；35B 不能与 GLM-OCR/9B 同时常驻，验证/运行前需停现有模型，结束后按基线恢复。

### 1.7 量化模型实测与稳定性验证（2026-11-10）

模型机已有完整的 `Qwen3.6-35B-A3B-NVFP4`，无需下载。实测环境与结论如下。

**环境与模型**

| 项 | 实测 |
|---|---|
| 硬件 | NVIDIA GB10，119GiB 统一内存，aarch64，CUDA 13 |
| 运行时 | vLLM 0.26.0，FlashInfer 0.6.14，Humming 0.1.10 |
| 权重 | `/home/grainuser/models/models/Qwen3.6-35B-A3B-NVFP4`，24.67GB，6 分片 |
| 量化 | `compressed-tensors`：部分层 FP8 W8A8，专家层 NVFP4 W4A4 |
| 服务 | `:9988`，`--language-model-only --enforce-eager --kv-cache-dtype fp8` |

**最终可复现启动命令**

```bash
export PATH=/home/grainuser/models/venv/bin:/home/grainuser/.local/bin:/usr/local/cuda/bin:$PATH
export MAX_JOBS=2
MOE_BACKEND=auto LINEAR_BACKEND=auto GPU_MEM_UTIL=0.42 \
MAX_MODEL_LEN=32768 MAX_BATCHED_TOKENS=8192 MAX_NUM_SEQS=1 \
bash /home/grainuser/hanson_selfheal/ops/start_qwen36_nvfp4.sh
```

**稳定性结果**

| 上下文 | 输入 tokens | 长上下文延迟 | 5 次 JSON 合法 | 2 路并发 | 结束时 MemAvailable | 结论 |
|---|---:|---:|---:|---|---:|---|
| 2K | 1,075 | 0.43s | 5/5 | 0.56/1.12s | 65.8GB | 通过 |
| 8K | 7,225 | 1.30s | 5/5 | 0.85/1.43s | 62.3GB | 通过 |
| 16K | 15,025 | 2.82s | 5/5 | 0.56/1.12s | 57.6GB | 通过 |
| 32K | 29,425 | 5.99s | 5/5 | 0.56/1.12s | 49.6GB | 通过 |

验证结果保存在 `data/selfheal/results/qwen36_nvfp4_validation_{2k,8k,16k,32k}.json`。

**踩坑与修复**

1. **PATH 缺 ninja**：FlashInfer JIT 报 `FileNotFoundError: ninja`。修复：启动前把 `/home/grainuser/models/venv/bin`、`~/.local/bin`、`/usr/local/cuda/bin` 加入 `PATH`。
2. **JIT 并行编译打爆内存**：默认 ninja 并行会同时拉起 7+ 个 `cicc`，单个可达 2-9GB，曾把可用内存压到 1.9GB。修复：`MAX_JOBS=1~2`；首次编译完成后 JIT 缓存可复用，后续启动不再触发大规模编译。
3. **Marlin 不兼容**：`--moe-backend marlin` 在 `ParallelLMHead` 上触发 `output_size_per_partition` 缺失，属于 vLLM 0.26 对该模型架构的 bug，不可用。
4. **CUTLASS 不支持当前设备**：`VLLM_CUTLASS` 报 `kernel does not support current device cuda`。
5. **Humming 不支持 GB10 NVML**：`nvmlDeviceGetMaxClockInfo` 返回 `NVMLError_NotSupported`，不可用。
6. **可用路径**：`auto` 选择 FlashInfer CUTLASS + `MAX_JOBS=2`；首次 JIT 约 30-40 分钟，之后启动约 3-4 分钟。

**OOM 看门狗**

- 脚本：`/home/grainuser/hanson_selfheal/ops/oom_watch.sh`
- 阈值：`MemAvailable < 4GB` 或 `SwapFree < 256MB 且 MemAvailable < 6GB` 时，向 35B 进程组发送 TERM，10 秒后 KILL。
- 实测：在 2K/0.20 预算的 KV cache 初始化阶段，可用内存从 22GB 跌到 5.4GB，看门狗在 3.9GB 时成功杀死 35B，服务器未死机；日志见 `data/selfheal/logs/oom_watch.log`。
- 只杀 35B 进程组，不触碰 NIII、GLM-OCR、Layout、adapter-v5、数据库与 MinIO。

**与现有路线的关系**

- 35B 与现有 GLM-OCR + Layout + Qwen3.5-9B 不能同时常驻：GLM-OCR `gpu 0.4` 约 48GB，9B 约 20GB，35B 32K 约 73GB，合计超过 119GB。
- 本次验证前已停止 GLM-OCR/Layout/9B，验证完成后已按基线参数恢复；9977/9978/9979/9991 全部 200，GLM-OCR 为 `seq12/gpu0.4`。
- 因此 Phase 0 的 35B 验证必须在维护窗口执行；生产切换前需要决定“35B 单模型”还是“9B 抽取 + 35B 审查/修复”的双模型分时方案。

**Phase 0 模型门禁结论**

- NVFP4 在 GB10 + vLLM 0.26.0 上可加载、可稳定输出 JSON、32K 不 OOM，满足 32K 上下文要求。
- 但 32K 下可用内存仅约 49.6GB，不能与现有 9B/GLM 同时运行；方案 1.4 中“4-bit 约 20GB、留 90GB”的估算偏乐观，应以实测 24.67GB 权重 + 32K 约 73GB 总占用为准。
- 35B 抽取质量 A/B 仍未执行；在完成 9B vs 35B 质量对比前，不应退役 9B。

---

## 2. 总体架构

```text
                    现有解析路线（保持不变）
PDF → OCR → TableGrid/IR → 抽取 → result/schema/evidence
                                      │
                                      │ 只读
                                      ▼
┌──────────────────────────── Self-Heal Route（新增） ────────────────────────────┐
│                                                                                  │
│  结果页 Feedback 面板 ──→ SelfHeal API ──→ Feedback Store                        │
│                                      │                                           │
│  自动审查器（35B，独立提示词） ──────┤                                           │
│                                      ▼                                           │
│                             统一 Finding Store                                    │
│                                      │                                           │
│                              归因 / 去重 / 优先级                                  │
│                                      ▼                                           │
│                              Repair Planner                                       │
│                    ┌─────────────────┼─────────────────┐                         │
│               L1 文档级修复      L2 配置/配方修复     L3 代码修复                  │
│                    │                 │                 │                         │
│                    └─────────────────┼─────────────────┘                         │
│                                      ▼                                           │
│                             Sandbox Runner（隔离目录）                            │
│                                      ▼                                           │
│                       Gate Evaluator（测试/回归/指标/回滚）                        │
│                                      ▼                                           │
│                       结果 diff / 对话回复 / 候选补丁                             │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 隔离设计（保证现有路线不受影响）

### 3.1 代码隔离

新增目录，现有模块只做“只读引用”：

```text
metal-doc-agent/metal_doc_agent/selfheal/
  __init__.py
  contracts.py          # Finding/Feedback/Repair/Gate 契约（新增，不改主 contracts）
  store.py              # SelfHeal 独立存储（SQLite/JSON）
  queue.py              # 独立文件队列
  worker.py             # 独立 worker 入口
  audit/
    packet.py           # 审计包构建
    auditor.py          # 35B 审查调用
  repair/
    planner.py          # 三级修复决策
    operators.py        # L2 算子注册表
    sandbox.py          # L1/L2 沙箱重跑
  codefix/
    agent.py            # L3 补丁生成（仅沙箱）
    gates.py            # 测试/回归/静态检查
  api.py                # SelfHeal FastAPI（独立端口）
```

Web 新增：

```text
apps/web/src/modules/selfheal/
  FeedbackPanel.tsx
  FeedbackThread.tsx
  RepairDiff.tsx
  api.ts
```

现有结果页只加一个受 feature flag 控制的挂载点，不改变原有渲染逻辑。

### 3.2 运行隔离

新增独立服务，不进入现有 compose 主链路：

- `selfheal-api`：独立端口，独立进程。
- `selfheal-worker`：独立队列、独立并发。
- 独立镜像 tag：`hanson-r1-selfheal:<release>`。
- 现有 `engine-api` / `worker-prod` / `worker-explore` 镜像和命令不变。

### 3.3 数据隔离

SelfHeal 使用独立数据库（P0 用 SQLite，后续可换 Postgres）：

```text
sh_feedback          用户反馈
sh_feedback_message  对话消息
sh_finding           统一问题
sh_repair_attempt    修复尝试
sh_gate_result       门禁结果
sh_candidate_recipe  候选配方
sh_code_patch        代码补丁提案
sh_audit_run         审查运行记录
```

现有平台表不新增字段、不改语义。

### 3.4 产物隔离

```text
data/selfheal/
  jobs/<selfheal_job_id>/
    before/            # 现有产物只读引用或复制
    sandbox/           # 修复后产物
    diff.json
    feedback.json
    findings.json
    gates.json
    reply.md
  overlays/<proposal_id>/configs/   # 配置覆盖副本
  patches/<patch_id>/                # 代码补丁 worktree
```

现有 `data/engine/jobs/<job_id>/` 只读，不写入。

### 3.5 配置隔离

- 生产 `configs/` 只读。
- L2 修复写入 `data/selfheal/overlays/<id>/configs/`。
- 沙箱运行通过 `METAL_DOC_HOME` 指向 overlay 根目录，读取覆盖配置。
- 只有通过门禁的候选配方才进入 `configs/selfheal/candidates/`，再由升级流程进入正式 `configs/`。

### 3.6 开关与零影响验证

- 环境变量 `SELFHEAL_ENABLED=0` 默认关闭。
- 关闭时：不注册路由、不启动 worker、不建表、不写任何文件。
- CI 增加“零影响测试”：
  1. 固定 5 份文档，`SELFHEAL_ENABLED=0` 跑现有 pipeline。
  2. 产物与 r7-95 基线逐文件 hash 对比。
  3. 全量 pytest 必须与改造前一致。

---

## 4. 统一数据契约

### 4.1 FeedbackItem

```text
feedback_id, doc_id, job_id, user_id, created_at
category: wrong_value | missing_value | extra_value | wrong_unit |
          wrong_requirement | wrong_table | duplicate | other
target: feature, record_id, property, table_id, page_no, row, col
description, expected_value, source_quote
attachments
status: open | processing | fixed | rejected | needs_more_info
priority: P0 (user) / P1 (audit)
```

### 4.2 Finding（统一问题）

```text
finding_id, doc_id, source: audit | user
verdict: correct | wrong | missing | extra | ambiguous | unverifiable
target, expected, observed
evidence: [{page_no, table_id, row, col, quote}]
rule_code, confidence, priority
status: open | accepted | rejected | fixed | quarantined
```

### 4.3 RepairProposal

```text
proposal_id, finding_ids
level: L1 | L2 | L3
operator: 白名单算子名
params: JSON
target_signature: 表型签名（L2）
status: proposed | sandbox | verified | applied | rolled_back | rejected
```

### 4.4 GateResult

```text
gate_id, proposal_id
checks: [
  {name: evidence_grounded, passed},
  {name: reproduction, passed},
  {name: target_metric, passed},
  {name: regression_50, passed},
  {name: regression_20, passed},
  {name: full_pytest, passed},
  {name: static_checks, passed},
  {name: canary, passed}
]
decision: accept | rollback | propose_only
```

---

## 5. 处理流程

### 5.1 用户反馈流程

```text
用户提交反馈
→ 校验目标存在、证据可定位
→ 生成 Finding（source=user, priority=P0）
→ 复现：
   1) 能定位到现有产物 → 进入修复规划
   2) 无法定位 → 标记 needs_more_info，回复用户补充
→ L1 文档级修复优先
→ 仍不满足 → L2 配方修复
→ 仍不满足且可复现 → L3 代码补丁
→ 回复：原因、修改、diff、影响范围、回滚方式
```

### 5.2 自动审查流程

```text
解析完成
→ 构建 Audit Packet（schema 行 + evidence + 原文单元格 + 条款）
→ 35B 审查（独立提示词）
→ Finding（source=audit, priority=P1）
→ 证据门禁：quote 必须匹配原文
→ 按类别/置信度采样进入修复规划
→ 高频问题优先升级为 L2 候选配方
```

### 5.3 统一归因与去重

- 同一 `doc_id + target + verdict` 合并。
- 用户反馈与自动审查冲突时，用户反馈优先，但必须复现。
- 用户反馈确认的 finding 自动生成 eval case。

---

## 6. 修复算子目录

### 6.1 L1 文档级修复（安全、立即生效）

- 重新解析指定表/整篇
- 指定表修复覆盖（表头合并/拆分）
- 指定列绑定覆盖
- 指定抽取器（bound/property/hardness/element/nonrecord）
- 指定文档画像/模板
- 只在 `data/selfheal/` 生成新产物，不写生产配置

### 6.2 L2 配置/配方修复（自动，门禁后生效）

白名单：

1. `column_alias.add`
2. `recipe.binding_override`
3. `table_repair.add`
4. `unit_normalize.add`
5. `property_map.add`
6. `extractor.enable`
7. `coverage_template.hint`

规则：

- 只允许改 `configs/` 下白名单文件。
- 必须绑定 `RecipeSignature`。
- 先 local → shadow → canary → global。
- 每次变更生成 `sh_candidate_recipe` 和 eval case。

### 6.3 L3 代码级修复（沙箱、默认只出提案）

允许范围：

- `metal_doc_agent/tablegrid/`
- `metal_doc_agent/extraction/`
- `metal_doc_agent/recipes/`
- `metal_doc_agent/schema_projection.py`
- `metal_doc_agent/validation/`
- `metal_doc_agent/selfheal/`
- `configs/`

禁止范围：

- `apps/api` 认证/安全
- `infra/`、Docker、`.env`
- 评测标签、黄金集、现有测试断言
- 依赖清单（新增依赖必须人工）

补丁限制：

- ≤ 5 个文件，≤ 200 行
- 必须包含一个回归测试
- 不允许网络访问、任意 shell、动态执行
- 必须能回滚

---

## 7. 自动门禁

任何修复必须通过：

1. **证据门禁**：finding 的 quote 能在原文/单元格匹配。
2. **复现门禁**：修复前先复现问题。
3. **目标指标**：错误/空字段/缺失项必须改善。
4. **回归门禁**：50 份高质量集、20 份历史集、5 份人工对照集不下降。
5. **错误门禁**：不新增 hard error，不新增 IR mismatch。
6. **迭代上限**：每份文档最多 3 次，超限 quarantine。
7. **L3 额外门禁**：
   - 全量 pytest 通过
   - 静态检查通过
   - diff 大小/文件白名单通过
   - shadow → canary 通过
   - 失败自动 revert

结论只有三种：`accept`、`rollback`、`propose_only`。

---

## 8. API 设计（新增，默认不注册）

```text
POST /v1/selfheal/feedback
GET  /v1/selfheal/feedback?doc_id=
GET  /v1/selfheal/feedback/{id}
POST /v1/selfheal/feedback/{id}/messages
POST /v1/selfheal/feedback/{id}/process
GET  /v1/selfheal/jobs/{id}
GET  /v1/selfheal/jobs/{id}/diff
GET  /v1/selfheal/proposals/{id}
POST /v1/selfheal/proposals/{id}/rollback
GET  /v1/selfheal/metrics
```

鉴权复用平台 token；SelfHeal 服务只信任平台内部调用。

---

## 9. Web 结果页

- 新增“问题反馈”按钮/面板（feature flag 控制）。
- 支持选择 schema 行/字段，自动带出定位与原文证据。
- 提交后显示处理进度、对话回复、修复 diff。
- 可查看“本次修复只影响当前文档 / 同类表型 / 全局”。
- 不改变现有结果页布局和交互。

---

## 10. 开发计划

### Phase 0：隔离骨架 + 单模型准入（不改行为）

交付：

- `metal_doc_agent/selfheal/` 包骨架
- `apps/selfheal` 独立 FastAPI + worker + 队列
- 独立 SQLite 表
- `SELFHEAL_ENABLED` 开关
- compose 新增 `selfheal-api` / `selfheal-worker`（默认不启动）
- Qwen3.6-35B-A3B-NVFP4 单模型部署与显存/延迟基准（已完成 2K/8K/16K/32K）
- 9B vs 35B 抽取 A/B（同一批 50 份、同一 OCR、同一 prompt）
- 35B 审查准入基准：注入错误集 + 正确文档误报集
- 零影响测试：flag off 产物 hash 对比

验收：

- 现有 574 个引擎测试、63 个平台测试、5 个 Web 测试全部通过
- flag off 时 5 份文档 stable 产物与 r7-95 基线规范化 SHA256 一致
- 现有容器镜像/命令不变
- 35B 抽取质量不低于 9B 的 95%，否则先 prompt/LoRA 适配
- 35B 审查达到召回率/误报率阈值
- GB10 上 Qwen3.6-35B-A3B-NVFP4 单模型 2K/8K/16K/32K 全部通过；32K 输入 29,425 tokens、延迟 5.99s、可用内存 49.6GB
- 35B 验证前后模型平面可恢复：9977/9978/9979/9991 全部 200，GLM-OCR 使用 seq12/gpu0.4

### Phase 1：用户反馈 + L1

交付：

- 反馈 API、存储、对话消息
- 结果页反馈面板
- L1 文档级重解析（复用已有 OCR 缓存）
- 新旧结果 diff 与回复
- `feedback.json`、`repair_diff.json`

验收：

- 反馈可提交、可处理、可查看 diff
- L1 修复不写生产配置、不改现有产物
- 失败自动回滚

### Phase 2：统一 Finding + 自动审查 + L2

交付：

- Audit Packet 构建
- 35B 审查调用（独立提示词）
- `findings.json`
- 证据门禁
- L2 算子注册表、overlay 沙箱、shadow/canary
- 候选配方存储与回滚

验收：

- 自动审查 finding 有原文证据
- 用户反馈与自动审查合并去重
- L2 修复只影响匹配签名
- 回归集指标不下降

### Phase 3：L3 代码修复流水线（单模型、能力达标后启用）

交付：

- 复现用例生成
- 隔离 worktree 补丁
- 静态检查、全量 pytest、回归集
- shadow/canary
- 自动合并/回滚（默认 proposal_only）
- `code_patch.json`

验收：

- 补丁只能在白名单文件内
- 任一测试失败自动丢弃
- `SELFHEAL_CODE_AGENT=off` 时不生成任何补丁
- L3 与抽取、审查共用同一个 Qwen3.6-35B-A3B 实例
- 默认不自动合并，除非显式开启 `SELFHEAL_AUTO_MERGE=1`
- 自动合并后有 canary 与回滚

### Phase 4：对话式体验与灰度

交付：

- 反馈线程、处理进度、diff 展示
- 指标面板
- 灰度与回滚开关
- 运行报告

验收：

- 用户可见完整闭环
- 自动化率、修复成功率、回滚率可观测
- 现有路线指标无变化

---

## 11. 测试计划

- 单元测试：契约、存储、队列、算子、门禁
- 集成测试：反馈 → Finding → 修复 → 沙箱 → diff
- 回归测试：50 份高质量集、20 份历史集、5 份人工对照集
- 零影响测试：flag off 产物 hash 对比
- 安全测试：路径穿越、禁用文件、超大 diff、任意代码执行、提示注入
- UI 测试：反馈面板、对话、diff
- 故障演练：模型超时、沙箱失败、回滚失败

---

## 12. 观测指标

- 审查 precision / recall
- 用户反馈解决率、平均迭代次数
- L1/L2/L3 修复分布
- 自动修复成功率、误修率、回滚率
- 回归集指标变化
- 单文档耗时与成本
- 候选配方命中率、升级成功率

---

## 13. 风险与回滚

| 风险 | 控制 |
|---|---|
| 现有路线被影响 | 独立服务、flag off、只读产物、零影响 hash 测试 |
| 模型幻觉 finding | 证据门禁 + 确定性校验优先 |
| 反馈错误导致误修 | 先复现；L1 优先；L2 签名隔离；L3 全量测试 |
| 代码自动改坏 | 沙箱 + 白名单 + diff 限制 + 全量测试 + canary + revert |
| 35B 与现有模型共存导致 OOM | 验证/运行前停 GLM-OCR/Layout/9B；OOM 看门狗；验证后按基线参数恢复 |
| FlashInfer JIT 编译内存峰值 | MAX_JOBS=1~2；预编译缓存；OOM 看门狗兜底 |
| L3 缺少版本控制可回滚 | 当前工作区无 `.git`；Phase 3 前必须补 Git 或采用文件快照回滚 |
| 成本失控 | 抽样审查、预算上限、最大迭代次数 |
| 数据污染 | 独立表、独立产物目录、生产配置只读 |

回滚方式：

1. `SELFHEAL_ENABLED=0`，停止 selfheal 服务。
2. 删除/忽略 `data/selfheal/`。
3. L2 配方回滚到上一版本。
4. L3 代码回滚：有 Git 时 revert commit；当前工作区无 `.git`，Phase 3 前需补版本控制或使用文件快照回滚。
5. 模型平面回滚：停止 35B，执行 `data/selfheal/ops/restore_current_models.sh`，确认 9977/9978/9979/9991 全部 200。
6. 现有解析路线无需任何操作。

---

## 14. 结论

这条路线与现有解析路线完全隔离，通过“统一 Finding + 三级修复 + 沙箱门禁”实现自动审查和用户反馈闭环。  
在不启用 `SELFHEAL_ENABLED` 时，现有系统行为、产物和性能不变；启用后，先跑 L1/L2，L3 代码修复默认只出提案，待门禁成熟后再开启自动合并。
