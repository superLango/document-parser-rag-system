# M3 里程碑详细执行计划：配方/模板注册中心

> 文档版本：v1.2  
> 编制日期：2026-11-11  
> 计划周期：2026-12-17 ~ 2026-12-30  
> 主责角色：项目负责人（兼后端/配方）  
> 协作角色：外部业务/领域专家（按需）  
> 上游依据：[架构重构方案](architecture-refactor-plan.md)、[项目需求文档](requirements.md)、[整体开发计划](development-plan.md)、[项目决策记录](decision-log.md)  
> 前置里程碑：[M0](M0-project-scaffold.md)、[M1](M1-core-domain-orchestration.md)  
> 当前状态：已完成（2026-11-11；7 配方 + 1 模板迁移，路由一致率 100%）

---

## 1. 里程碑目标

建立配方/模板的不可变包、注册中心、版本通道、匹配与迁移能力：

- 配方包规范落地（manifest + bindings + templates + tests + digest）。
- 注册中心支持 publish/get/resolve/promote/rollback/deprecate。
- 确定性 matcher 可替代旧 `match_recipe`。
- 旧配方数据 100% 迁移为新包。
- 路由一致率 ≥99%，可回滚。

## 2. 范围与不做

### 2.1 范围

| 项 | 内容 |
|---|---|
| 包规范 | recipe-package-2.0 schema |
| 包构建 | manifest/bindings/templates/tests/checksum |
| 注册中心 | 版本、通道、列表、解析、晋升、回滚、弃用 |
| 匹配 | 签名分数、token 重叠、歧义消解 |
| 兼容性 | engine_api 范围、测试用例 |
| 迁移 | 旧 `configs/recipes/*.json` → 新包 |
| 模板 | 旧 schema_templates → 模板包 |
| 路由评测 | 旧 matcher vs 新 matcher 对比 |

### 2.2 不做

- 不做 RouterAgent（M5）。
- 不做沙箱执行（M4）。
- 不做配方编辑器。
- 不做自动配方生成。
- 不做前端配方页面（M7）。

## 3. 前置依赖

| 依赖 | 说明 |
|---|---|
| M0 完成 | contracts、服务骨架 |
| M1 完成 | 编排可调用路由阶段 |
| 旧配方数据 | `metal-doc-agent/configs/recipes/` |
| 旧模板数据 | `configs/schema_templates/` |
| 业务确认 | 配方状态、通道映射 |
| 路由基线 | 旧 matcher 在样本上的结果 |

## 4. 交付物

| # | 交付物 | 路径 | 形式 | 验收人 |
|---|---|---|---|---|
| D3.1 | 配方包 schema | `packages/contracts/schemas/recipe-package-2.0.json` | Schema | 架构 |
| D3.2 | 包加载/校验 | `services/recipe_registry/package.py` | 代码 | 架构 |
| D3.3 | 注册中心 | `services/recipe_registry/registry.py` | 服务 | 架构/QA |
| D3.4 | 匹配器 | `services/recipe_registry/matcher.py` | 代码 | 算法/QA |
| D3.5 | 配方包数据 | `services/recipe_registry/data/recipes/` | 数据 | 业务 |
| D3.6 | 模板数据 | `services/recipe_registry/data/templates/` | 数据 | 业务 |
| D3.7 | 迁移脚本 | `scripts/migrate_recipes/` | 脚本 | QA |
| D3.8 | 路由对比报告 | `new_app/docs/reports/M3-route-parity.md` | 报告 | PM/架构 |
| D3.9 | 兼容性测试 | `new_app/tests/contract/recipes/` | 测试 | QA |

## 5. 工作分解（WBS）

| 编号 | 任务 | 主责 | 协作 | 产出 | 计划完成 |
|---|---|---|---|---|---|
| M3-01 | 包 schema 与 manifest 评审 | 架构 | 后端/业务 | schema | 2026-12-17 |
| M3-02 | 包加载/校验/digest | 后端 | 架构 | package.py | 2026-12-19 |
| M3-03 | 注册中心存储与 API | 后端 | DevOps | registry | 2026-12-21 |
| M3-04 | 通道与版本状态机 | 后端 | 架构 | channels | 2026-12-22 |
| M3-05 | 确定性 matcher | 算法 | 后端 | matcher | 2026-12-23 |
| M3-06 | 旧配方迁移脚本 | 后端 | 业务/QA | 迁移脚本 | 2026-12-25 |
| M3-07 | 模板迁移 | 后端 | 业务 | 模板包 | 2026-12-26 |
| M3-08 | 兼容性测试 | QA | 后端 | 测试报告 | 2026-12-27 |
| M3-09 | 路由对比与差异清单 | QA/算法 | 业务 | 报告 | 2026-12-29 |
| M3-10 | 与编排集成 | 后端 | 算法 | 路由阶段真实调用 | 2026-12-30 |

