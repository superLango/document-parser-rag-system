# 解析算法资产化与热更新方案

> 日期：2026-11-12
> 状态：待确认
> 目标：把配方、矩阵策略、规则、解析代码统一为可版本化资产；agent 修改后热更新生效，无需重建镜像；并打通“审核 → 修复 → 用户验收 → 回归 → 晋升 stable”的完整闭环。

## 1. 目标与边界

### 1.1 目标

1. 解析相关的一切（配方 JSON、矩阵策略代码、表修复规则、别名/词典）由**一个资产服务**统一管理版本、通道、校验和与回滚。
2. 沙箱每次 run 从资产服务解析 stable 版本并注入工作区，**改完下一次 run 即生效**，不重建引擎镜像。
3. agent 可修改资产：先生成 candidate，沙箱重跑目标文档 + 回归集，用户验收后晋升 stable。
4. 用户反馈可以针对任意内容（不限于第一次修改），agent 在当前 candidate 上做**增量补丁**，不推倒重来。
5. 已验收的结果区域锁定，二次补丁不得静默改动；所有晋升可审计、可回滚。

### 1.2 非目标 / 边界

- 不改变 7 个业务微服务边界：资产服务由 `recipe-registry` 扩展，不新增第 8 个业务服务；`layout_api`/GLM 等外部模型服务不计入业务服务数量（D-017）。
- 新增第三方 Python 依赖仍需要重建引擎镜像（运行时依赖固定）。
- K8s 工作区 800KB 限制保持不变；本方案只注入约 60–100KB 的解析代码。
- 用户验收 ≠ 代码可全量上线；stable 晋升必须过回归门禁，且默认需要人工二次确认。

## 2. 总体架构

```text
                    ┌──────────────────────────────────────────┐
                    │ algorithm-registry（扩展 recipe-registry）│
                    │  assets: recipe / parser / rules          │
                    │  versions: 不可变 + checksum + history    │
                    │  channels: stable / candidate / shadow    │
                    └───────────▲──────────────▲───────────────┘
                                │ resolve      │ publish / promote
                                │ stable       │ candidate
┌───────────────┐     ┌─────────┴────────┐  ┌──┴──────────────┐
│ api-gateway   │────▶│ orchestration    │  │ agent           │
└───────────────┘     └─────────┬────────┘  │ triage/repair   │
                                │           │ code-fix 提案    │
                                ▼           └──┬──────────────┘
                    ┌───────────────────────┐  │
                    │ sandbox service       │◀─┘ 沙箱验证 candidate
                    │ workspace:            │
                    │  /work/engine/  ← 代码资产（只读）
                    │  /work/recipes/ ← 配方资产（已有）
                    │  /work/input/   ← OCR/请求
                    └──────────┬────────────┘
                               ▼
                    ┌──────────────────────┐
                    │ engine container     │
                    │ sys.path: /work/engine 优先
                    │ fallback: /engine（镜像内置）
                    └──────────────────────┘

                    ┌──────────────────────┐
                    │ review + feedback    │
                    │ 文档级门禁/自动反馈   │
                    └──────────────────────┘
```

关键原则：

- 资产服务只负责“发资产”，不负责执行；执行由 sandbox（正式）或 agent（预览/测试）负责。
- 引擎镜像保留一份内置代码作为兜底；工作区 bundle 缺失时回退 `/engine`。
- 每次 run 把资产版本与 digest 写入 `manifest.json`，结果可复现、可追溯。

## 3. 资产模型

### 3.1 资产类型

| 类型 | 内容 | 运行位置 | 示例 |
|---|---|---|---|
| `recipe` | 配方 manifest：bindings、strategy_chain、rules | 沙箱 | `mechanical_properties_v1` |
| `parser` | 解析代码包：`builtin.py`、`strategies.py` 等 | 沙箱 | `parser_core` |
| `rules` | 表修复/别名/词典 JSON | OCR 或沙箱 | `table_repairs`、`column_aliases` |

三类资产共用同一套版本、通道、checksum、回滚与审计机制。

### 3.2 版本与通道

- 版本不可变（semver），发布后不可覆盖；修订必须发新版本。
- 通道指针：`stable`（生产）、`candidate`（验证中）、`shadow`（灰度）、`deprecated`（回滚保留）。
- 每个 `(kind, asset_id, channel)` 只指向一个版本；晋升/回滚只改指针，不动包内容。
- `history` 记录 actor、from/to version、digest、原因，便于审计。

