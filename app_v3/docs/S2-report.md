# app_v3 S2 阶段报告（验证器 / 牌号修复 / 固定评测）

> 阶段：P0-S2  
> 日期：2026-11-25  
> 状态：**S2 基础设施完成，P0 指标未达标**（验证器与修复需继续调优）  
> 约束：未修改冻结版 v2 代码；只新增 `app_v3/` 代码与报告。

## 1. 目标与完成情况

| 目标 | 交付 | 状态 |
|---|---|---|
| 证据验证 | `verify/evidence.py`（表/页引用、越界、条款引文） | ✅ |
| 值守恒 | `verify/conservation.py`（记录值必须出现在来源行） | ✅ |
| 条件完整性 | `verify/conditions.py`（温度/单位/类别-温度冲突） | ✅ |
| 冲突检测 | `verify/conflicts.py`（同键不同值/重复） | ✅ |
| 未解决队列 | `verify/queue.py`（原因码/建议/证据） | ✅ |
| 验证流水线 | `verify/pipeline.py`（CLI + 汇总） | ✅ |
| 牌号列分析 | `analyze/grade_columns.py` | ✅ |
| 文档级牌号推断 | `analyze/document_grade.py` | ✅ |
| 牌号修复 | `analyze/repair.py`（默认保守模式） | ✅ |
| 固定评测入口 | `eval/matcher.py`（v5 matcher 迁入）+ `eval/run_eval.py` | ✅ |
| 回归测试 | `tests/`（S1+S2） | ✅ 34 passed |

## 2. 评测器校准（关键）

`app_v3/eval/matcher.py` 迁入冻结版 v5 matcher；用 20 份基准产物回放：

| 指标 | 基线（冻结 v2） | app_v3 eval 回放 | 一致性 |
|---|---:|---:|---|
| 匹配 | 6672 | 6672 | ✅ |
| 金标 | 9724 | 9724 | ✅ |
| 一致率 | 0.7899 | 0.7899 | ✅ |
| 覆盖率 | 68.61% | 68.61% | ✅ |

→ **评测入口与冻结基线严格一致**，后续优化可直接对比。

## 3. S2 牌号修复评测

### 3.1 保守模式（默认）
策略：
- 表格牌号修复默认关闭（避免引入新错误）；
- 文档级牌号仅在"英文文档 + 唯一合金牌号 + 出现≥2 次 + 非 Grade N"时应用；
- 中文文档不做文档级强修。

结果：

| 指标 | 基线 | 保守修复后 | 变化 |
|---|---:|---:|---:|
| 匹配 | 6672 | **6698** | **+26** |
| 一致率 | 0.7899 | 0.7890 | -0.0009 |
| 覆盖率 | 68.61% | **68.88%** | +0.27pp |
| 缺失 | 3052 | 3026 | -26 |
| 多余 | 2513 | 2487 | -26 |

主要收益：**ISO 5832-3 从 0% → 26 条匹配**（文档级唯一牌号 `Ti-6Al-4V` 修复）。

### 3.2 激进模式（不采用）
同时开启表格牌号修复 + 文档级修复：
- 匹配 6642 / 9724，覆盖率 68.31%，**较基线下降**；
- ASME（219→209）、ASTM（247→201）明显退化：表内 UNS/Grade 列与金标牌号体系不一致，直接把表内值覆盖 grade 会引入错误。

结论：**牌号修复必须走"候选 + 验证/保守策略"，不能无脑覆盖**；这一结论来自评测，而不是人工猜测。

## 4. 验证器运行结果（20 份 v2 产物）

| 指标 | 数值 |
|---|---:|
| 记录 | 9185 |
| verify status ok | 6829 |
| warn | 812 |
| unresolved | **1544** |
| 未解决队列 | **2356** |
| 诊断 | `value_conflict: 1544`、`missing_temperature: 1485`、`metadata_evidence_missing: 5`、`missing_unit: 4` |

说明：
- `value_conflict` 高，主要因为**条件缺失/条件未区分**导致同一"类别+项目+牌号+条件"键下出现多个值；验证器按保守规则标记，宁可从队列复核，不静默选一个；
- `missing_temperature` 高，说明上游绑定/展开仍缺温度条件（S3 需在条件绑定层修复，而不是在验证器放宽）；
- 未解决队列已落盘：`extract/s2/verification.json`、`extract/s2/repaired.json`。

## 5. 新增/变更文件

```
app_v3/
├── analyze/
│   ├── grade_columns.py
│   ├── document_grade.py
│   └── repair.py
├── verify/
│   ├── evidence.py
│   ├── conservation.py
│   ├── conditions.py
│   ├── conflicts.py
│   ├── queue.py
│   └── pipeline.py
├── eval/
│   ├── matcher.py          # v5 matcher 迁入
│   ├── run_eval.py         # 固定评测入口
│   └── s2-baseline-eval.json / s2-repaired-eval.json
├── scripts/s2_demo.py
├── tests/test_analyze.py / test_verify.py
└── docs/S2-report.md
```

## 6. 已知限制与下一步（S3）

1. **条件完整性仍是最大缺口**：`missing_temperature=1485`；需要从"列头/条件行/表标题"生成条件，而不是在验证器放宽；
2. **牌号体系差异**：表内 UNS/Grade 与金标常用牌号不一致；需要"标准体系词表 + 别名匹配"，不能直接覆盖；
3. **value_conflict 误报**：缺少条件时同键冲突过多；S3 先修复条件再收紧冲突规则；
4. **验证器精度**：1544 unresolved 需要抽检，区分"真错误/缺条件/上游误判"；
5. P0 退出指标尚未达到（一致率 0.90、覆盖率 70%），需 S3 继续。

## 7. S3 建议

- 条件补充：表格列路径/条件行/表标题 → 试验温度/状态/尺寸；
- 牌号：标准体系词表（UNS↔常用牌号、Grade↔材料）与别名匹配；
- 冲突规则分级：缺少条件时降为 `info`，不直接 unresolved；
- 评测盲测集固定，继续以 20 份 + 盲测验证。