## 6. 接口与契约

### 6.1 RecipeRegistryPort

```python
class RecipeRegistryPort(Protocol):
    def publish(self, package: RecipePackage) -> RecipeRef: ...
    def get(self, ref: RecipeRef) -> RecipePackage: ...
    def resolve(self, recipe_id: str, channel: str) -> RecipeRef: ...
    def promote(self, candidate: RecipeRef, approved_by: str) -> RecipeRef: ...
    def rollback(self, recipe_id: str, to_version: str) -> RecipeRef: ...
    def deprecate(self, ref: RecipeRef, reason: str) -> None: ...
    def list_versions(self, recipe_id: str) -> list[RecipeRef]: ...
```

### 6.2 包 manifest

按架构方案 7.2 执行；本阶段必须支持：

- `recipe_id` 与文件名一致。
- `version` 语义化。
- `engine_api` 范围。
- `signature/bindings/templates/tests/checksum`。
- `entrypoint` 可选；本阶段可先全部无代码包。

### 6.3 通道

| 通道 | 用途 |
|---|---|
| `stable` | 生产解析 |
| `candidate` | 候选修复/新配方 |
| `shadow` | 影子验证 |
| `deprecated` | 只读保留 |

规则：

- 版本不可变。
- 通道是指针，不是包属性。
- 晋升原子；回滚可追溯。
- run 创建时冻结版本。

## 7. 迁移方案

### 7.1 配方迁移

```text
旧 recipes/*.json
  → 读取 recipe_id/status/profile/signature/bindings/rules
  → 生成 manifest.json
  → 生成 bindings.json
  → 生成 tests/cases 骨架（从旧样本/金标抽取）
  → 计算 digest
  → 写入 data/recipes/<id>/<version>/
  → 导入 registry
```

### 7.2 状态映射

| 旧状态 | 新通道 |
|---|---|
| `active` | `stable` |
| `candidate` | `candidate` |
| `retired` | `deprecated` |
| `registry L4` | `stable` |
| `registry L2/L3` | `candidate` |

### 7.3 差异报告

逐文档对比：

- 旧 matcher 选中 recipe_id / status / score。
- 新 matcher 选中 recipe_id / status / score。
- 差异 >1% 的文档进入人工复核清单。

## 8. 验收标准

### 8.1 功能

- [ ] 配方包可 publish/get/list。
- [ ] `stable/candidate/shadow/deprecated` 通道可用。
- [ ] `resolve` 返回确切 version + digest。
- [ ] `promote` 原子切换；`rollback` 可回退。
- [ ] 旧配方 100% 迁移。
- [ ] 模板 100% 迁移。
- [ ] 编排路由阶段可使用新 matcher。

### 8.2 质量

| 指标 | 门槛 |
|---|---|
| 配方迁移率 | 100% |
| 路由一致率 | ≥99% |
| 不兼容组合 | 100% 被拒绝 |
| 版本不可变 | 修改包后 digest 变化 |
| 回滚 | 指针回滚成功 |
| 契约测试 | 100% 通过 |

### 8.3 文档

- [ ] 配方包格式说明。
- [ ] 注册中心 API 说明。
- [ ] 迁移报告 + 差异清单。
- [ ] 通道/晋升/回滚说明。
- [ ] PROVENANCE 记录。

## 9. 时间节点

| 节点 | 日期 | 标志 |
|---|---|---|
| K3.1 包 schema 冻结 | 2026-12-17 | 评审通过 |
| K3.2 注册中心可用 | 2026-12-22 | API 通过 |
| K3.3 迁移完成 | 2026-12-26 | 100% 配方入库 |
| K3.4 路由对比完成 | 2026-12-29 | 一致率 ≥99% |
| K3.5 验收 | 2026-12-30 | 集成通过 |

## 10. 风险与应对

| 风险 | 应对 |
|---|---|
| 旧配方语义不清晰 | 业务专家逐条确认；差异清单 |
| 签名分数不可比 | 统一 token 化/权重；以路由结果为准 |
| 迁移遗漏 | 清单 + 数量对账 + CI 校验 |
| 版本指针并发 | 乐观锁；晋升单写 |
| 模板字段漂移 | 模板版本化；旧 run 冻结 |