### 3.3 parser bundle 清单

```json
{
  "schema_version": "1.0",
  "bundle_id": "parser_core",
  "version": "1.0.0",
  "runtime_api": "sandbox-engine/1",
  "python": "3.12",
  "stdlib_only": true,
  "entry_modules": ["builtin", "strategies"],
  "files": [
    {"path": "builtin.py", "sha256": "..."},
    {"path": "strategies.py", "sha256": "..."}
  ],
  "tests": ["test_strategy_chain.py"],
  "checksum": "...",
  "created_at": "2026-11-12T00:00:00+00:00"
}
```

- 只允许 `.py`、`.json`，禁止二进制与符号链接。
- 文件总大小上限 1 MB；超过需人工评审。
- checksum 覆盖全部文件内容 + 清单（去掉 checksum/created_at 字段）。

### 3.4 资产 API（registry）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/internal/assets/{kind}/{id}` | 资产详情与通道 |
| GET | `/internal/assets/{kind}/{id}/versions/{version}` | 取指定版本（含文件内容或下载地址） |
| POST | `/internal/assets/resolve` | `{kind,id,channel}` → `{version,digest}` |
| POST | `/internal/assets/{kind}/{id}/versions` | 发布 candidate（不可变） |
| POST | `/internal/assets/{kind}/{id}/promote` | candidate → shadow → stable |
| POST | `/internal/assets/{kind}/{id}/rollback` | 回滚到指定版本 |
| GET | `/internal/assets/{kind}/{id}/history` | 变更历史 |

## 4. 热更新机制

### 4.1 沙箱注入

1. orchestration 发起 run 时，workspace 同时解析 `recipe` 与 `parser` 的 stable 版本。
2. workspace 写入：
   - `/work/recipes/<id>/...`（已有）
   - `/work/engine/<bundle>/...`（新增，文件权限 0444）
   - `/work/engine/manifest.json`（bundle 清单 + digest）
3. 请求与 run `manifest.json` 增加：

```json
"assets": {
  "recipe":  {"id": "mechanical_properties_v1", "version": "1.3.0", "digest": "..."},
  "parser":  {"id": "parser_core", "version": "1.0.3", "digest": "..."},
  "rules":   {"id": "table_repairs", "version": "1.1.0", "digest": "..."}
}
```

### 4.2 引擎加载

- `runner.py` 启动顺序：
  1. `sys.path.insert(0, "/work/engine")`；
  2. 尝试 `import builtin` / `import strategies`；
  3. 失败或不存在 → 回退镜像内置 `/engine`；
  4. 把实际使用的 bundle digest 写入输出 `manifest.json`。
- 环境变量保持 `PYTHONDONTWRITEBYTECODE=1`，避免只读目录写 `.pyc`。
- 代码仍运行在无网络、非 root、只读根文件系统、限 CPU/内存的隔离容器内。

### 4.3 沙箱外运行（预览/测试）

- agent 预览、CI 回归通过同一资产 API 拉取同一版本，在受限子进程执行（无网络、超时、只读工作目录）。
- 正式结果仍以沙箱执行为准；沙箱外只用于快速验证与 diff。

## 5. 审核-修复闭环

### 5.1 两级闸门

| 闸门 | 决策人 | 解锁内容 |
|---|---|---|
| 结果验收 | 用户 | 该文档结果可用；candidate 进入 shadow/晋升候选 |
| 代码晋升 | 自动门禁 + 人工（L3） | candidate → stable，全量生效 |

用户验收是必要条件，不是充分条件；stable 晋升必须过回归。

### 5.2 闭环流程

```text
Run（stable 资产）
  → 解析 → review
      ├─ 通过 → 交付
      └─ 不通过 → 自动 feedback（文档/表/字段级）
            ↓
      agent triage：L1 重解析 / L2 配方规则 / L3 解析代码
            ↓
      candidate 补丁（基线 = 当前 candidate，不是 stable）
            ↓
      沙箱重跑：目标文档 + 回归集
            ↓
      产出 diff：记录 diff / 代码 diff / 回归报告
            ↓
      用户审核
        ├─ 反馈 → 增量补丁（已验收区域锁定）→ 重跑 → 合并 diff → 再审核
        └─ 验收 → candidate 通过
              ↓
      shadow（灰度）→ 回归门禁 → stable
              ↓
      用例固化为回归 fixture；bundle digest 更新
              ↓
      下一份文件 run 时解析到新 stable，直接走新代码
```

