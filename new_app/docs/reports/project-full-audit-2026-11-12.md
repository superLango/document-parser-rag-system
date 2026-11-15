# 项目全维度核查报告

> 核查时间：2026-11-12
> 核查范围：`new_app` 全部服务、契约、配方/parser 资产、前端、部署、测试、CI 与 8 份核心文档
> 核查方式：只读审计；文档口径提取 + 代码逐项核对 + 关键结论二次复核（标 ✔ 的条目已由本轮代码复核）
> 本轮未修改任何业务代码；本报告与配套整改清单为唯一产出

## 0. 结论摘要

- 主业务链路（版面优先 → 配方矩阵 → 沙箱解析 → 审核 → 反馈修复 → 晋升）**已打通**，Phase 2 指标治理、L3 执行链路、50 份规模化门禁均已完成。
- 但项目**尚不能判定为"全部优化结束"**：存在 6 项 P0 级问题（审批语义冲突、registry 无持久化、伪造开关无标识、验收口径下调、第 8 服务口径、契约占位），以及 12 项 P1 覆盖/一致性问题。
- 文档与实现的主要矛盾不是"功能没做"，而是**文档状态滞后 + 验收口径多套并行 + 个别能力自动越过了人工闸门**。

## 1. 已产出资产盘点

### 1.1 服务与代码

| 资产 | 位置 | 状态 |
|---|---|---|
| 七微服务 | `services/{api_gateway,orchestration,ocr,agent,sandbox,recipe_registry,review}` | 已实现并容器运行 |
| 共享契约 | `packages/contracts/src/hanson_contracts`（sandbox/feedback/agent 等） | 已实现；OpenAPI 文件仍为 M0 占位 |
| 共享包 | `hanson_domain`、`hanson_obs` | 仅占位 `__init__` |
| 编排状态机 | `services/orchestration/workflow.py`、`models.py`、`migrations/0001–0006` | 已实现 |
| 审核修复闭环 | `services/orchestration/feedback/service.py`、`shadow.py`、`snapshots.py`、`rundiff.py` | 已实现 |
| OCR/版面 | `services/ocr/adapters/*`、`algorithms/{profile,table_grid,repairs}.py` | 已实现 |
| 配方注册 | `services/recipe_registry/*`，7 个配方 + 不可变版本 + 通道 | 已实现 |
| 沙箱运行时 | `services/sandbox/*`、`runtime/{runner,builtin,strategies}.py` | 已实现；parser 资产热加载 |
| Agent Runtime | `services/agent/*`（Harness/Context/Gateway/4 Agent） | 已实现 |
| 前端 | `web/src/pages/*` 六页面 + 六 Tab | 已实现，部分能力缺失（见 4.3） |

### 1.2 数据与资产

| 资产 | 位置 | 状态 |
|---|---|---|
| 配方包 | `services/recipe_registry/data/recipes`（mechanical 1.5.0、chemical 1.1.0、element_rows 1.2.0 等） | stable 可用 |
| Parser 资产 | `parser_core` 1.0.6 → 1.0.13 stable；1.0.14 candidate | 已发布，支持 pinned |
| 词典 | 2203 条，导入对账 2203/2203 | 已完成 |
| 验证数据 | `data/validation-2026-11-06/`（60 份旧结果 + PDF manifest） | 可用 |
| 金标 | `docs/reports/gold-standards.json` | 严格校验仅 2/89 合格 |

### 1.3 文档与报告

| 文档 | 作用 | 状态问题 |
|---|---|---|
| `requirements.md` | 初始定位/非目标 | 仍写"不启动开发"（滞后） |
| `architecture-refactor-plan.md` | 架构重构方案 | 沙箱运行时仍写"未锁定"；审批写"用户 approve→stable" |
| `development-plan.md` | 全量开发计划 M0–M8 | M0/M1 仍标"待验收"，与后续已完成状态不一致 |
| `M0–M8-*.md` | 阶段详细执行计划 | 部分交付物与实现不符/未回填 |
| `acceptance/M8.md` | M8 验收 | 在 F1 未达标、灰度未真实执行下判"通过（仅词典导入）" |
| `reports/layout-first-and-repair-optimization-plan.md` | 本轮主方案 | 已记录 Phase 2 治理、L3、门禁 v1 |
| `reports/algorithm-asset-hot-update-plan.md` | 资产化 P1–P5 | 状态仍写"待确认"；审批语义自相矛盾 |