## 11. 出口准则与回滚

**出口准则**

- 配方/模板迁移完成。
- 路由一致率达标。
- 注册中心 API/契约测试通过。
- 架构/业务/QA/PM 验收。

**回滚**

- 编排可固定到旧配方快照。
- 注册中心可整体回退到上一批次导入。
- 不影响已创建的 run（版本冻结）。

## 12. 关联文档

- [架构重构方案](architecture-refactor-plan.md)
- [整体开发计划](development-plan.md)
- 上一里程碑：[M2](M2-ocr-table-algorithms.md)
- 下一里程碑：[M4 沙箱服务](M4-sandbox-runtime.md)、[M5 Agent Runtime](M5-agent-runtime.md)

## 13. 变更记录

| 版本 | 日期 | 变更 | 变更人 |
|---|---|---|---|
| v1.0 | 2026-11-11 | 初版 | 项目负责人 |
| v1.1 | 2026-11-11 | 补充 Q4 词典/数据策略引用、Q8 单人角色 | 项目负责人 |
| v1.2 | 2026-11-11 | M3 完成：配方包、注册中心、matcher、旧数据迁移、编排集成与路由一致率报告 | 项目负责人 |

---

## 14. 执行记录（2026-11-11）

### 14.1 已完成

| 项 | 结果 |
|---|---|
| 包模型 | `package.py`：manifest 校验（recipe_id/version/engine_api/profile）、digest（sha256）、同版本不可变 |
| 注册中心 | `registry.py`：publish/get/resolve/promote/rollback/deprecate/list，通道指针 + history，tmp+replace 原子写 |
| 匹配器 | `matcher.py`：复刻旧 `signature_score` 与 0.9/0.6 阈值 |
| 数据迁移 | 7 个旧配方 → `data/recipes/<id>/1.0.0/`；1 个模板 → `data/templates/product_full/1.0.0/` |
| API | `api.py`：发布、列表、详情、resolve、promote、rollback、deprecate、match |
| 编排集成 | routing 阶段读取 OCR 产物表格并调用 `/internal/recipes/match`；`ROUTE_USE_FAKE` 可回退 |
| 契约测试 | `tests/contract/recipes/`：包校验、注册中心、matcher，共 18 个用例 |
| 对比脚本 | `scripts/benchmark/route_parity.py`；报告见 [M3-route-parity](reports/M3-route-parity.md) |
| 文档 | `services/recipe_registry/README.md`、`PROVENANCE.md` 已更新 |

### 14.2 验证证据

| 验证 | 结果 |
|---|---|
| Compose API | `GET /internal/recipes` 返回 7 个配方，全部 `stable@1.0.0` |
| resolve | `mechanical_properties_v1` → `1.0.0` + digest `43e3466e…` |
| matcher | 3×3 力学表 → `hardness_v1` `candidate` `0.8` |
| K8s 端到端 | fixture 上传 → `STRUCTURED_READY`；routing artifact `assignments` 1/1，`hardness_v1@1.0.0` `0.75` |
| 路由一致率 | 5 个金标表：配方 1.0000、状态 1.0000、分数逐例相同 |
| 契约测试 | 18 passed |
| Ruff | 通过 |

### 14.3 验收对照

| 验收项 | 结果 |
|---|---|
| 包 publish/get/list | 通过 |
| stable/candidate/shadow/deprecated 通道 | 通过 |
| resolve 返回 version + digest | 通过 |
| promote 原子切换、rollback 可回退 | 通过（单测） |
| 旧配方迁移 100% | 7/7 |
| 模板迁移 100% | 1/1 |
| 编排路由使用新 matcher | 通过（K8s artifact 证据） |
| 路由一致率 ≥ 99% | 100% |
| 不兼容组合被拒绝 | 通过（engine_api / checksum / id / version） |
| 版本不可变 | 通过（同版本不同内容返回 409） |
| 契约测试 100% | 18 passed |

### 14.4 说明

- 旧生命周期 L0–L5 由 `stable/candidate/shadow/deprecated` 通道模型替代；旧 `registry.json` 为空，无状态需要保留。
- 匹配结果多为 `candidate`，因为金标表列数与 token 少于正式标准表；与旧算法逐位一致，未新增偏差。
- RouterAgent 的歧义消解与 LLM 兜底留给 M5。