### 5.3 分层修复

| 层级 | 修改内容 | 是否需要镜像 | 验证 |
|---|---|---|---|
| L1 | 重新解析、版面/表格修复规则 | 否 | 目标文档 diff |
| L2 | 配方 bindings/strategy_chain/别名 | 否 | 目标表 + 回归 |
| L3 | 解析代码（parser bundle） | 否（本方案） | 单测 + 目标文档 + 回归 + 代码评审 |

L3 已确认：**补丁自动进入 candidate**，不要求人工做代码 diff 合并；用户只审核最终解析结果。代码 diff 仍保留在审计记录中，供后续追溯与回滚。

### 5.4 增量补丁与合并

- 每次 feedback 生成一个 `patch`，挂在当前 candidate 的 `patch_chain` 上，保留顺序与来源 feedback id。
- 第二次反馈的处理：
  1. 以当前 candidate 为基线生成新 patch；
  2. 重跑目标文档 + 回归；
  3. 与 `accepted_snapshot` 对比：已验收的表/字段/记录若发生变化，**必须提示用户重新确认**；
  4. 未变化区域自动合并，输出合并后的 diff。
- `accepted_snapshot` 记录：run_id、records digest、已验收 table_id/field 列表、用户与时间。

### 5.5 晋升与回滚

1. candidate 通过目标文档 + 回归集 + 金标 → 进入 shadow。
2. shadow 按文档队列或比例灰度，不影响全量。
3. shadow 无回退 → 默认 `ready`，**等待人工 promote 或 abandon**；失败一键 rollback 到上一版本。
4. 每次晋升写入 `history`，包含来源 feedback、patch_chain、回归报告 digest。

已确认（方案 B，2026-11-12 修订）：**回归通过后默认停在 ready，需要人工二次确认**；仅当显式设置 `SHADOW_AUTO_PROMOTE=true` 时才自动晋升 stable。用户 approve 是进入 shadow 的必要条件，AI 修复不能直接改 stable。

### 5.6 Shadow 运行与已验收快照

**Shadow 是什么**：candidate 不直接替换线上版本，而是先在限定范围内验证。对本项目（文档批处理）采用 **双跑对比**：

- 同一文档同时用 stable 与 candidate 各解析一次；
- 对外只交付 stable 的结果，candidate 结果只用于内部质量对比；
- **连续 10 份文档无回退 → 默认 ready，等待人工确认**；仅 `SHADOW_AUTO_PROMOTE=true` 时自动晋升；
- 批次带超时（默认 7 天），超时置 `expired` 并让反馈回到 verified；
- 人工出口：`POST /v1/shadow/batches/{id}/promote` 强制晋升、`.../abandon` 放弃灰度。

灰度范围（已确认）：**指定文档集 + 双跑对比**。candidate 只跑指定文档集，其余文档继续走 stable。

**已验收快照是什么**：用户确认某份文档结果后，保存该次结果的指纹（records digest、已验收的 table_id/字段、run_id、文档版本）。后续补丁重跑同一文档时，用它判断“之前确认过的内容有没有被悄悄改动”。

已确认策略：

1. **永久保留**：快照作为审计与回归 fixture 长期保存。
2. **文档版本变化继续沿用**：同一文档重新上传后，旧快照仍作为已验收基线使用；如果新版本内容导致问题，由 review 门禁拦截或用户反馈发现，不依赖快照自动失效。

## 6. 质量门禁与回归体系

### 6.1 文档级门禁（review 前）

| 规则 | 触发 | 动作 |
|---|---|---|
| `DOC-NO-RECORDS` | records=0 且 tables>0 | 自动 feedback（L1/L2） |
| `DOC-NO-TABLES` | tables=0 且 pages≥N | 自动 feedback（OCR/L1） |
| `DOC-UNBOUND-COLUMNS` | `MEASURE_COLUMN_MISSING` 比例高 | L2 配方补丁 |
| `DOC-DUP-KEYS` | 同牌号同指标重复超阈值 | L2 条件维度补丁 |
| `DOC-UNIT-MISSING` | 数值无单位比例超阈值 | L2 单位绑定补丁 |
| `DOC-LOW-COVERAGE` | 可解析表覆盖不足 | L2/L3 |