### 1.4 测试 / 部署 / CI

| 资产 | 状态 |
|---|---|
| 测试 | sandbox 69 用例通过；agent 13 文件；recipe_registry 5 文件；orchestration 仅纯函数测试；api_gateway 仅 health；web 无单测/E2E |
| Compose | 七服务 + PG/MinIO/Redis 可运行；**无 web 容器**；recipe-registry 无持久卷 |
| K8s | `deploy/k8s/base` 七服务；无 Ingress/web；agent session 在 `/tmp` |
| CI | ruff / compile / pytest / 旧包 grep + web typecheck/build；无集成、无迁移、无契约校验 |
| 发布门禁 | `scripts/benchmark/gate_scale.py` 50 份，F1 0.6025 / 静默 2.62% / 失败 0 |

## 2. 进度状态总表

> 完成度为评估值，非文档声明；用于排序，不作为验收结论。

| 里程碑 | 状态 | 完成度（评估） | 主要缺口 |
|---|---|---|---|
| M0 骨架 | 基本完成 | 90% | ADR、`uv.lock`、K8s/CI 正式验收未回填 |
| M1 编排主链路 | 基本完成 | 85% | 创建 run 幂等、事件类型、progress、OpenAPI 契约 |
| M2 OCR/表格 | 基本完成 | 90% | 扫描件成功率未系统统计；profile 命名与文档不一致 |
| M3 配方注册 | 基本完成 | 90% | registry 数据无持久卷，重建丢通道 |
| M4 沙箱 | 基本完成 | 90% | Kata 未实测；运行时决策未回填架构文档 |
| M5 Agent | 部分完成 | 75% | RouterAgent 未接入、needs_human 缺失、工具集不全、并发窗口基准未做 |
| M6 反馈闭环 | 部分完成 | 80% | 审批语义与架构冲突、shadow 永久 WAITING、审计口径 |
| M7 前端 | 部分完成 | 80% | 无 SSE、审核证据不可定位、词典只读、无搜索分页 |
| M8 词典/切换 | 受限通过 | 85% | F1 未达 0.80、灰度未真实执行、归档标签未建 |
| Phase 2 指标治理 | 完成 | 100% | F1 0.6020 / 静默 2.55% |
| L3 执行链路 | 完成 | 100% | pinned parser 端到端验证 |
| 规模化门禁 v1 | 完成 | 100% | 50 份门禁脚本与报告 |

## 3. 三份核心文档交叉核验

### 3.1 架构重构方案 vs 实现

| 架构承诺 | 实现 | 结论 |
|---|---|---|
| 七服务、服务间只走 contracts、不共享 DB | 七服务成立；contracts 已用；各服务同库不同表 | 基本符合 |
| 配方不可变、stable 仅晋升改变、run 冻结版本 | 已实现，digest 校验 | 符合 |
| 审批：`用户 approve → PromotionWorkflow → 原子更新 stable`（A:1170-1184） | ✔ approve 实际 promote 到 **shadow**，满 10 份后**自动**升 stable（feedback/service.py:418-436、shadow.py:390-415） | **冲突 P0** |
| 低置信路由 → RouterAgent / needs_human（A:1149-1158） | ✔ 仅确定性 matcher；fallback 固定 `generic`（workflow.py:362-410） | **缺失 P0** |
| 沙箱运行时 M4 后确认（A:1318-1320） | 已选定 runc 9.10（decision-log） | 文档未回填 P1 |
| 事件溯源每阶段可回溯 | 缺 `run.created` / `artifact.created` 写入 | 部分 P1 |
| 公开 API `/v1`、内部 `/internal` | 路由符合；OpenAPI 仅 health | 部分 P1 |

