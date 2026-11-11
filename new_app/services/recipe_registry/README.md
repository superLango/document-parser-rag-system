# 配方注册中心

不可变配方包的存储、版本通道与确定性匹配服务。

## 职责

- 配方包校验与 digest 计算（`package.py`）。
- 版本存储、通道指针、晋升/回滚/弃用（`registry.py`）。
- 表格签名匹配，供编排 routing 阶段调用（`matcher.py`）。

## 包格式

```text
services/recipe_registry/data/recipes/<recipe_id>/<version>/manifest.json
services/recipe_registry/data/recipes/registry.json     # 通道指针与历史
services/recipe_registry/data/templates/<template_id>/<version>/template.json
```

`manifest.json` 关键字段：

| 字段 | 说明 |
|---|---|
| `schema_version` | 固定 `2.0` |
| `recipe_id` | 小写字母/数字/下划线 |
| `version` | 语义化版本 `x.y.z` |
| `engine_api` | 固定 `recipe-engine/1` |
| `profile` | 表型（chemical/mechanical/inspection/dimension/classification） |
| `signature` | 匹配签名（profile/orientation/n_cols/blocks/tokens/multi_header/unit_set） |
| `bindings` | 列绑定与行键规则 |
| `rules` | 解析规则 |
| `checksum` | 对 manifest（去掉 checksum/created_at）的 sha256 |
| `compatibility` | 旧状态、模板、词典等兼容信息 |

版本不可变：同 `recipe_id@version` 再次发布时，digest 不同返回 `RECIPE_VERSION_IMMUTABLE`。

## 通道

| 通道 | 用途 |
|---|---|
| `stable` | 生产解析 |
| `candidate` | 候选修复 |
| `shadow` | 影子验证 |
| `deprecated` | 只读保留 |

规则：

- 通道是指针，不是包属性；每个 `(channel, recipe_id)` 只指向一个版本。
- `promote` 原子切换并写 history；`rollback` 回到该通道上一版本。
- `deprecate` 从 stable/candidate/shadow 移除并写入 deprecated。
- run 创建时冻结版本（编排记录 recipe_id/version/digest）。

## API

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/internal/recipes` | 发布包 |
| GET | `/internal/recipes` | 配方列表与通道 |
| GET | `/internal/recipes/{recipe_id}` | 版本与通道 |
| GET | `/internal/recipes/{recipe_id}/versions/{version}` | manifest |
| POST | `/internal/recipes/resolve` | `{recipe_id, channel}` → 指针 |
| POST | `/internal/recipes/{recipe_id}/versions/{version}/promote` | 晋升 |
| POST | `/internal/recipes/{recipe_id}/rollback` | 回滚 |
| POST | `/internal/recipes/{recipe_id}/versions/{version}/deprecate` | 弃用 |
| POST | `/internal/recipes/match` | `{table}` → 匹配结果 |

错误码：`RECIPE_ID_INVALID`、`RECIPE_VERSION_INVALID`、`RECIPE_ENGINE_INCOMPATIBLE`、`RECIPE_CHECKSUM_MISMATCH`、`RECIPE_VERSION_IMMUTABLE`、`RECIPE_NOT_FOUND`、`RECIPE_NOT_RESOLVED`、`RECIPE_ALREADY_PROMOTED`、`RECIPE_ROLLBACK_UNAVAILABLE`、`RECIPE_CHANNEL_INVALID`、`RECIPE_ACTOR_REQUIRED`。

## 匹配

`signature_score` 复刻旧实现：

```text
profile 必须一致
基础 0.5 + 方向 0.15 + 列数 0.1/0.05 + 块数 0.05
+ 0.2 × (0.5 × Jaccard + 0.5 × overlap)
```

阈值：`exact ≥ 0.9`、`candidate ≥ 0.6`，否则 `unknown`。

## 迁移

```bash
cd new_app
python scripts/migrate_recipes/migrate.py
```

- 旧 `configs/recipes/*.json` → 7 个配方包，`version=1.0.0`，`active → stable`。
- 旧 `configs/schema_templates/product_standard.json` → `templates/product_full/1.0.0`。
- 重复执行幂等。

## 测试

```bash
cd new_app
python -m pytest tests/contract -q
python scripts/benchmark/route_parity.py
bash scripts/dev/recipe-check.sh
```