### 6.2 回归集

| 集合 | 内容 | 门禁 |
|---|---|---|
| 标准集 | 50 份代表性标准 | 有记录文档数、字段命中、静默错误不得回退 |
| 金标集 | GB/T 1591、GB/T 33084 等 | Field F1、值命中 |
| 已验收用例 | 用户确认过的文档结果快照 | 记录与字段不得变化 |

### 6.3 通用性约束（L3 必查）

- 禁止按文档 ID/文件名/固定值硬编码；静态扫描 + 测试用例双检查。
- 只允许标准库；禁止网络访问、文件系统越界。
- 单文件/单次补丁行数上限；超限转人工评审。
- 必须有对应单元测试；无测试的补丁不得进入 candidate。

## 7. 数据模型补充

### 7.1 运行清单（manifest.json）

```json
{
  "engine": {
    "api": "sandbox-engine/1",
    "image": "hanson-sandbox-runtime:local",
    "image_digest": "sha256:...",
    "assets": {
      "parser": {"id": "parser_core", "version": "1.0.3", "digest": "..."},
      "recipe": {"id": "mechanical_properties_v1", "version": "1.3.0", "digest": "..."}
    }
  }
}
```

### 7.2 反馈与验证

```json
{
  "feedback_id": "...",
  "run_id": "...",
  "target": {"document_id": "...", "table_id": "T3", "field": "Rm"},
  "level": "L2",
  "candidate": {
    "asset": {"kind": "parser", "id": "parser_core", "version": "1.0.4"},
    "patch_chain": ["patch-001", "patch-002"],
    "base_version": "1.0.3"
  },
  "accepted_snapshot": {
    "run_id": "...",
    "records_digest": "...",
    "accepted_tables": ["T3"],
    "accepted_fields": ["T3.Rm", "T3.Rp0.2"]
  },
  "verification": {
    "target_ok": true,
    "regression_ok": true,
    "regression_report": "runs/.../regression.json",
    "changed_in_accepted": []
  }
}
```

## 8. 分阶段实施

### P1：资产服务 + 热加载（M）

- recipe-registry 增加 `parser` / `rules` 资产类型、API、通道与 checksum。
- workspace 注入 `/work/engine`；runner 优先加载工作区代码并记录 digest。
- 迁移现有 `builtin.py` / `strategies.py` 为 `parser_core@1.0.0`。
- 验收：改一处策略代码 → 发布 candidate → 沙箱 run 使用新代码，无需重建镜像；B338 两份回归不退化。

**P1 执行结果（2026-11-12）：**

- 新增 `services/recipe_registry/assets.py`：`parser` / `rules` 资产模型、不可变版本、通道指针、checksum、历史与回滚；API 增加 `/internal/assets`（list/publish/resolve/detail/promote/rollback/history）。
- 已发布 `parser/parser_core@1.0.0` 并指向 stable；发布脚本：`scripts/assets/seed_parser_asset.py`（种子）与 `publish_parser_asset.py`（走 registry API）。
- 沙箱 workspace：
  - 每次 run 解析 stable parser 资产，校验文件 sha256 与 bundle checksum，写入 `/work/engine`（0444/0555）；
  - 资产不可用时回退引擎镜像内置代码，并在 `manifest.json` 记录 `assets.parser.source=image`；
  - Docker / K8s 执行器均注入 `HANSON_ENGINE_DIR` 与 `HANSON_ENGINE_ASSETS`。
- 引擎 runner：优先 `sys.path` 加载 `/work/engine`，回退 `/engine`；新增 `ENGINE_ASSETS` 诊断（含实际 `builtin_path`）。
- 热更新验证（**未重建引擎镜像**）：
  1. 发布 `parser_core@1.0.1` 并 promote stable；
  2. 下一次 run：`source=registry`、`version=1.0.1`、`digest=197b3651...`、`builtin_path=/work/engine/builtin.py`；
  3. 新代码诊断 `PARSER_BUNDLE revision 1.0.1` 出现，记录数保持 34，`STRUCTURED_READY`。