### 3.2 全量开发计划 vs 里程碑

| 计划要求 | 实际 | 结论 |
|---|---|---|
| 1 人串行、不得跳门禁（P:99,191） | M0/M1 仍标"待验收"，M8 已判通过；M2–M7 多数功能先于验收推进 | **依赖倒挂 P1** |
| M0 验收：CI、K8s、契约、无旧 import | CI 绿；K8s 未正式跑；契约占位 | 部分完成 |
| M1 验收：幂等、恢复、事件、API | 恢复/取消已测；创建 run 无幂等、事件不全 | 部分完成 |
| M5 验收：并发 4×三窗口基准 | 仅单请求；并发 4 留到 M8（L:263） | **门槛未满足 P1** |
| M6 验收：approve→stable 原子、reject→丢弃 | approve 走 shadow；reject 路径存在 | **偏差 P0** |
| M8 验收：SLO、切换/回滚、灰度 | 压测 0 错误、切换/回滚 455/475ms；灰度未真实执行 | 受限通过 P0 口径 |

### 3.3 阶段详细计划 vs 现实（口径冲突）

| # | 冲突 | 出处 | 影响 |
|---|---|---|---|
| 1 | 新旧对比 F1 三套口径：0.3489（12 样本）/ 0.4933→0.6020（60 样本）/ 目标 0.80 | L:621,657；F:350-397；I:13 | 无法判断哪个是验收基线 |
| 2 | 静默门槛：≤5% 与 ≤3%→≤2% 并存 | L:657；I:14；F:448 | 门禁阈值不唯一 |
| 3 | 金标：要求 ≥30 份 vs 实际仅 2 份合格 | F:367,432；gold-standards.json | 金标门禁无法启用 |
| 4 | 审批：`用户 approve` vs `回归通过自动晋升、无需人工确认` | A:1170-1184；H:22 vs H:221 | **实现与验收均无唯一语义** |
| 5 | M8 "通过" vs 指标未达 0.80、灰度未执行 | M8:6,38,46 | 验收结论被弱化 |

## 4. 核查清单（按问题类型）

> 类型：A=遗漏项，B=冲突/缺陷，C=覆盖不足，D=偏差
> 优先级：P0=上线前必须解决，P1=本阶段应解决，P2=后续优化

### 4.1 A 类：尚未落地的遗漏项

| ID | 模块 | 问题 | 影响 | 优先级 | 证据 |
|---|---|---|---|---|---|
| AUD-A01 | 契约 | `public.yaml`/`internal.yaml` 仅 health，与 60+ 端点不符 | 前端类型、第三方集成、契约测试全部失真 | P0（已修复） | 自动导出：public 37 paths、internal 35 paths；`--check` 通过 |
| AUD-A02 | 编排 | 创建 run 无幂等键 | 重复点击/重试产生重复 run 与费用 | P1 | `orchestration/api.py:150-167` |
| AUD-A03 | 编排 | `run.created`、`artifact.created` 事件未写入 | 事件溯源与审计不完整 | P1 | 全库无写入 |
| AUD-A04 | 编排 | Run 无 progress 字段，前端只能显示阶段 | 长文档体验与 SLA 观测不足 | P2 | `schemas.py:30-46` |
| AUD-A05 | Agent | RouterAgent 未接入编排路由 | 低置信表无模型补位，无 needs_human | P0（已修复） | 低置信/未匹配表标记 `needs_human` 并写 `run.route.needs_human` 事件；`ROUTE_AGENT_ENABLED=true` 时接 RouterAgent |
| AUD-A06 | Agent | 工具集仅 5 个只读工具，缺 sandbox/review/human | 长任务闭环能力不足 | P1 | `agent/tools/builtin.py:88-147` |
| AUD-A07 | Agent | Prompt 版本/hash 未落库 | 无法复现与审计模型行为 | P1 | `workflow.py:742-778` |
| AUD-A08 | 前端 | 无 SSE，仅 1.5s 轮询；审核证据不可定位页/bbox | 实时性与可核查性弱 | P1 | `ExtractionPage.tsx:83-87`、`ReviewFindings.tsx:107-110` |
| AUD-A09 | 前端 | 词典只读，无导入/编辑 UI | M8 词典能力只能用脚本 | P2 | `DictionaryPage` |
| AUD-A10 | M8 | 全量导入脚本未建、灰度 10/50/100 未真实执行、归档标签未建 | 切换证据不足 | P0→受限通过 | M8 已改“受限通过”，未达项列入 Phase 3；灰度待生产执行 |
| AUD-A11 | 金标 | 金标 ≥30 未达成（严格仅 2/89） | 金标门禁无法启用 | P1 | `gold-standards.json` |
| AUD-A12 | 策略 | `grade_property_tail`/`element_matrix` 真实命中未统计 | 无法判断策略价值 | P2 | 方案文档 F:287 |

