# app_v3 S6 阶段报告（P1 DSL 执行器 / 未解决队列审计）

> 阶段：P0 收尾 + P1 WP1.2  
> 日期：2026-11-25  
> 状态：**DSL 执行器完成并通过真实表验证；P0 指标仍未达标**  
> 约束：未修改冻结版 v2 代码；只新增/调整 `app_v3/`。

## 1. 完成情况

| 目标 | 交付 | 状态 |
|---|---|---|
| P1 WP1.2 DSL 执行器 | `table_program/engine.py`（melt/explode/pivot/filter） | ✅ |
| 回放校验 | `table_program/replay.py`（值覆盖/缺失/多余） | ✅ |
| 真实表验证 | gbt-2054 T9：209 条记录，回放 **coverage=1.0** | ✅ |
| 未解决队列审计 | `verify/audit.py` + `scripts/s6_audit.py` | ✅ |
| 盲测清单占位 | `eval/blind_manifest.json`（待新增文档） | ✅ |
| 单元测试 | **47 passed** | ✅ |

## 2. P1 DSL 真实表验证（gbt-2054 T9）

程序：
- `explode` 牌号列（多牌号拆分）；
- `melt` 抗拉强度/Rp0.2/断后伸长率/HV/HRB 五列；
- 条件：室温拉伸三列带 `试验温度=室温`，硬度列单独。

结果：
- 记录 **209** 条；
- 回放校验：`ok=True`，**coverage=1.0**（无遗漏值单元格）。

说明：执行器/回放已在真实 OCR 表上跑通，可作为 P1 的确定性执行基础。

## 3. 未解决队列审计（20 份）

| 原因 | 数量 |
|---|---:|
| missing_temperature | **1323** |
| value_conflict（跨行/跨表） | **820** |
| same_row_value_conflict（降级 warn） | 558 |
| metadata_evidence_missing | 5 |
| missing_unit | 4 |
| value_conflict_insufficient_conditions | 3 |
| **队列合计** | **2161** |

队列最多的文档：
- gbt-3077-2015（446）、gjb-2351a-2021（362）、gjb-1951a-2020（325）、astm-b348-25（288）、asme-sb338-2025（205）。

**结论**：
- `missing_temperature` 仍是最大来源（1323），但条件补全只能补表头/标题明确的温度；剩余需**表/标准级温度默认策略**或条款通道；
- `value_conflict` 820 为跨行/跨表真实冲突候选，需抽检；
- `same_row_value_conflict` 558 已降级为 warn（不阻塞），保留复核。

## 4. 评测（20 份回归集，未变化）

| 指标 | 冻结基线 | S2 | S3 | S4 | S5 | **S6** |
|---|---:|---:|---:|---:|---:|---:|
| 匹配 | 6672 | 6698 | 6698 | 6698 | 6698 | **6698** |
| 一致率 | 0.7899 | 0.7890 | 0.7952 | 0.7944 | 0.7944 | **0.7944** |
| 覆盖率 | 68.61% | 68.88% | 68.88% | 68.88% | 68.88% | **68.88%** |

## 5. P0 退出检查

| 指标 | 目标 | 当前 | 结论 |
|---|---:|---:|---|
| 一致率 | ≥0.90 | 0.7944 | ❌ |
| 覆盖率 | ≥70% | 68.88% | ❌ |
| 多余 | <1000 | 2487 | ❌ |
| 未解决率 | ≤10% | 8.9% | ✅ |

P0 未退出；S7 继续 P0 收尾。

## 6. 新增/变更文件

```
app_v3/
├── table_program/engine.py          # DSL 执行器
├── table_program/replay.py          # 回放校验
├── verify/audit.py                  # 队列审计
├── scripts/s6_audit.py
├── scripts/s6_dsl_demo.py
├── tests/test_table_program.py
├── eval/blind_manifest.json         # 盲测占位
├── eval/s6-audit.json
├── eval/s6-dsl-demo.json
├── docs/S6-audit.md
└── docs/S6-report.md
```

## 7. S7 计划

1. **P0 收尾（重点）**：
   - 表/标准级温度默认（只在可证明的表类型/栏目上使用，避免新的猜测）；
   - 条款通道：高倍/弯曲/热处理（当前高倍缺口 149）；
   - 820 条 value_conflict 抽检与规则精化；
2. **P1 应用**：用 DSL 执行器覆盖化学宽表/冲击/硬度表，验证回放后再进入评测；
3. **盲测**：新增 10–20 份未见文档填充 `blind_manifest.json`。