- 测试：资产契约测试 5 个；registry + sandbox 全量测试通过，ruff 通过。

### P2：文档级门禁 + 自动 feedback（M）

- review 增加文档级规则，命中自动创建 feedback。
- feedback 支持 document/table/field 粒度。
- 验收：AMS4108G 等历史 0 记录文档可自动进入修复流程。

**P2 执行结果（2026-11-12）：**

- review 规则集升级为 `m6`，新增 6 条文档级规则（`services/review/rules.py:run_document_rules`）：
  - `DOC-NO-RECORDS`（error）：有表格但 0 记录；
  - `DOC-NO-TABLES`（error）：`pages >= doc_min_pages` 但 0 表格；
  - `DOC-UNBOUND-COLUMNS`（warning）：`MEASURE_COLUMN_MISSING` 表格占比 ≥ 0.3，按表生成；
  - `DOC-DUP-KEYS`（warning）：同牌号同指标重复 > 3 次，按 field 生成（最多 5 组）；
  - `DOC-UNIT-MISSING`（warning）：数值缺单位占比 ≥ 50%（样本 ≥ 5）；
  - `DOC-LOW-COVERAGE`（warning）：有记录但有效表格占比 < 50%（表格 ≥ 2）。
- `ReviewRequest` 增加 `pages` / `diagnostics`；orchestration review 阶段从 OCR 与 diagnostics 产物读取后传入。
- `ReviewFinding` 增加 `message`；`findings` 表新增 `message` / `rule_id` 列（迁移 `0003_finding_rule`），review 报告可追溯到具体规则。
- 自动 feedback：`FeedbackService.create_from_review` 把 `DOC-*` finding 转成 feedback，粒度由 finding target 决定（document / table / field），并在 target 中带上 `rule_id`、`document_id`、`run_id`。
- 文档级验证：feedback 无 `measure` 时不再直接失败，改为按规则做整篇对比：
  - `DOC-NO-RECORDS`/`DOC-LOW-COVERAGE`：记录数增加；
  - `DOC-UNBOUND-COLUMNS`：未绑定列诊断减少；
  - `DOC-DUP-KEYS`：重复超额数减少；
  - `DOC-UNIT-MISSING`：缺单位比例下降；
  - 文档级反馈在无绑定配方时允许进入 triage，修复范围非 recipe 时转 `needs_more_info`（留给 OCR/engine 与 P5 代码提案）。
- 实测（4 页无表格 PDF）：
  - review `status=fail`，`DOC-NO-TABLES` 命中，run 进入 `REVIEW_FAILED`；
  - 自动创建 document 级 feedback（含 `rule_id`）；
  - `POST /v1/feedback/{id}/process` 自动完成 triage，落 `needs_more_info`，不再出现 `RECIPE_NOT_RESOLVED` 卡死。
- 测试：新增 14 个用例（6 条规则、service 统计、feedback 载荷、文档级验证判定）；全量 `pytest` 通过，ruff 通过。

### P3：candidate 增量补丁 + 已验收快照（M）

- patch_chain、accepted_snapshot、已验收区域 diff 检测。
- 用户反馈 → 增量补丁 → 合并 diff → 再审核。
- 验收：两次反馈场景下，第一次已验收记录不被静默修改。

**P3 执行结果（2026-11-12）：**

- 新增 `accepted_snapshots` 表（迁移 `0004_accepted_snapshot`）：记录 `document_id`、`document_version`、`run_id`、`feedback_id`、`records_digest`、`accepted_tables`、`accepted_fields`、`field_digests`、`actor`；`(document_id, records_digest)` 唯一，重复验收幂等。
- 快照服务 `services/orchestration/snapshots.py`：
  - 字段键 `table:grade:measure`，字段摘要取 `{value, unit, ...}` 的规范化 sha256；
  - `diff_against_snapshot` 只对已验收字段做变化/消失检测，新增字段不算回归；
  - `next_patch_chain` 保证只有基线 candidate 一致时才继承上游 patch 链。