### 4.2 B 类：逻辑冲突 / 实现障碍 / 设计缺陷

| ID | 模块 | 问题 | 影响 | 优先级 | 证据 |
|---|---|---|---|---|---|
| AUD-B01 | 反馈闭环 | 架构要求 approve→stable 原子；实现 approve→shadow→10 份后自动 stable；H 文档 22 行与 221 行互相矛盾 | 审批责任不清、上线不可控 | P0 | ✔ `feedback/service.py:418-436`、`shadow.py:390-415`、A:1170-1184、H:22/221 |
| AUD-B02 | Shadow | 不足 10 份时永久 `WAITING`，无超时、告警、人工强制晋升/放弃 | 反馈闭环卡死且无出口 | P0 | ✔ `shadow.py:390-403` |
| AUD-B03 | 配方注册 | registry 数据在容器内无持久卷，重建丢通道/历史 | 生产不可用、发布不可追溯 | P0（已修复） | `docker-compose.yml` recipe-registry volumes；重建后 1.0.14/1.2.0 仍可读取 |
| AUD-B04 | 健康检查 | `/healthz`、`/readyz` 固定返回 ok，不查 PG/MinIO/模型 | 故障时仍被判健康 | P1 | `services/common.py:17-23` |
| AUD-B05 | 测试开关 | fake 开关可被环境/请求误开，假结果无 `simulated` 标识；`OCR_BACKEND` 可由请求指定 mock | 生产可能静默产出假数据 | P0（已修复） | fake 阶段写 `simulated=true`；启动告警；快照拒收；compose 显式 false |
| AUD-B06 | 编排 | `MOCK_STAGE_DELAY_SECONDS=0.2` 默认在真实链路生效 | 无意义延迟 | P2 | `config.py:15` |
| AUD-B07 | 配方注册 | `resolve` 返回查询参数 channel，而非真实绑定通道 | 运维误判 | P2 | `recipe_registry/api.py:310-326` |
| AUD-B08 | 验收 | M8 在 F1 0.3489、静默 9.13%、灰度未执行下判"通过" | 验收失真、风险后移 | P0（已修复） | M8 改为受限通过；D-016 固化指标口径 |
| AUD-B09 | 事件/契约 | CI 的契约"校验"仅 YAML 解析；公开契约占位 | 契约驱动名存实亡 | P1（已修复） | CI 新增 `export_openapi.py --check`，契约漂移即失败 |
| AUD-B10 | 部署 | recipe-registry/agent 会话状态均落临时目录，无持久化 | 重启丢状态 | P1 | `compose:180-190`、`agent/config.py:19` |

> **整改进展（2026-11-12）**：AUD-B01、AUD-B02 已按方案 B 修复并端到端验证。
> 决策记录 D-015；状态机 `shadow_state.py`；超时 `deadline_at`（迁移 0007）；人工出口 `POST /v1/shadow/batches/{id}/promote|abandon`。
> 实测：`expired` / `abandoned` / 人工 `promote`（stable 1.5.0→1.6.0→回滚 1.5.0）均通过，`promotions` 审计完整；`SHADOW_AUTO_PROMOTE=false` 为默认值。

### 4.3 C 类：覆盖范围缺失 / 考虑不周

