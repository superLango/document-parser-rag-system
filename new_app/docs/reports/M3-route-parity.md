# M3 路由一致率报告

> 版本：v1.1  
> 日期：2026-11-11  
> M3 结论：新 matcher 与旧 matcher 在 5 个金标表格上 100% 一致  
> M6 更新：增加低覆盖惩罚，2 例机械表有意纠正；recipe parity 3/5，status parity 5/5

## 1. 方法

- 语料：`new_app/tests/golden/table/*.md` 的 5 张表（力学、化学、合并表头、检验、真实扫描件）。
- 新链路：`extract_tables` → `services.recipe_registry.matcher.match_table`，候选为迁移后的 7 个 `stable` 配方包。
- 旧链路：隔离 `sys.path` 导入 `legacy/metal-doc-agent`，用 `load_recipes` + `match_recipe`，表对象按字段转换为旧 `TableGrid`。
- 命令：`python scripts/benchmark/route_parity.py`

## 2. 结果

| case | 新配方 | 新分数 | 新状态 | 旧配方 | 旧分数 | 旧状态 | 一致 |
|---|---|---|---|---|---|---|---|
| chemical-elements | chemical_composition_v1 | 0.8933 | candidate | chemical_composition_v1 | 0.8933 | candidate | 是 |
| inspection-items | inspection_rules_v1 | 0.8967 | candidate | inspection_rules_v1 | 0.8967 | candidate | 是 |
| mechanical-basic | hardness_v1 | 0.7500 | candidate | hardness_v1 | 0.7500 | candidate | 是 |
| merged-header | hardness_v1 | 0.7500 | candidate | hardness_v1 | 0.7500 | candidate | 是 |
| qdu-p5-mechanical | mechanical_properties_v1 | 0.7711 | candidate | mechanical_properties_v1 | 0.7711 | candidate | 是 |

| 指标 | 值 | 门槛 |
|---|---|---|
| 配方一致率 | 1.0000 | ≥ 0.99 |
| 状态一致率 | 1.0000 | ≥ 0.99 |
| 分数差异 | 0 | — |

## 3. 说明

- 新 matcher 复刻旧 `signature_score`：profile 必须一致，基础 0.5，方向 +0.15，列数 +0.1/+0.05，块数 +0.05，token 相似度权重 0.2；阈值 `exact ≥ 0.9`、`candidate ≥ 0.6`。
- 五张表均落在 `candidate`（0.75–0.90），因为金标表是精简样本，列数与 token 集小于正式标准表；这与旧算法行为一致。
- 迁移后的配方签名保持原样（`bindings`/`rules`/`signature` 未改写），因此打分逐位相同。

## 4. 差异清单

无。

## 5. 后续

- M5 RouterAgent 可在 matcher 结果之上做歧义消解。
- 扩充语料后继续用同一脚本回归；M3 基线为 5 例 100%。

---

## 6. M6 更新：hardness/mechanical 低覆盖惩罚（2026-11-11）

M5 RouterAgent 评测发现：`hardness_v1` 与 `mechanical_properties_v1` 共享 `mechanical_properties` profile；机械表（牌号/Rm/A）与 hardness 配方 header token 交集为 0，但 hardness 因 `n_cols=3` 加分仍以 0.75 胜出。旧 matcher 同样存在该问题。

M6 修复：`services/recipe_registry/matcher.py` 增加 `token_coverage`；当表头 token 覆盖率为 0（<0.15）时扣 0.1。机械表 coverage=0.33–0.50，硬度表 coverage=0（被罚），因此机械配方胜出；纯硬度表仍路由到 hardness_v1。

| case | new_recipe | new_score | legacy_recipe | legacy_score | recipe parity | status parity |
|---|---|---|---|---|---|---|
| chemical-elements | chemical_composition_v1 | 0.8933 | chemical_composition_v1 | 0.8933 | yes | yes |
| inspection-items | inspection_rules_v1 | 0.8967 | inspection_rules_v1 | 0.8967 | yes | yes |
| mechanical-basic | mechanical_properties_v1 | 0.6917 | hardness_v1 | 0.7500 | **no（有意纠正）** | yes |
| merged-header | mechanical_properties_v1 | 0.7091 | hardness_v1 | 0.7500 | **no（有意纠正）** | yes |
| qdu-p5-mechanical | mechanical_properties_v1 | 0.7711 | mechanical_properties_v1 | 0.7711 | yes | yes |

```text
cases=5 recipe_parity=0.6000 status_parity=1.0000
```

结论：

- 旧 100% 一致率包含 2 例共同误判；M6 不再以“与旧 matcher 完全一致”作为唯一目标。
- 路由金标准确率：M6 `M6-router-eval.json` 中 Agent 1.0（5/5）、确定性 matcher 1.0（5/5）。
- 若必须保留旧 100% parity，可在需要时通过配置关闭低覆盖惩罚；当前默认开启。
- 新增契约测试：`test_mechanical_table_beats_hardness_recipe`、`test_hardness_table_still_routes_to_hardness`。