- 用户确认结果：新增 `POST /v1/runs/{run_id}/accept` 与 `GET /v1/documents/{document_id}/snapshot`（orchestration + gateway）；快照永久保留，跨文档版本沿用，取最新一条。
- 增量补丁：`_build_candidate` 读取 registry 的 `candidate` 通道作为基线（没有则回退 stable），并在 candidate 中记录 `patch_chain`（来源 feedback 顺序），第二次反馈会叠加在未应用的 candidate 上。
- 已验收区域保护：`_verify` 产出 `changed_in_accepted`、`requires_confirmation`、`records_digest`、`field_digests`；审批接口在该标记为真且未显式传 `confirm_accepted_change=true` 时返回 `409 ACCEPTED_REGION_CHANGED`；审批通过后写入新快照。
- 实测（ASTM B338，34 条记录）：
  - `POST /runs/{id}/accept` 登记快照：2 张表、90 个字段、digest `7fd573e3...`；重复调用返回同一快照（幂等）；
  - `GET /documents/{id}/snapshot` 可读；
  - 用真实快照做基线比对：原始记录 0 处变化；修改 1 个 `Rm` 值后精确命中 `T3:1:Rm changed`。
  - 新增 6 个快照/补丁链用例；全量测试与 ruff 通过。

### P4：晋升流水线（S/M）

- candidate → shadow → stable；回归集自动化；一键回滚。
- 验收：一次完整闭环（修复 → 用户验收 → shadow → stable → 下一份文档生效）。

**P4 执行结果（2026-11-12）：**

- 新增迁移 `0005_shadow`：`shadow_documents`（灰度文档集）、`shadow_batches`（批次与计数）、`shadow_results`（逐文档双跑指标）；`promotions.feedback_id` 改为 nullable，支持无 feedback 的 shadow 自动晋升。
- Shadow 服务 `services/orchestration/shadow.py`：
  - 文档集 CRUD：`GET/POST /internal/shadow/documents`、`DELETE /internal/shadow/documents/{id}`；
  - 双跑对比 `compare_shadow`：记录数不减少、已验收字段变化数不增加、diagnostics error 数不增加，三项全过才算通过；
  - 批次执行 `run_batch`：对文档集逐份用 candidate 重跑沙箱，与最近一次 `STRUCTURED_READY` 的 stable 结果对比；无稳定基线的文档跳过；
  - 连续 `shadow_required_documents`（默认 10）份通过 → 自动 `promote stable`，写 `Promotion(action=promote, channel=stable, actor=shadow)`，并把来源 feedback 置为 `promoted`；
  - 任一份回退 → 批次 `failed`，不晋升。
- 审批路径调整：feedback `verify` 通过不再直接晋升 stable，而是先 `promote shadow` 通道 + 创建 shadow 批次，feedback 状态记为 `shadow`；批次达标后由 shadow 自动晋升 stable 并回写 `promoted`。
- 一键回滚：`POST /v1/recipes/{id}/rollback` 改由 orchestration 代理，回滚 registry 指针并写 `Promotion(action=rollback)` 审计；网关新增 shadow 文档集/批次 API。
- 实测完整闭环（ASTM B338，candidate 1.4.0 为 1.3.0 的无行为差异补丁）：
  1. 用户验收 feedback → 1.4.0 进入 `shadow` 通道，创建批次；
  2. 2/2 文档双跑通过（34 → 34 记录、已验收变化 0、error 0），批次 `promoted`，stable 自动指向 1.4.0，feedback 状态 `promoted`；
  3. 一键 rollback → stable 回到 1.3.0；
  4. `promotions` 同时留有 shadow 自动晋升与 rollback 审计。
- 测试：新增 6 个双跑对比用例；`tests/integration/agent` 55 个用例通过，ruff 通过。

### P5：L3 代码提案安全化（M）

- 静态扫描、行数/文件限制、测试强制、人工审批。
- 验收：L3 补丁不可硬编码文档、必须带测试。

**P5 执行结果（2026-11-12）：**