| ID | 模块 | 问题 | 影响 | 优先级 |
|---|---|---|---|---|
| AUD-C01 | 测试 | orchestration 主链路、api_gateway 转发、review HTTP、ocr 全链路无集成测试 | 回归只能靠 60 份脚本 | P1 |
| AUD-C02 | CI | 无 PG/MinIO 集成、无迁移验证、无 web E2E | CI 绿灯不代表可运行 | P1 |
| AUD-C03 | 压测 | M8 压测未覆盖 OCR/沙箱并发 | 容量结论不完整 | P1 |
| AUD-C04 | 回归 | 50/60 份门禁只覆盖数字 PDF 重建表，未统计扫描件成功率 | Phase 3 门槛无数据 | P1 |
| AUD-C05 | 前端 | 无搜索/分页/筛选；无 web 容器；K8s 无 Ingress | 交付形态不完整 | P2 |
| AUD-C06 | 文档 | M0/M1 状态、沙箱运行时决策、H 文档状态、V-001~008 均未回填 | 决策不可追溯 | P1 |

### 4.4 D 类：与初始定位/核心目标的偏差

| ID | 模块 | 偏差 | 影响 | 优先级 | 证据 |
|---|---|---|---|---|---|
| AUD-D01 | 架构 | 新增 `layout_api`/多 OCR 引擎，与"不新增第 8 服务"冲突 | 服务边界失控 | P0（已修复） | D-017：7 个业务微服务 + 外部模型服务 |
| AUD-D02 | 晋升 | L3 代码补丁"回归通过自动晋升 stable、无需人工确认" | 绕过人工闸门 | P0（已修复） | D-015：默认人工确认，显式开关才自动 |
| AUD-D03 | 指标 | 以旧基线扩为门禁基线，0.80 目标下调为 0.60 且未登记阶段例外 | 目标漂移、旧错误固化 | P0（已修复） | D-016：发布门禁 0.60/3%，Phase 3 0.80/2% |
| AUD-D04 | 金标 | 金标策略退化为"2 份 + 旧基线" | 验收说服力不足 | P1 | F:432 |
| AUD-D05 | 算法 | 策略链行为对齐旧提取器，存在"复制后重写"滑坡 | 旧缺陷带入新系统 | P1 | F:180-187 |
| AUD-D06 | 范围 | M8 收缩为"仅词典导入"，未在总计划登记范围变更 | 计划与实际不一致 | P1 | M8:6；P:96 |

## 5. 可直接落地的调整优化方案

### 5.1 P0（上线前必须完成）

1. ~~**统一审批语义（需一次决策）**~~ **已完成（方案 B）**
   - 已确认方案 B：人工 approve 进 shadow；满额默认 `ready`；`SHADOW_AUTO_PROMOTE=false` 为默认，显式开启才自动晋升。
   - 已同步修订 A:1170-1184、M6 §6.4/§8.1、H:22/221，并写入决策 D-015。
2. ~~**Shadow 出口**~~ **已完成**
   - `shadow_batches.deadline_at`（迁移 0007）；超时置 `expired` 并把反馈退回 `verified`。
   - 新增 `POST /v1/shadow/batches/{id}/promote` 与 `.../abandon`，均写 `promotions` 审计。
3. ~~**Registry 持久化**~~ **已完成**
   - compose 已挂载 `../../services/recipe_registry/data:/app/services/recipe_registry/data`；
   - 重建容器后 recipe stable=1.5.0、parser stable=1.0.13，运行时发布的 1.0.14 与 1.2.0 仍可读取；
   - docker inspect 确认 bind mount 生效。
4. ~~**契约可信化**~~ **已完成（导出 + CI 校验）**
   - `scripts/contracts/export_openapi.py` 自动导出：public 37 paths、internal 35 paths；
   - CI 新增 `--check`，契约漂移即失败；前端类型自动生成留 P1。
5. ~~**Fake 防误用**~~ **已完成**
   - 四个 fake 阶段写 `simulated=true`；启动打 `SIMULATION_MODE` 告警；
   - `capture_run_snapshot` 检查 ocr/result/records，模拟结果拒收；
   - compose 显式 `REVIEW_USE_FAKE=false`，其余 fake 开关默认 false。
