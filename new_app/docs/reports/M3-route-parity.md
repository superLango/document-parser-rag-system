# M3 路由一致率报告

> 版本：v1.0  
> 日期：2026-11-11  
> 结论：新 matcher 与旧 matcher 在 5 个金标表格上 100% 一致

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
- 扩充语料后继续用同一脚本回归；当前基线为 5 例 100%。