- 契约：新增 `CodeFile` / `CodePatch` / `CodeGuardViolation` / `CodeGuardReport`；`RepairProposal` 增加 `code_patch` 与 `guard`，L3 提案可与配方 patch 分离携带完整文件内容与 unified diff。
- 安全闸门 `services/code_guard.py`：
  - 阈值：单次最多 3 个文件、单文件 ≤ 800 行、单次补丁 ≤ 150 行、bundle 总量 ≤ 1 MB；
  - 只允许 `.py` / `.json`；拒绝绝对路径、`..`、Windows 路径与二进制后缀；
  - AST 静态扫描：仅标准库导入，禁用 `socket`/`http`/`subprocess`/`ctypes`/`shutil` 等模块，禁用 `open`/`eval`/`exec`/`compile`/`os.system` 等调用；
  - 禁止硬编码文档：UUID、文档文件名、`document_id`/`run_id` 字面量（JSON 配置同样扫描）；
  - 测试强制：必须包含 `test_*.py` 且至少一个 `def test_*`；
  - `apply_code_gate` 不通过时强制 `needs_human=true`、`risk=high`。
- Agent：repair schema 支持 `code_patch`；engine 提案解析后立即过闸门，违规内容保留在提案中供审计但摘要标注阻断码；engine 无代码、或非 engine 携带代码，均转人工。
- Orchestration：`process` 对 engine 提案二次过闸门（防下游绕过），阻断时落 `needs_more_info` 并记录 `L3 code proposal blocked by security gate: ...`；通过后进入人工审批等待（parser bundle 发布与沙箱覆盖验证尚未接线）。
- 测试：新增 21 个闸门用例；`tests/integration/agent` 77 个用例通过，ruff 通过。
- 部署验证：重建 agent / orchestration 镜像后，在 agent 镜像内执行闸门：合法补丁 `passed=True`；含 `subprocess` + 硬编码文档 + 缺测试的补丁被 `MODULE_FORBIDDEN`/`HARDCODED_DOCUMENT`/`DIFF_REQUIRED`/`TESTS_REQUIRED` 阻断。

## 9. 验收指标

| 指标 | 当前 | P1 | P2 | P3 | P4 |
|---|---|---|---|---|---|
| 解析代码热更新 | 需重建镜像 | 无需重建 | 保持 | 保持 | 保持 |
| 有 records 文档 | 11/50 | 基线不回退 | ≥20/50 | ≥30/50 | ≥40/50 |
| Field F1（60 份） | 0.4933 | 不回退 | ≥0.52 | ≥0.56 | ≥0.60 |
| 静默错误 | 4.92% | ≤4.92% | ≤4% | ≤3% | ≤3% |
| 回归集回退 | 无门禁 | 无回退 | 无回退 | 无回退 | 无回退 |
| 晋升可回滚 | 配方支持 | 资产支持 | 支持 | 支持 | 支持 |

## 10. 风险与应对

| 风险 | 应对 |
|---|---|
| agent 生成的代码破坏其他文档 | candidate + 回归集 + shadow；禁止直接 stable |
| 单文档验收即上线 | 用户验收与代码晋升分离，回归门禁强制 |
| 二次补丁改坏已验收结果 | accepted_snapshot 锁定 + diff 提示 |
| 热更新破坏可复现性 | bundle digest 写入每次 run manifest，历史版本不可变 |
| 工作区体积超限（K8s 800KB） | 代码包限制 1MB；大文件走对象存储；K8s 后续改 PVC |
| 依赖变化 | 仍走镜像；资产清单声明 stdlib_only |

## 11. 决策记录

| 编号 | 决策 | 状态 |
|---|---|---|
| 1 | 资产服务扩展 `recipe-registry`，不新增独立服务 | 已确认 |
| 2 | shadow：指定文档集 + 双跑对比，连续 10 份无回退自动晋升 | 已确认 |
| 3 | 回归通过后自动晋升 stable，无需人工二次确认 | 已确认 |
| 4 | 已验收快照永久保留；文档版本变化继续沿用，问题由门禁/用户反馈发现 | 已确认 |
| 5 | L3 代码提案自动进入 candidate；用户只审核最终解析结果，不做人工 diff 合并 | 已确认 |

## 12. 与现有文档的关系

- 版面优先 OCR 与 Phase 0/1 进度：[layout-first-and-repair-optimization-plan.md](layout-first-and-repair-optimization-plan.md)
- 新旧差异与审核闭环分析：[legacy-vs-new-and-review-loop-analysis.md](legacy-vs-new-and-review-loop-analysis.md)
- 本方案落地后，Phase 1 的策略代码将从“镜像内置”迁移为 `parser_core` 资产，后续 agent 修改无需重建镜像。