6. ~~**验收口径修订**~~ **已完成**
   - M8 改为“受限通过”，未达项单列；D-016 固化 legacy-regression 0.60/3% 与 gold Phase 3 0.80/2%。
7. ~~**第 8 服务口径**~~ **已完成**
   - D-017：7 个业务微服务 + 外部模型服务（layout/GLM），架构图与资产化文档已同步。
- ~~**低置信路由（补充 P0）**~~ **已完成（P0 风险消除）**
  - 低置信/未匹配表标记 `needs_human`，写 `run.route.needs_human` 事件（含表清单/数量/agent_used）；
  - `ROUTE_AGENT_ENABLED=true` 时接入 RouterAgent；默认关闭以保持回归稳定。

> **P0 收口状态（2026-11-12）**：核查清单中的 6 组 P0 已全部处理或转为受限通过；50 份门禁复测 F1 0.6025 / 静默 2.62% / 失败 0，无回归。

### 5.2 P1（本阶段应完成）

8. RouterAgent 接入路由：确定性 matcher 低置信 → RouterAgent（仅从 catalog 选）→ 仍低置信 → `needs_human` 队列 + 前端提示。**（已完成，随 P0 低置信路由落地；`ROUTE_AGENT_ENABLED` 默认关闭）**
9. 创建 run 幂等：`(document_id, sha256, recipe_channel, parser_version)` 唯一键，重复请求返回既有 run。**（已完成：`runs.idempotency_key` 唯一列 + `idempotency.build_key`；create/reparse 分别用 `run`/`reparse` 前缀；迁移 0008）**
10. 事件补齐：`run.created`、`artifact.created`、`promotion.completed` 全量写入；前端接 SSE（保留轮询兜底）。**（已完成：run/artifact 写 run_events；晋升/放弃/回滚写 `audit_events`；前端 EventSource 订阅 + 5s 轮询兜底）**
11. 健康检查分级：`/healthz` 进程存活；`/readyz` 检查 DB、MinIO、registry、模型端点。**（已完成：`create_app` 支持 readiness 回调；orchestration 检查 DB/MinIO/registry，OCR 检查对象存储与模型端点，未就绪返回 503）**
12. 测试补齐：orchestration HTTP 主链路（上传→run→取消→恢复）、gateway 转发、review HTTP、ocr 全链路；CI 加 PG/MinIO service + `alembic upgrade head` + web E2E。**（已完成：orchestration 主链路、gateway 转发（含 reparse 透传与 502）、review 规则/空报告、ocr mock 解析均有 HTTP 测试；主 CI 增加 PG/MinIO + 迁移；新增 `new-app-web-e2e.yml`（定时 + 手动门控，起 compose 栈后跑 Playwright），本地实跑 3 条 E2E 全部通过）**
13. Agent 工具补齐：sandbox/review/human 三类工具；prompt 版本与 hash 落库。**（已完成：新增 `run_sandbox`/`request_review`/`escalate_to_human` 三个 write 工具，未配置地址或缺少请求上下文时返回明确错误；prompt_id/hash 已在会话落库并有测试）**
14. 压测扩展：OCR/沙箱并发场景；统计扫描件成功率并纳入 Phase 3 门槛。**（已完成脚本能力：`--run-count/--run-concurrency` 控制流水线并发，输出成功率与 OCR/沙箱阶段 p50/p95，`--scan-fixture` 统计扫描件成功率；本轮实测 run 并发 2、流水线成功率 100%，扫描件因未提供 fixture 标记不可用。纳入 Phase 3 门槛待样本齐备）**
15. 金标扩充：以 `accepted_snapshot` 为来源累计 ≥30 份；门禁分两级（legacy 回归为发布门禁、金标为质量门禁）。**（受阻：门禁分级已由 D-016 固化；≤30 份需人工审核通过后积累，当前严格合格仅 2/89，无法以代码替代人工确认）**
16. 文档回填：M0/M1 状态、沙箱运行时决策、H 文档状态、V-001~008、M8 范围变更登记。**（已完成：M0 改为“已完成（受限）”、M1 改为“已完成”；沙箱运行时回填 containerd+runc；V-001~V-006/V-008 已回填，V-007 待生产切换窗口；M8 范围变更见验收文档第 4 节）**

