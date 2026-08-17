# LangExtractPkg 引擎收敛与官方特性利用（2026-08）

> 决策：抽取引擎收敛为 **LangExtractPkg（Google LangExtract 原包 1.6.0）**，
> 默认引擎即原包；BaseExtract 停用（代码保留作历史兜底，前端选项置灰）。

## 1. 为什么收敛

- 原包自带一整套官方特性：sentence-aware 分块、跨块共指窗口、batch×workers 并行、
  多轮抽取（first-pass-wins 按字符区间合并）、resolver 对齐（exact/fuzzy/lesser）；
- 旧实现（自行预切段 + 逐段调用原包）等于把这些特性全部禁用：
  分块退化为纯字符窗口、共指窗口关闭、多轮合并失效（段间字符区间断裂）、并行退化为逐段串行；
- 用户决策：不再使用 BaseExtract，直接使用 LangExtract，充分利用官方特性。

## 2. 官方特性利用清单（映射到实现）

| 官方特性 | 参数 | 当前实现（`lang_pkg_extractor.py`） |
|---|---|---|
| sentence-aware 分块 | `max_char_buffer`（默认 3000，受输入预算钳制） | 完整上下文一次交 `lx.extract`，原包 `ChunkIterator` 按句子/新行边界切块 |
| 跨块共指窗口 | `context_window_chars`（默认 500） | 传给原包，上一块尾部字符拼到当前块开头 |
| batch×workers 并行 | `batch_length` / `max_workers`（默认 8/8） | 原包内部分块并行，建议与 vLLM `--max-num-seqs` 一致 |
| 多轮抽取 | `passes`（默认 2） | 原包顺序多轮 + 按字符区间 first-pass-wins 合并 |
| 输出 Schema 约束 | `output_schema`（XGrammar） | 保留，与 `fence_output` 互斥时优先 Schema |
| resolver 对齐 | 原包默认（fuzzy 0.75 / lesser） | 解析结果保留 `_evidence`（字符区间 + 对齐状态） |
| few-shot 示例 | `max_examples`（3，实际 1 完整正例 + 1 拆条示例） | 保留 |
| 批量上下文 | `additional_context` | 暂不启用（指令已含 query 术语） |

## 3. 防超限/防截断策略

1. **不截断**：`context_assembler` 不按预算截断；`BaseExtract` 的 `context_truncate` 残留逻辑仅影响已停用引擎；
2. **单块预算**：`max_char_buffer ≤ input_char_budget(max_tokens) − prompt 固定开销 − context_window_chars`，
  其中 `input_char_budget = (窗口 55000 − max_tokens − 3000 保留) × 1.5 字符`；
3. **输出预算下调**：`max_tokens` 默认 8192（原 32768），输入预算自动放大，降低「输入+输出超窗口」的 400；
4. **不设任务级超时**：arq `job_timeout=None`；内部 `lx.extract` 不包超时——抽取时长取决于
   文档/上下文/输出长度，无法预估，贸然超时取消会误杀仍在抽取的任务（线程实际仍会跑完但结果被丢弃）；
   显式停止/关闭时由 `CancelledError` 处理将状态落 failed；
5. **段级失败即整体失败**：不静默丢数据。

## 4. 溯源证据

每条记录附带 `_evidence`：

```json
{"_evidence": {"span": [1234, 1246], "alignment": "match_exact"}}
```

- `span`：值在抽取上下文中的字符区间（原包 resolver 对齐结果）；
- `alignment`：`match_exact / match_greater / match_lesser / match_fuzzy`；
- 合并去重：按主键字段归一化（去空白、小写），同一主键保留对齐更精确/首次记录；
- 后续可对接前端「字段级复核/溯源」展示。

## 5. 配置与文件

- 默认引擎与参数：`backend/app/services/extraction_config_service.py`（`DEFAULT_GLOBAL_CONFIG.llm`）；
- 原包适配器：`backend/app/services/extraction/lang_pkg_extractor.py`；
- 前端：`frontend/src/views/kb/KbGlobalConfig.tsx`（BaseExtract 置灰、原包参数区）；
- 测试：`qa/functional/langpkg_full_features.py` → 结果 `qa/evaluation/results/langpkg_full_features/`。

## 6. 验证记录（GB-T1220-2007，2026-08-17）

- 结果：109 条记录（剔除 1），完整率 0.5321、可用率 0.9817、综合分 0.6423；
- 溯源：108/109 记录带 `_evidence`（span + alignment，99.1%）；
- 与旧「分段多次调用」对比：记录数一致、剔除 31→1、综合分 0.6234→0.6423；
- 耗时约 21 分钟（完整上下文 + passes=2 + 共指窗口的预期代价）；
- 全程无 400/上下文超限/截断；arq `job_timeout` 设为 7 天安全网，不按估算时间贸然停止任务。