> **P1 进度（2026-11-12）**：第 8–14、16 项已完成；第 15 项受阻于人工审核样本量。

### 5.3 P2（后续优化）

17. 前端：搜索/分页/筛选；审核证据页/bbox 定位；原文预览叠加版面框；词典导入 UI。
18. 部署：web 容器 + Ingress；agent session 与 registry 数据持久化；K8s 健康探针使用 readyz。
19. `MOCK_STAGE_DELAY_SECONDS` 仅 dev 生效；`resolve` 返回真实通道绑定。
20. 策略命中统计：`grade_property_tail`/`element_matrix` 在 39 份历史 0 记录文档上的命中率。

> **P2 进度（2026-11-12）**：
> - 第 19 项已完成（environment gating；`resolve` 返回真实通道，配方测试 8 条通过；容器重建后实测 `channel=stable`）。
> - 第 20 项已完成：`scripts/benchmark/strategy_coverage.py` 全量重解析 39 份历史 0 记录文档，产物 `docs/reports/strategy-coverage.{json,md}`。结果：解析成功 8 份（20.51%）、产出记录 8 份（20.51%）、策略命中 3 份（7.69%）；`grade_property_matrix` 命中 3 份/3 条，`grade_property_tail` 与 `element_matrix` **0 命中**。结论：历史 0 记录文档的恢复主要来自绑定列解析（5 份），尾部/元素矩阵策略无增益，后续不再优先扩展，保留作为兜底。
> - 第 17 项已完成：文档库搜索/状态筛选/分页、运行记录分页、原文预览版面框叠加、审核 Finding「定位原文」、词典 JSON 导入 UI（后端 `/v1/dictionary/import` + 宿主机挂载持久化）。新增 E2E 用例覆盖搜索与导入对话框，契约测试 3 条通过。
> - 第 18 项已完成：新增 `web` 容器（nginx 静态资源 + `/v1` SSE 反代，端口 15173）与 K8s `web` Deployment/Service/Ingress（`hanson.local`）；agent session、配方/词典数据挂 PVC；全部 K8s 就绪探针切换 `/readyz`。compose/K8s YAML 校验通过，web 反代实测 200。

## 6. 口径统一建议（单一事实源）

| 口径 | 现状 | 建议 |
|---|---|---|
| Field F1 | 0.3489 / 0.4933 / 0.6020 / 0.80 四套 | 固定两类：`legacy-regression F1`（发布门禁 ≥0.60）与 `gold F1`（Phase 3 ≥0.80） |
| 静默错误 | ≤5% / ≤3% / ≤2% | 发布门禁 ≤3%；Phase 3 ≤2%；M8 历史 ≤5% 标注为旧口径 |
| 金标数量 | ≥30 份 vs 2 份 | Phase 3 前累计 ≥30；此前只报告不门禁 |
| 审批语义 | 人工 approve vs 自动晋升 | 决策后写入 decision-log，代码与三份文档同步 |
| 服务数量 | 七服务 vs layout_api | 明确“业务微服务 7 个 + 外部模型服务 N 个” |

## 7. 核查结论

1. **建设成果真实存在**：七服务、配方/parser 资产、沙箱、审核修复闭环、前端六页均可运行；本轮指标治理、L3、门禁有完整证据链。
2. **不能宣称"全部优化结束"**：P0 问题 6 项未闭环，其中审批语义、registry 持久化、fake 防误用属于上线阻断项；M8 验收口径与 0.80 目标需要正式修订。
3. **最大风险不是功能缺失，而是"口径漂移"**：多套指标门槛、旧基线当门禁、自动晋升绕过人工，会让后续迭代失去判断标准。
4. 建议按 P0 → P1 → P2 顺序执行；P0 完成后，再启动 Phase 3 的 0.80 与灰度工作。
