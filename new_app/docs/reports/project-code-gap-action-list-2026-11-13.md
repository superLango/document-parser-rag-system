# 项目功能代码调研与差距处置清单

> 生成时间：2026-11-13
> 输入材料：
> - 外部评审稿《Hanson 标准解析平台 目标路线、真实实现与优化建议》v1.2（只读评审稿）
> - [项目全维度核查报告](project-full-audit-2026-11-12.md)
> - [项目差距清单报告](project-gap-report-2026-11-13.md)
> - 当前工作区代码与最新运行报告（full-audit50、scale-gate、M8-loadtest 等）
> 方法：**以代码为准**逐条核对评审稿断言，先给出“报告 vs 代码”结论，再与现有差距清单合并为统一处置清单。
> 标记：属实 / 部分属实 / 不成立 / 无法复核

## 0. 一句话结论

评审稿的核心判断成立：**当前系统是“解析—复核—终止”的线性主链路，加一条人工触发的反馈修复支路；“复核发现问题后自动改配方/矩阵并重解析”没有接通，人工审核也没有进入 Run 状态机。** 基础能力不差，差的是闭环、失败边界和质量证据。

合并两份报告后，真正的上线阻断项是 4 个 P0：闭环未接通、人工审核未进状态机、未匹配表仍走默认配方、L3 代码补丁直推 stable 且审批端点无鉴权。其余是质量/数据、版本治理、新版本适配和工程运维缺口。

## 1. 对评审稿的核对结论

抽查 30 余条关键断言，绝大多数与当前代码一致。需要修正或补充的有 5 处：

| # | 评审稿说法 | 代码核对结论 | 影响 |
|---|---|---|---|
| 1 | ReviewAgent 一次拿全量 records/evidence，压缩后证据残缺 | **部分属实**：ReviewService 确实把全量 records/evidence 放进 AgentTask，但 [review.py](../../services/agent/agents/review.py#L62-L80) 在调用模型前只取 `records[:50]`、`evidence[:100]`，并对表格采样。模型看到的证据比“压缩后”更少。 | 结论成立，且问题更早：不是上下文压缩导致，而是 Agent 层主动截断 |
| 2 | 当前 stable `parser_core@1.0.13` | **不成立/已过时**：当前 `data/assets/registry.json` 为 `stable=1.0.22`、`candidate=1.0.14`。候选指针反而低于 stable，疑似测试/发布残留。 | 版本治理必须增加“候选不得落后于 stable”的校验 |
| 3 | 配方 manifest 的 tests 为空 | **属实且更严重**：70 个配方 manifest 中 **70 个 tests 为空**（不只是“很多”）。 | “一版一测试”不是优化项，是发布门禁前置条件 |
| 4 | 源 Excel 词典 9206 行/76 类/1077 项/1158 方法 | **无法复核**：当前工作区只能确认 new_app 侧 `2203 条/78 类/1045 项/1080 方法`；源 Excel 不在工作区。 | 词典差异需另取源文件核对，不能直接写入结论 |
| 5 | 配方 entrypoint 可在沙箱执行 | **属实但未使用**：runner 支持 entrypoint，[runner.py](../../services/sandbox/runtime/runner.py#L81-L110) 有完整执行路径；但 70 个配方 manifest 的 `entrypoint` **全部为 null**。 | L2 插件通道“有能力、无资产”，新版本适配需要补首批 entrypoint |

## 2. 逐条代码核对表

### 2.1 闭环与状态机

| ID | 评审稿断言 | 结论 | 代码证据 | 说明 |
|---|---|---|---|---|
| C-01 | 主链路只有 OCR/routing/sandbox/review，没有 repair 阶段 | 属实 | [workflow.py](../../services/orchestration/workflow.py#L1050-L1084) | 四阶段 + finalize，无 REPAIRING/REPARSING |
| C-02 | REVIEW_FAILED 是终态 | 属实 | [state.py](../../services/orchestration/state.py#L20-L46) | `REVIEW_FAILED: set()` |
| C-03 | 没有 HUMAN_REVIEW / HUMAN_APPROVED / REJECTED | 属实 | [state.py](../../services/orchestration/state.py#L4-L17) | 仅 13 个状态 |
| C-04 | 低置信只写 `needs_human` 事件，不改状态 | 属实 | [workflow.py](../../services/orchestration/workflow.py#L190-L199) | 仍继续进入沙箱 |
| C-05 | 无 assignment 时默认 `mechanical_properties_v1@1.0.0` | 属实 | [workflow.py](../../services/orchestration/workflow.py#L658-L664)、[runner.py](../../services/sandbox/runtime/runner.py#L174-L188) | runner 还会写 `RECIPE_FALLBACK` 诊断，但记录照常产出 |
| C-06 | ReviewAgent 只作建议，deterministic error 才 fail | 属实 | [review/service.py](../../services/review/service.py#L84-L96) | model error 只降级为 warn |
| C-07 | `_auto_feedback` 只建 DOC-* feedback，不调用 process | 属实 | [workflow.py](../../services/orchestration/workflow.py#L896-L908)、[feedback/service.py](../../services/orchestration/feedback/service.py#L87-L91) | 创建后停在 `open` |
| C-08 | 反馈修复需人工触发 | 属实 | [FeedbackPanel.tsx](../../web/src/components/feedback/FeedbackPanel.tsx#L42-L43)、[feedback.ts](../../web/src/api/feedback.ts#L23-L24) | UI 有“处理”按钮；无自动触发 |
| C-09 | L1 表修复已实现 | 属实 | [feedback/service.py](../../services/orchestration/feedback/service.py#L306-L307)、[_process_l1](../../services/orchestration/feedback/service.py#L1234-L1295) | `decision=data` 走 `_process_l1` |
| C-10 | L2 recipe patch 已实现 | 属实 | [feedback/service.py](../../services/orchestration/feedback/service.py#L318-L340) | recipe scope 走候选补丁 + 沙箱验证 |
| C-11 | L3 approve_code 直接 promote 到 stable | 属实 | [feedback/service.py](../../services/orchestration/feedback/service.py#L1592-L1662) | 发布后直接 `channel=stable` |
| C-12 | L3 只查 confirm/scope/guard/files | 属实 | [feedback/service.py](../../services/orchestration/feedback/service.py#L1866-L1879) | 无 tests/regression/shadow 要求 |
| C-13 | approve-code 公开、无鉴权、actor 自报 | 属实 | [api_gateway/main.py](../../services/api_gateway/main.py#L339-L345)、[feedback.py](../../packages/contracts/src/hanson_contracts/feedback.py#L186-L191) | `actor/reason/confirm` 均由请求体传入 |

### 2.2 版本、资产与治理

| ID | 评审稿断言 | 结论 | 代码证据 | 说明 |
|---|---|---|---|---|
| C-14 | 配方 manifest tests 为空 | 属实且更严重 | `data/recipes/**/manifest.json` | 实测 70/70 为空 |
| C-15 | `package.py` 的 digest 只算 manifest | 属实 | [package.py](../../services/recipe_registry/package.py#L58-L69) | 不含 tests/模板/代码文件 |
| C-16 | registry 是单 JSON + threading.Lock | 属实 | [registry.py](../../services/recipe_registry/registry.py#L1-L58) | 无跨进程/多副本事务 |
| C-17 | chemical 44 个版本、parser 23 个版本 | 属实 | 目录统计 | chemical 44，parser_core 1.0.0–1.0.22 |
| C-18 | 当前 chemical stable 1.1.12 / candidate 1.1.42 | 属实 | `data/recipes/registry.json` | — |
| C-19 | 当前 parser stable 1.0.13 | 不成立/已过时 | `data/assets/registry.json` | 实际 stable 1.0.22、candidate 1.0.14 |
| C-20 | recipe entrypoint 可执行 | 属实但未使用 | [runner.py](../../services/sandbox/runtime/runner.py#L81-L110) | 0/70 配方配置 entrypoint |
| C-21 | EditionProfile / AdaptationController 不存在 | 属实 | 全库无匹配 | 新版本适配未落地 |

### 2.3 Agent、Context、OCR、Matcher

| ID | 评审稿断言 | 结论 | 代码证据 | 说明 |
|---|---|---|---|---|
| C-22 | Context L1/L2/L3 压缩有损 | 属实 | [manager.py](../../services/agent/context/manager.py#L197-L222) | L1 弹历史、L2 换占位、L3 丢非 immutable 内容 |
| C-23 | `check_lossless` 未在主循环调用 | 属实 | 仅 [manager.py](../../services/agent/context/manager.py#L225) 定义 | harness 无调用 |
| C-24 | ReviewAgent 证据覆盖不足 | 属实 | [review.py](../../services/agent/agents/review.py#L62-L80) | 只送 50 条记录、100 条证据 |
| C-25 | OCR 质量只看空页/无表 | 属实 | [ocr/service.py](../../services/ocr/service.py#L194-L202) | 无表级/单元格置信度 |
| C-26 | matcher 单分数、无 top1/top2 margin | 属实 | [matcher.py](../../services/recipe_registry/matcher.py#L16-L22)、[L146-L161](../../services/recipe_registry/matcher.py#L146-L161) | 0.9/0.6 阈值，best score |
| C-27 | RouterAgent 默认关闭 | 属实 | [orchestration/config.py](../../services/orchestration/config.py#L32) | `route_agent_enabled=False` |
| C-28 | Review 规则有 M5-VALUE/UNIT/TABLE，仍缺字典/方法/范围语义校验 | 属实 | [rules.py](../../services/review/rules.py#L172-L237) | 有值格式/单位/计数检查；无字典/方法/范围逻辑 |
| C-29 | observability 只有占位 | 属实 | [hanson_obs/\_\_init\_\_.py](../../packages/observability/src/hanson_obs/__init__.py) | 仅 `__version__`，无 OTel/Prometheus 依赖 |
| C-30 | 本地安全边界弱 | 属实 | [docker-compose.yml](../../deploy/compose/docker-compose.yml#L64)、[L86-L107](../../deploy/compose/docker-compose.yml#L86-L107)、[L132-L212](../../deploy/compose/docker-compose.yml#L132-L212) | 18000–18006 暴露；挂 docker.sock；弱口令；无应用层鉴权 |
| C-31 | 金标 2/89、F1 0.6025、静默 2.62% | 属实 | [gold-standards.json](gold-standards.json)、[scale-gate.md](scale-gate.md#L8-L9) | 发布线刚好压 0.60 |
| C-32 | 词典 new_app 2203/78/1045/1080 | 属实 | `data/dictionary/manifest.json` | 源 Excel 统计无法复核 |

## 3. 统一差距处置清单

> 合并评审稿（闭环/状态机/新版本适配）与 [项目差距清单报告](project-gap-report-2026-11-13.md)（里程碑验收/指标/W1–W6）。同一问题只保留一个 ID，来源列标注出处。

### 3.1 P0：可信闭环（冻结期必须先做）

| ID | 差距 | 来源 | 当前实现 | 处置动作 | 关闭条件 |
|---|---|---|---|---|---|
| P0-01 | review→repair→reparse 未接通 | 评审稿 4.1 | 主链路无 REPAIRING/REPARSING；REVIEW_FAILED 终态 | 新增 `REVIEW_FINDINGS → REPAIRING → REPARSING → REVIEWING` 有界循环（最多 2 次），记录 before/after/diff/regression | 循环可跑；无改善/回归转人工；每轮有证据 |
| P0-02 | 人工审核未进 Run 状态机 | 评审稿 4.2 | 无 HUMAN_REVIEW；STRUCTURED_READY 终态 | 新增 `HUMAN_REVIEW → HUMAN_APPROVED/REJECTED`；未 approved 不得导出/下游；审核人/意见/时间进 Run 事件 | 100% Run 经人工门；未批准导出被拒绝 |
| P0-03 | 未匹配/低置信表仍走默认配方 | 评审稿 4.3 | 无 assignment 时 `mechanical_properties_v1@1.0.0`；runner 照常产出记录 | 删除默认 mechanical fallback；新增 `UNROUTED` 状态/事件/页面/测试；无配方依据不产出记录 | 未匹配表 0 记录；UNROUTED 可查；评测“有记录”不再等于“蒙对” |
| P0-04 | L3 直推 stable + 审批端点无鉴权 | 评审稿 4.5 / v1.2 增量 | `approve_code` 发布后直接 `channel=stable`；只查 confirm/scope/guard/files；公开端点、actor 自报 | 改为 candidate → tests → 旧版回归 → shadow → stable；`code_release_blockers` 增加 tests/regression/目标文档；增加鉴权与 `verification_id`；前端接审批 | L3 100% 经 tests+回归+shadow；无鉴权/未确认无法发布；stable 可回滚 |

### 3.2 P1：质量、数据与治理

| ID | 差距 | 来源 | 当前证据 | 处置动作 | 关闭条件 |
|---|---|---|---|---|---|
| P1-01 | 自动 feedback 不自动 process | 评审稿 4.6 | `_auto_feedback` 只 create；UI 需人工点“处理” | 对 `DOC-*` / auto_repairable 自动进入 process，保留人工 approve；加预算（次数/token/时长），超预算转人工 | 自动修复率 ≥60%，其余转人工 |
| P1-02 | 金标 ≥30 未达成 | 差距清单 GAP-01 | 仅 2 份；严格 2/89 | 以 `accepted_snapshot` 累计；门禁分 legacy/金标两级 | ≥30 份且金标门禁启用 |
| P1-03 | 50 份标准 40/50，10 份 0 记录 | 差距清单 GAP-02 | full-audit50：`REVIEW_FAILED`/`FAILED` 10 份 | 逐份归因（版面/表格/配方/OCR），先修可自动修的表结构 | Phase 2 ≥45/50 |
| P1-04 | 原文命中率仅 70.03%/70.78% | 差距清单 GAP-03 | full-audit50 | 列级继承 + 记录清理 + 证据回查 | ≥99% |
| P1-05 | 重复键 368 条/261 组 | 差距清单 GAP-04 | full-audit50 | `column_conditions` + 条件绑定 + 脚注后缀并入牌号键 | 文档内重复键 ≤5 组 |
| P1-06 | Phase 3 指标未达 | 差距清单 GAP-05 | F1 0.6025、静默 2.62% | 先保 0.60/3%，再治理到 0.70/2%，最后 0.80/2% | F1 ≥0.70（Phase 2）/≥0.80（Phase 3）；静默 ≤2% |
| P1-07 | 扫描件成功率未统计、灰度未执行 | 差距清单 GAP-06/07 | M8-loadtest 无扫描样本；M8 灰度为演练 | 补扫描件 fixture 与统计；生产按 10%/50%/100% 执行并留回滚记录 | 扫描件 ≥90%；灰度三步有记录 |
| P1-08 | 版本治理失控 | 评审稿 4.7 | 70/70 manifest 无 tests；digest 只算 manifest；单 JSON + 锁；parser candidate 1.0.14 < stable 1.0.22 | 一版一测试；digest 覆盖 manifest+代码/测试/模板；同一配方一个 active candidate；清理/归档旧候选；候选不得落后 stable | 100% candidate 有 tests；digest 全包；候选指针单调 |
| P1-09 | Context 有损 + ReviewAgent 截断 | 评审稿 4.8（已修正） | L1/L2/L3 有损；`check_lossless` 未调用；模型只看 50 条记录/100 条证据 | 证据正文 immutable；压缩只压摘要/重复结构；大文档按表/批审核；主循环调用 `check_lossless` | 关键证据不丢；审核覆盖可量化 |
| P1-10 | OCR 表级质量门禁缺失 | 评审稿 4.9 + W2 | `assess_quality` 只看空页/无表 | 增加表头完整度、数字比例、合并异常、单元格置信度；低质量表不进入配方 | 低质量表 0 进入配方；TEDS/表头命中率有基线 |
| P1-11 | matcher 无 margin、RouterAgent 默认关 | 评审稿 4.10 | best score + 0.9/0.6；`route_agent_enabled=False` | top-k + margin；低置信转 RouterAgent/人工；补表题/上下文特征 | unknown/低置信率下降；回归稳定后开启 |
| P1-12 | 新版本适配未落地 | 评审稿第七章 | 无 EditionProfile/DriftAnalyzer/AdaptationController；entrypoint 0/70 | 引入 EditionProfile；L0/L1 自动，L2/L3 候选包 + 沙箱 + 人工；旧版本继续 pin 旧 edition | 新版本覆盖 ≥90%；旧版回归不下降 |

### 3.3 P2：工程、运维与安全

| ID | 差距 | 来源 | 当前证据 | 处置动作 | 关闭条件 |
|---|---|---|---|---|---|
| P2-01 | Run 无 `progress` 字段 | 全维度核查 AUD-A04 | orchestration 无 progress | 增加字段、API、前端展示 | 长文档可看进度 |
| P2-02 | 并发 4 × 三窗口未压测 | M5 验收 | M8-loadtest 仅 run 并发 3 | 补 32K/64K/128K × 并发 4 组合压测 | 报告回填 D-005 |
| P2-03 | M0 K8s/ADR/uv.lock 未完成 | 全维度核查 M0 | K8s 未正式跑；无 `uv.lock`；无 ADR | 正式部署验证；补 ADR 与锁文件 | M0 验收关闭 |
| P2-04 | V-007 生产 K8s 配置未回填 | decision-log V-007 | 待切换窗口 | 节点池/副本/HPA/存储确定后回填 | 配置入库 |
| P2-05 | 可观测性只有占位 | 评审稿 4.10 | `hanson_obs` 仅 `__version__`；无 OTel/Prometheus | 接 trace + 指标 + 日志；关键阶段打点 | P0 故障可定位；SLO 可观测 |
| P2-06 | 安全边界弱 | 评审稿 4.10 | 18000–18006 暴露；docker.sock；弱口令；无应用层鉴权 | 反向代理鉴权；rootless sandbox；密钥管理；最小端口暴露 | 无鉴权不可调用；sandbox 不挂宿主 socket |
| P2-07 | M2 profile 命名与文档不一致 | 全维度核查 M2 | 待复核 | 统一 profile 命名或更新文档 | 代码/文档一致 |
| P2-08 | L2 entrypoint 通道未使用 | 评审稿 7.5 | 0/70 配方配置 entrypoint | 为首批 L2 表型补 entrypoint + 测试 | 至少 1 个 L2 插件跑通 |

### 3.4 W1–W6 产品能力缺口

> 来源：[implementation-plan-current-vs-target.md](implementation-plan-current-vs-target.md)。与上面 P0/P1 并行，但不应优先于 P0。

| 工作包 | 状态 | 已落地 | 未落地 |
|---|---|---|---|
| W1 版面服务化 | 基本完成（layout-first 替代） | layout_api、layout-first、table crop、compose/k8s 配置 | 独立开关、`LAYOUT_API_TOKEN`、`/healthz` 权重 SHA |
| W2 表格三级策略 | 部分完成 | Tier 3 VLM 兜底；无框线表由版面 + GLM 处理 | `text_tables.py`（Tier 1）；TATR/PP-Table/Docling（Tier 2）；表格质量分 |
| W3 表头/条件/单位继承 | 部分完成 | 配方 1.6.1 条件绑定；header_paths 父级拼接 | `column_units/column_conditions/column_elements`；`_extract_unit` 列单位；双口径 F1 |
| W4 金标与回归门禁 | 基本完成（2026-11-14） | gold registry、gold_eval（F1/静默/覆盖/单位/条件/表型/表头/单元格/TEDS）、`gate_scale.py --require-gold`、CI 契约检查 | 无文本层 PDF 先 GLM 再核对；50 份 + 金标全链路跑通 |
| W5 OCR 韧性与多引擎 | 基本未做 | 超时、重试、layout 熔断、native 回退 | 异步队列；PaddleOCR-VL/MinerU；健康检查与自动降级 |
| W6 灰度与回滚 | 部分完成 | recipe channel、shadow、手动 promote/rollback | `TABLE_ENGINE`；独立开关；10% 灰度自动对比与自动回滚 |

### 3.5 P0 处置进度（2026-11-13）

| ID | 状态 | 实现 | 验证 |
|---|---|---|---|
| P0-01 | 已实现并验证 | 新增 REPAIRING/REPARSING 状态；review 失败或出现可修复 warning 时自动处理 open feedback；候选配方写入 `runs.recipe_override` 并重跑沙箱；最多 2 次；迁移 `0009_run_repair` | 使用 `tests/fixtures/doc-dup-keys-trigger.md` 实测：REVIEWING → REPAIRING → REPARSING → REVIEWING → HUMAN_REVIEW → STRUCTURED_READY；DOC-DUP-KEYS 修复后消失，保留 4 条记录 |
| P0-02 | 已实现并验证 | 新增 HUMAN_REVIEW/HUMAN_APPROVED/HUMAN_REJECTED；`/runs/{id}/accept` 审批、`/reject` 驳回；审核人/意见写入 Run 事件；前端增加审核通过/驳回按钮 | e2e：HUMAN_REVIEW → accept → STRUCTURED_READY；reject → HUMAN_REJECTED；事件序列已确认 |
| P0-03 | 已实现并验证 | 删除 `mechanical_properties_v1@1.0.0` 默认 fallback；无有效 assignment 直接进入 UNROUTED；沙箱只解析已分配表，未分配表输出 UNROUTED_TABLE 诊断 | e2e：未知表文档进入 UNROUTED，未产出记录 |
| P0-04 | 已实现并验证 | `approve-code` 要求 verification_id、通过的验证包、候选测试、无回归；只发布到 shadow，不再直推 stable；新增 `INTERNAL_API_TOKEN` 鉴权 | e2e：无 token/wrong token → 401；correct token 但无验证 → 409 CODE_RELEASE_BLOCKED；stable 仍为 parser_core 1.0.22 |
| 模型服务 | 已完成 | 模型服务器切换到 192.168.1.35；Layout 9978、GLM-OCR 9977、Qwen3.6-35B-A3B-FP8 9988 已启动；compose/k8s/.env/agent 配置同步 | 三个端口 `/v1/models` 与 `/healthz` 均 200 |
| 回归抽查 | 已完成 | 5 份旧基线文档经人工审核门跑通 | Field F1 0.7721、Value match 0.9848、静默 1.52%、覆盖率 100%、失败 0 |

配套修复（P0-01 触发文档暴露）：
- `DOC-DUP-KEYS` 规则和修复验证改为按 `condition_key` 计数，避免把不同条件下的同牌号同指标误判为重复键；
- JSON Patch `add` 指向 `bindings.conditions`/`row_key`/`strategy_chain` 时自动追加 `/-`，不再替换整个列表；
- `RepairProposal.root_cause` 补齐 `extraction_rule`/`value_parsing`，避免诊断结果被 Pydantic 拒绝；
- 测试文档：[doc-dup-keys-trigger.md](../../tests/fixtures/doc-dup-keys-trigger.md)。

### 3.6 P1 处置进度（2026-11-13）

#### P1-03 失败文档归因（10 份）

逐份读取 `full-runs50.json` 对应 run 的 review findings、routing 产物与 OCR 产物后，根因分为四类：

| 文档 | 状态 | 根因 | 处置 |
|---|---|---|---|
| AMS4108G、AMS4911S、AMS4943M | REVIEW_FAILED | 拉伸表（Tensile/Yield/Elongation）被 `hardness_v1` 以 0.65 分抢占，`mechanical_properties_v1` 仅 0.60；绑定 HB 失败 → 0 记录 | 已修：matcher 支持英文表头别名（tensile strength→rm、yield strength→rp0.2 等），同分时按表头覆盖率决胜；3 份重跑均 STRUCTURED_READY（42/13/3 条记录） |
| GB 24627-2009 | REVIEW_FAILED | 扫描件；旧 OCR 结果丢失表头（力学表只剩“直径”一列）。重建 OCR 后 T36 表头恢复为“直径/抗拉强度Rm/延伸率A”，但 matcher 把 `RmMPa` 当成整词，覆盖率不足被 hardness 0.70 抢占 | 已修：CJK 表头内的拉丁串按单位拆分（`RmMPa` → `rm`），并取消“有部分命中仍惩罚”；重跑 STRUCTURED_READY（2 条记录） |
| YST 255-2009 | REVIEW_FAILED | 扫描件带红色骑缝章；GLM 把化学成分表识别成“牌号为列、元素为行”的转置表，并夹带 101 行的“钴板的取样”幻觉循环 | 已修：OCR 增加幻觉循环检测（整页重识别兜底）；OCR profile 识别数据列中的元素行；sandbox 转置配方支持“牌号/牌号 + 元素标签”合并表头与右移一列取值。重跑 STRUCTURED_READY（6 个牌号 Co9998…Co9830，Co/C/S/Mn 等成分正确） |
| GBT 3274-2017 | REVIEW_FAILED | PDF 字体 cmap 损坏，文本层整页生僻字（“犐犆犛…”）；GLM 在块级裁剪图上把 5.1 条款循环伪造为 101 行“5.1.x 镍” | 已修：乱码文本层强制 GLM；块级输出重复循环检测命中后改用整页 220dpi GLM（实测整页输出干净）。该标准本身不给出化学成分/力学表（引用 GB/T 700、GB/T 1591），重跑正确进入 UNROUTED（43 张表：39 未路由、2 非记录表、2 无可用 measure） |
| AS4076、ASME SA264 | REVIEW_FAILED / UNROUTED | 两份标准本身没有力学性能表（CSR 试验规程 / 复合板引用母材标准） | 已修：Review 的 `DOC-NO-APPLICABLE-TABLES` 判定改为“所有表都不可产出记录”（未路由、非记录表、或配方绑定的 measure 全部缺失）。AS4076 重跑 UNROUTED（0 记录 / 49 表：44 未路由、5 无可用 measure）；ASME SA264 保持 UNROUTED |
| GBT 3880.2-2012、NBT 47014 | FAILED（OCR_BACKEND_UNAVAILABLE） | 54/87 页扫描件；编排 OCR 超时 900s。直接测量 54 页 layout-first OCR 耗时 606s，并发时超限 | GBT 3880.2 串行重跑成功（OCR 594s，174 条记录）；NBT 47014（87 页、680 张 OCR 表）在 OCR 超时提升到 2400s 后整篇 888s 完成，STRUCTURED_READY（6 条记录），自动修复一次后通过 |

#### P1-11 matcher margin 与英文表头

- [matcher.py](../../services/recipe_registry/matcher.py)：新增 `_EN_MEASURE_ALIASES`，把 AMS/ASME 表头映射到 `rm`/`rp0.2`/`a`/`z`/`kv2` 等标准 token；
- CJK 表头里的拉丁连写按单位拆分（`抗拉强度RmMPa` → `rm`），修复 GB 24627 这类表头被 hardness 抢占；
- 只在表头零命中时施加覆盖率惩罚；有部分命中时保留得分，同分时先比覆盖率、再比绑定数；
- `MatchResult` 增加 `margin`/`runner_up`，路由产物记录 top1-top2 差；`ROUTE_MARGIN_THRESHOLD` 默认 0（只记录，不改变路由），可按需开启低 margin 转人工；
- 新增测试：`test_english_tensile_table_routes_to_mechanical`、`test_concatenated_symbol_header_routes_to_mechanical`；
- RouterAgent 默认开启（`ROUTE_AGENT_ENABLED=true`），但只处理“高质量性能/成分表”：quality ≥0.7、profile ∈ {mechanical_properties, chemical_composition}、无 prose_fragment/单列/无数字等标签，且每篇最多 8 张；模型置信度 <0.7 不采纳，未覆盖的表仍转人工；
- 新增测试：`test_select_agent_tables_requires_property_profile_and_quality`、`test_select_agent_tables_is_capped`；
- 10 份失败文档的最终结果：7 份恢复 STRUCTURED_READY（AMS4108G 42、AMS4911S 13、AMS4943M 3、GB 24627 2、GBT 3880.2-2012 174、YST 255 6、NBT 47014 6）；AS4076、ASME SA264、GBT 3274 正确进入 UNROUTED（标准本身无适用记录表）。全量 50 份基线待统一重跑后更新。

#### P1-05 重复键（第一批）

- [builtin.py](../../services/sandbox/runtime/builtin.py)：条件列（供应状态/试样状态/厚度/方向）支持合并单元格向下继承，续行为空时沿用上一行条件；
- 修正 `_nonvalue_label` 把 `H14`/`H24` 当作元素符号丢弃的问题（铝合金状态码全部丢失是重复键的主要来源）；
- 离线复算 GBT 3880.2-2024：重复键组 300 → 38，重复记录 996 → 79；
- E2E 回归（新文档重跑）：GJB 2351-95 重复记录 103 → 19（重复键 39 → 7）；AMS4050K 24 → 0；GBT 1591 263 → 221；
- 新增测试：`test_merged_condition_cells_are_carried_forward`。

#### P1-10 OCR 乱码检测与表级质量门禁（第一批）

- [layout_first.py](../../services/ocr/adapters/layout_first.py)：新增 `_looks_garbled`/`_document_text_garbled`，按“常用汉字占比 <1% 且 CJK ≥100”识别损坏 cmap；命中后整篇文本块改走 GLM OCR；
- 全量 80 份 GB/GJB 语料复核：仅 GBT 3274 命中，正常文档最低常用字占比 7.98%，无误报；
- 新增 [quality.py](../../services/ocr/algorithms/quality.py)：按表头完整度、数字比例、单列/长文本碎片、重复行、错列等计算表级 `quality` 与 `quality_flags`，写入 OCR 产物；
- 路由阶段新增 `min_table_quality=0.25` 门禁：低质量表不进入配方匹配，记入 routing 的 `filtered_tables`；50 份存量语料中所有产出记录的表 quality ≥0.9，门禁不会误伤有效表；
- 新增测试：`test_garbled_text_layer_is_ocrd_instead_of_reused`、`test_garbled_detector_ignores_normal_text`、`test_quality_scores_record_table_high`、`test_quality_rejects_prose_fragment`、`test_filter_tables_by_quality_splits_buckets`。

#### P1-10 幻觉循环与转置成分表（第二批）

- [layout_first.py](../../services/ocr/adapters/layout_first.py)：新增 `_is_degenerate_ocr`，识别 GLM 的重复循环（同一单元格重复 ≥50%，或 ≥30 行“5.1.x 短文本”式编号）；命中后改用 220dpi 整页 GLM 重新识别，整页仍异常则丢弃异常块并告警；
- [profile.py](../../services/ocr/algorithms/profile.py)：数据列中出现 ≥3 个元素符号（严格匹配 `^[A-Z][a-z]?$`，排除 C45/H14/Co9998 这类牌号）时判为 `chemical_composition`，方向判为 `element_rows`；
- [builtin.py](../../services/sandbox/runtime/builtin.py)：转置配方支持“牌号/牌号”合并表头——元素标签可能落在牌号块内部，值列相对表头右移一列；同时保留 Min/Max 限值列行为；
- [strategies.py](../../services/sandbox/runtime/strategies.py)：`element_matrix` 同步支持该布局，按表头牌号列产出记录；
- 新增测试：`test_degenerate_detector_catches_numbered_loop`、`test_degenerate_table_block_uses_full_page_ocr`、`test_transposed_composition_with_leading_label_columns`、`test_transposed_element_rows_with_merged_grade_label`。

#### P1-10 TEDS 基线（2026-11-14）

- 新增 [teds.py](../../scripts/benchmark/teds.py)：按 `table -> tr -> td` 构建有序树，Zhang-Shasha 树编辑距离，`TEDS = 1 - dist / max(node_count)`；
- [table_gold_eval.py](../../scripts/benchmark/table_gold_eval.py) 增加 `teds` 指标（表头路径命中外再加结构相似度），5 个表格 golden case 基线：`header_path=1.0000`、`TEDS=1.0000`；
- 限制：TEDS 在表网格级别度量，全记录级 TEDS 依赖 P1-02 金标规模（当前暂缓）；
- 新增测试：`tests/algorithm/test_teds.py`（4 项：完全相同、列缺失、行缺失、空表）。

#### P1-08 版本治理（第一批）

- 修正资产注册表陈旧指针：删除 `candidate=parser_core@1.0.14`（低于 stable 1.0.22 的 L3 测试残留），并写入 cleanup 历史；
- `RecipeRegistry.promote(candidate)` 与 `AssetRegistry.promote(candidate)` 增加“候选不得落后 stable”的硬校验（`RECIPE_CANDIDATE_BEHIND_STABLE` / `ASSET_CANDIDATE_BEHIND_STABLE`）；
- 新增 `governance()`：扫描候选落后 stable、candidate/shadow/stable manifest 缺 tests；注册中心启动时输出告警；
- 新增测试：`test_candidate_behind_stable_is_rejected`、`test_governance_reports_missing_tests`。

#### P1-08 版本治理（第二批，2026-11-14）

- 一版一测试：新增共享契约测试 [test_recipe_contract.py](../../tests/contract/recipes/test_recipe_contract.py)，遍历 `data/recipes/*/*/manifest.json` 校验可加载、`recipe_id`/`version` 与路径一致、`tests` 非空；一次性迁移脚本 [govern_recipes.py](../../scripts/recipes/govern_recipes.py) 为全部 manifest 回填该测试并重算 checksum；
- digest 全包：[package.py](../../services/recipe_registry/package.py) 的 `compute_digest` 在 manifest 规范化载荷之外追加 `referenced_paths` 所引用的测试/模板/代码文件内容哈希，manifest 或任一被引文件变更都会改变 digest；
- 候选清理：`RecipeRegistry` 新增 `stale_candidate_versions()` / `archive_stale_candidates()`，低于 stable 的候选移入 `recipes_archive`；`governance()` 新增 `RECIPE_TEST_FILE_MISSING`（引用的测试文件不存在）与 `RECIPE_CANDIDATE_STALE`（候选落后 stable）；
- 运行一致性：digest 现在覆盖 manifest 引用的测试文件，服务镜像必须包含这些文件，否则容器内重算 digest 与 host 不一致（本轮出现 `checksum mismatch: declared=… computed=…` 导致 routing 404）；已在 [deploy/compose/Dockerfile](../../deploy/compose/Dockerfile) 增加 `COPY tests ./tests` 并重建 registry；
- 执行结果：229 个 manifest 全部具备 tests 引用，185 个历史候选版本归档，`governance()` `issues=[]`（0 告警）；
- 新增测试：`test_digest_covers_referenced_test_file`、`test_governance_reports_missing_test_file`、`test_stale_candidates_are_archived`。

#### 金标驱动修复（2026-11-14 晚）

以 `gold_standard_30` 为基准修复解析管线，parser 稳定版 1.0.31 → 1.0.39，mechanical_properties_v1 稳定版 1.6.51，新增 heat_treatment_v1@1.0.0。

已落地：

- **热处理制度通道**：OCR 新增 `heat_treatment` profile（GB/T 3280 附录 C、GB/T 14976 表1）；builtin 新增热处理表解析与“从力学记录热处理条件派生”（GJB/HB）；金标评测新增热处理指标适配。
- **断裂韧度**：hardness_v1 硬过滤（无硬度表头不得接管）；KIC/L-T/T-L/S-L 令牌与绑定；无牌号表的“方向/厚度转条件”；拆分厚度列合并；`ksi√inch` / `MPa√m` 单位。
- **化学成分**：AMS `Element/Min/Max` 合并（区间、≤、≥）；中文元素标签 `镍(Ni)`；`Ni+Co` 组合；合并组标签“杂质含量,不大于”向下传递限值；转置表标签列改为“命中数最多”选取（GB/T 6516）。
- **牌号兜底**：文档级牌号（AMS 7050-T7452 / 6Al-4V / UNS）；“镍-钛 / nickel-titanium / nitinol → NiTi”；UNS 正则排除 `GB/T 24627` 这类标准号。
- **其他**：Bend Factor 表 profile；表头残留“不大于”行跳过；机械强度单值统一 `≥` 语义；热处理行匹配忽略金标不一致的“项目大类”。

验证（金标 F1，重跑快照）：

| 文档 | 修复前 | 修复后 |
|---|---:|---:|
| gbt-6516-2025 | 0（REVIEW_FAILED） | **1.0000**（92/92） |
| gbt-24627-2023 | 0（REVIEW_FAILED） | **1.0000**（15/15） |
| ams-4108g | 0.0000 | **0.9890**（静默 0） |
| ams-4050k | 0.1476 | **0.8994**（静默 0） |
| ams-4911s | 0.2254 | **0.8000** |
| gjb-5040-2001 | 0.62（旧基线） | **0.8368**（最优 run） |
| gbt-14976-2025 | 0.43 | 0.4369（heat F1 **0.8364**） |

剩余阻断项已转为版面问题，清单见 [layout-ocr-issue-list-2026-11-14.md](layout-ocr-issue-list-2026-11-14.md)：漏表/漏页（GBT 5231、GJB 5040 续表、GB/T 1591 续表、ASTM 化学成分首页、HB 20079 化学成分表）、网格错位（ASME SB265 1023 列、SB338/SB575 单列、GB/T 1591 29 vs 17 列等），以及同一 PDF 重跑表格切分不稳定的问题。

补充（同日第二批，parser 1.0.40/1.0.41）：

- **冲击表**：识别“纵向/横向”子表头行并按列绑定方向；重复的“3个试样平均 / 单个试样”列拆分独立记录；无牌号冲击表按旧 schema 填 `全部牌号`；“试样”不再被误当条件列；时间解析排除 `AMS 2772` 这类标准号。
- **AMS 正文热处理**：sandbox runner 增加文档级段落抽取（`solution + precipitation` → 固溶+时效/固溶+过时效/固溶+人工时效；`anneal` → 退火），AMS4050K/4108G/4911S 本地验证分别得到 `固溶+人工时效`、`固溶+过时效`、`退火`。
- **新增验证**：GBT 3280 F1 0.6938（heat F1 **0.9913**，此前仅 82 条化学）；GBT 1591 F1 0.5237（124 条记录，此前无有效力学）。
- 全量 30 份重跑已用 parser 1.0.41 启动，结果回填后刷新门禁报告。

#### P1-01 自动反馈处理与预算（2026-11-14）

- 自动处理：`_auto_repair` 在 `REVIEWING`/`REVIEW_PASSED` 阶段拉取该 run 的全部 `open` feedback（按创建时间），逐条调用 `FeedbackService.process`；`DOC-*` 等自动产生的反馈在 `feedback_from_findings` 中默认 `target.auto_repair=True`，人工提交与人工 approve 路径保持不变；
- 三层预算（[config.py](../../services/orchestration/config.py)）：`auto_feedback_enabled`、`auto_feedback_max_items=3`（次数）、`auto_feedback_token_budget=64000`、`auto_feedback_wall_time_seconds=300`；
- 预算执行：次数由 `feedback_ids[:auto_feedback_max_items]` 截断；token/时长从该 run 的历史 `run.repair.completed` 事件累计（跨重试不重置）；`FeedbackService` 每次 Agent 调用按剩余额度裁剪 `AgentBudget`，剩余不足 1024 token 抛 `FeedbackBudgetExceeded`，HTTP 超时取剩余时长；
- 指标落点：每次自动修复写 `run.repair.completed`（`processed`/`verified`/`tokens_used`/`wall_time_seconds`），自动修复率 = `verified / processed`；可用 `scripts/benchmark/feedback_metrics.py` 汇总；
- 新增测试：`tests/integration/orchestration/test_feedback_budget.py`（5 项：条数上限、1024 token 下限、reset、token 耗尽、时长耗尽）。
- 实测（2026-11-14，4 份重跑）：3 个 run 触发自动修复，共处理 8 条 feedback（3/3/2），消耗 54,668 / 65,225 / 67,844 tokens、209 / 222 / 220 秒；8 条全部终止为 `needs_more_info`（repair proposal 为空操作或缺少 expected_value），`verified=0`，自动修复率 0/8 = 0%，未达 ≥60% 目标；
- 预算说明：token 额度是软上限（末次 Agent 调用可能越过剩余额度，实际用量已记录）；`GJB 5040` 与 `B861-24` 因 token 额度耗尽提前停止，证明预算能截断循环；
- 剩余差距在 repair 提案质量（而非预算控制），作为 P1-01 的后续项。

#### P1-09 Review 证据覆盖（第一批）

- [review.py](../../services/agent/agents/review.py)：不再截取前 50 条记录/100 条证据；改为按表均衡采样（最多 60 条记录），证据优先取采样记录引用的条目（最多 120 条）再补足；
- compact 中新增 `sampling` 统计（总数/发送数），审核覆盖可量化；
- 新增测试：`test_review_agent.py`（大表不再挤掉小表、证据优先命中引用 ID）。

#### P1-04 原文命中率（全量 50 份）

- 全量 50 份重跑完成：47 份 STRUCTURED_READY + 3 份正确 UNROUTED（AS4076/ASME SA264/GBT 3274），0 失败；5158 条记录 / 14517 字段，总耗时 8632s；
- `closeout_standard_audit.py` 复核（`full-audit50.json/md`）：可核对字段 3296（11221 字段因扫描件/乱码文本层不可核对）；牌号命中 83.4%、值命中 97.4%、单位存在 100%、超合理区间 38（0.26%）、重复键 457 组、多条件键 310；
- 审计归一化修复：全角数字/字母先做 NFKC（GBT 1591/3623 等文本层为 `０．２４`/`Ｑ３５５`，原会误判未命中）；文本层可用性改为只看记录自身页面（GBT 14976 表格页是乱码字体编码，相邻正文页正常会把“不可核对”算成抽取错误）；
- 剩余 34 个未命中牌号集中在文本层乱码/编码偏移文档（GBT 3621、GBT 14976、HB 20079、YST 579、GBT 3623），属不可核对面非抽取错误；
- 单位绑定修复：机械表把 OCR 单位行（ksi/MPa/min）当数据行解析，导致 Rm/Rp0.2 被标成 `%`，还把单位行产出伪记录；新增按列吸收单位行、`min/max` 限定词与 `0.2% Offset` 中的 `%` 不再当单位（parser_core 1.0.27）。SB265/SB338/B862/SB575 重跑后超区间值 157 → 38；
- 已知限制：GBT 1591 化学成分表为跨厚度块合并表头，195 组重复键（同牌号两条厚度块记录未带厚度条件），列入下一批表结构治理。

#### P1-05 重复键（全量复核）

- 全量 457 组重复键，主要集中在 GBT 1591（195）、GJB 5040（43）、AMS4967N（42）、ASTM B861-24（30）；
- 归因：多级/跨块表头下同一牌号的厚度分段记录没有进入 `condition_key`，以及单位行被当成数据行；后者已修，前者留作已知限制；
- 第一批的合并条件继承与 H14/H24 修复保持不变。

#### P1-05 重复键（第三批：牌号列选择 + 片段合并 + 重复行消歧，2026-11-14）

- [builtin.py](../../services/sandbox/runtime/builtin.py)：新增 `_pick_key_column`（多个“牌号”候选列时按数据值选真实牌号列，对“质量等级/等级/class/类别”表头罚分）、`_grade_cell_score`、`_key_column_candidates`；
- `_merge_fragments` 重写为“同牌号同条件下，重叠字段值一致或互补才合并，冲突则保留独立记录”，避免跨厚度块续表被误合并或错误拆分；
- 新增 `_disambiguate_duplicate_keys`：同一 `(牌号, condition_key)` 仍有多行且属性冲突时，为后续行追加 `conditions["记录序号"]` 并重算条件键，写 `DUPLICATE_KEY_DISAMBIGUATED` 诊断；
- [runner.py](../../services/sandbox/runtime/runner.py) 在片段合并后调用消歧并写 `DUPLICATE_KEY_DISAMBIGUATED_SUMMARY`；
- 发布 parser_core 1.0.28（stable）并重建 `hanson-sandbox-runtime:local`（`runner.py` 烘焙在引擎镜像内，必须重建才生效），4 份受影响文档重跑：

| 文档 | 记录数 | 重复键组 | 重复记录 | 状态 |
|---|---|---|---|---|
| GBT 1591-2018 | 115 → 114 | 195 → 0 | 471 → 0 | HUMAN_REVIEW（记录就绪，待人工确认） |
| GJB 5040-2001 | 131 → 132 | 43 → 0 | 61 → 0 | HUMAN_REVIEW |
| AMS4967N | 50 → 43 | 42 → 0 | 87 → 0 | HUMAN_REVIEW |
| ASTM B861-24 | 73 → 72 | 30 → 0 | 48 → 0 | HUMAN_REVIEW |

- 4 份均达到“文档内重复键 ≤5 组”的目标（实际 0 组）；全量 50 份审计中的 457 组按此推算降至 147 组（其余 46 份未重跑，仍是 `full-audit50.json` 快照）；
- HUMAN_REVIEW 由 Review 的 warning/error 触发（含模型对 `B` 列把牌号 `R53445` 当成期望值的语义误报），不影响记录本身，需人工确认；
- 新增测试：`test_key_column_prefers_real_grade_over_category`、`test_merge_fragments_merges_identical_overlap_and_keeps_conflicts`、`test_duplicate_key_disambiguation_appends_occurrence_index`。

#### P1-06 F1 / 静默错误（全量 50 份）

- `gate_scale.py --limit 50`（legacy 表格重放）：
  - Field F1 0.608（门槛 ≥0.60）；
  - 值匹配 0.9745，静默错误率 2.55%（门槛 ≤3%）；
  - 覆盖率 0.98，证据率 0.98，p95 120.6s；
  - 金标子集 1 份：F1 0.8092、静默 0、覆盖率 100%；
- 未通过项只有 `failed_runs 1 != 0`：该失败发生在重放传输阶段，数据库中没有对应的失败 run（其余指标正常）。

#### P1-07 扫描件（全量 50 份）

- 22 份无文本层文档：21 份 STRUCTURED_READY + 1 份正确 UNROUTED（GBT 3274），4092 条记录 / 10292 字段，成功率 95.5%；

#### P1-07 表格引擎独立灰度（2026-11-14）

- 独立开关：[config.py](../../services/orchestration/config.py) 新增 `table_engine`（`stable`/`candidate`）与 `table_engine_canary_percent`（默认 0，灰度时 10）、`table_engine_auto_rollback`，与配方 channel 解耦；
- 分桶：`_canary_selected` 用 `sha256(run_id)` 取 0–99 稳定桶，同一 run 结果可复现；`candidate` 与 `stable` 相同或缺失时不灰度；
- 打点：`_maybe_pin_canary_parser` 在沙箱阶段前把命中的 run 固定到 candidate 版本（写入 `run.parser_version`，沙箱按该版本挂载 parser 资产）；
- 自动对比：沙箱成功后 `_evaluate_table_canary` 取该文档最近一次非候选的成功 run 作为基线，复用 `compare_shadow` 比较记录/诊断，结果写 `run.table_engine.canary` 事件；
- 自动回滚：对比不通过且开启 `table_engine_auto_rollback` 时，先 rollback candidate 指针，若仍非 stable 再 promote stable，回滚动作记入同一事件；
- 新增测试：`tests/integration/orchestration/test_table_canary.py`（4 项：0/100 边界、同 run 稳定、约 10% 分布、candidate==stable 不灰度）。

#### 全量基线产物

- 结果：`docs/reports/full-runs-p1.json`
- 日志：`docs/reports/full-rerun-p1.log`
- 审计：`docs/reports/full-audit50.json` / `full-audit50.md`
- 门禁：`docs/reports/scale-gate.json` / `scale-gate.md`
- 重跑：4 份受影响文档（GBT 1591、GJB 5040、AMS4967N、ASTM B861-24）已于 2026-11-14 用 parser_core 1.0.28 重跑并回填新 run_id（状态 HUMAN_REVIEW），其余 46 份沿用 11-13 快照。

#### 30 份金标全量重跑基线（2026-11-14 15:27）

- 30/30 完成、全部有记录（3043 条；`gbt-3280-2015` 触发脚本 1500s 截止后由 run 完成，已从 API 回填 310 条）；平均 342s/份；
- `gold-eval.json`：Field F1 **0.5230**、P 0.6749 / R 0.4269、静默 **17.50%**、覆盖率 100%、单位 98.05%、条件 **33.10%**；表格匹配 0.9604、profile 0.7033、表头 0.4915、单元格 0.4045、TEDS 0.4208；heat F1 0.8267；
- `gold-audit.json`：牌号原文命中 **72.02%**、值命中 **95.46%**、单位 98.16%、不可核对 7520/11996、超区间 60、**重复键 0 组**（P1-05 ≤5 组目标达成）、多条件键 526；
- 失败分类与逐份结果见 [gold-failed-docs.md](gold-failed-docs.md)：A 牌号口径（ISO 5832-3 全 0、Alloy/UNS）、B 漏表/漏行（ASME SB265 等）、C 条件/静默（GBT 5231 等）、D 金标特殊口径（其他元素/总和）；
- 评测侧已修 `canon_grade`（剥离 Alloy、提取描述式牌号内 UNS），F1 0.5213 → 0.5230；管线侧 Ti-6Al-4V 中文标题识别已加、**待部署**。

#### Phase 1 收口代码与 Phase 2 骨架（2026-11-14，未部署）

- **W3 列级元数据**：[contracts.py](../../services/ocr/contracts.py) 的 TableGrid/TableBlock 新增 `column_units/column_conditions/column_elements`；[table_grid.py](../../services/ocr/algorithms/table_grid.py) 从 header_paths 逐级继承（单位不串条件、中文元素标签、Ni+Co）；[builtin.py](../../services/sandbox/runtime/builtin.py) 单位先入库再被单位行覆盖、化学元素列与无牌号条件列兜底；新增 6 项测试；
- **W2 Tier1**：新增 [text_tables.py](../../services/ocr/algorithms/text_tables.py)（词坐标聚行/垂直空白道分列/表格行带/数字与表头校验），接入 [pdf.py](../../services/ocr/adapters/pdf.py) 与 [layout_first.py](../../services/ocr/adapters/layout_first.py) 的“无画线表”兜底，开关 `ocr_text_table_fallback`；30 份金标中 27 份可恢复至少 1 张表；
- **W2 Tier2 PoC**：新增 [table_engine_poc.py](../../scripts/benchmark/table_engine_poc.py)，对比 native/text/docling/tatr/ppstructure 的表数与延迟；当前环境三个结构模型均未安装，结论为“需专用环境安装后评测”；
- **P1-04/05 审计**：[closeout_standard_audit.py](../../scripts/benchmark/closeout_standard_audit.py) 支持 `--records-dir --registry` 离线审计，新增 `documents_with_records/status_counts`；
- **W3 双口径 F1**：[m8_effect_compare.py](../../scripts/benchmark/m8_effect_compare.py) 新增原始符号与归一化符号两套 F1/静默率（`SYMBOL_ALIASES`）；
- **P1-12/Phase 2**：新增 [services/adaptation](../../services/adaptation)（EditionProfile、DriftAnalyzer、AdaptationController、L2/L3 CandidatePackage）；[workflow.py](../../services/orchestration/workflow.py) 在 routing 后接入版本画像/漂移分析与 `run.edition.adaptation` 事件；`bindings.measures[*].aliases` 已由 builtin 消费；orchestration 只读挂载配方数据；
- 开关默认关闭：`EDITION_PROFILE_ENABLED=false`；`ocr_text_table_fallback=true`；
- 测试：ruff 全绿；`pytest tests/algorithm tests/integration/sandbox tests/contract tests/integration/orchestration` 通过（含新增 16 项 adaptation、4 项 text_tables、W3/aliases 用例）。

#### Phase 3 进展（2026-11-14，部分待部署）

- **P2-01 progress**：`runs.progress`（0–100）、迁移 `0010_run_progress`、`STAGE_PROGRESS` 阶段映射（OCR 10 → 沙箱 45 → 复核 80 → 人工 95 → 完成 100）、`RunOut.progress`、前端运行列表显示百分比；新增 2 项单测；
- **P2-05 可观测**：`hanson_obs` 从占位改为进程内 metrics 注册表（counter/gauge/histogram + Prometheus 文本）；`create_app` 统一挂 `/metrics` 与请求计数/耗时中间件；
- **P2-06 安全**：`create_app` 增加可选 `API_AUTH_TOKEN` Bearer 鉴权（默认关闭，health/ready/metrics 白名单）与安全响应头；compose/.env 增加开关；
- **P2-03 K8s/ADR**：新增 `deploy/k8s/base/hpa.yaml`（api-gateway/orchestration/ocr 各 2–6 副本、CPU 70%）并加入 kustomization；decision-log 新增 D-018（依赖源/uv.lock 待工具）、D-019（弹性）、D-020（可观测/鉴权）；V-007 改为部分回填；
- **P2-02 压测**：`window_benchmark.py` 新增 `--concurrency`（默认 4）与 p50/p95/成功率/内存统计，可按 32K/64K/128K × 4 执行；
- **W5 未完成**：多引擎兜底与健康检查已有（hybrid/layout/pdf），大扫描件异步队列仍未实现，留待后续；
- 说明：P2-01/P2-05/P2-06 需在第二轮 30 份重跑结束后统一重建镜像并重启，避免打断在跑任务。

#### P1 完成度总览

| 条目 | 状态 | 说明 |
|---|---|---|
| P1-01 自动 feedback | 完成（实现+预算）/ 修复率未达标 | 自动处理 open feedback，三层预算生效（实测 8 条、3 个 run 被 token 额度截断）；自动修复率 0/8=0%，目标 ≥60%，差距在 repair 提案质量 |
| P1-02 金标 ≥30 | 完成（2026-11-14） | 30 份人工金标、25,377 items；`gold-registry.json` 注册、`gold_eval.py` 评测；旧 2 份金标已标记 superseded |
| P1-03 失败文档归因 | 完成（10/10 有结论） | 7 份 STRUCTURED_READY（AMS4108G 42、AMS4911S 13、AMS4943M 3、GB 24627 2、GBT 3880.2 174、YST 255 6、NBT 47014 6）；3 份正确 UNROUTED（AS4076/ASME SA264/GBT 3274） |
| P1-04 原文命中率 | 完成（全量 50 份） | 牌号 83.4%、值 97.4%、单位 100%、超区间 38/14517（0.26%）；剩余未命中牌号来自乱码文本层，属不可核对 |
| P1-05 重复键 | 完成（4 份重点文档 0 组） | GBT 1591 195→0、GJB 5040 43→0、AMS4967N 42→0、B861-24 30→0（重复记录 471/61/87/48→0）；全量审计按此推算 457→147 |
| P1-06 F1/静默 | 完成（全量 50 份） | F1 0.608、值匹配 0.9745、静默 2.55%、覆盖率 0.98；仅重放传输失败 1 次（无对应 run 失败） |
| P1-07 扫描件/灰度 | 完成（能力就绪，未开生产灰度） | 22 份扫描件成功率 95.5%（21 ready + 1 正确 UNROUTED）；`table_engine` 独立开关 + 10% 稳定分桶 + 对比/自动回滚已实现并测试，默认 `canary_percent=0` 不灰度 |
| P1-08 版本治理 | 完成 | 229 个 manifest 全部具备 tests、digest 覆盖引用文件、185 个旧候选归档、`governance()` 0 告警；镜像补 `COPY tests` 保证容器内 digest 一致 |
| P1-09 Review 证据覆盖 | 第一批完成 | 按表均衡采样 + 证据引用优先 + sampling 统计 |
| P1-10 OCR 表级质量 | 完成 | 乱码检测 + 质量门禁 + 幻觉循环整页兜底 + 转置成分表解析；TEDS 基线：5 个表格 golden case `header_path=1.0000`、`TEDS=1.0000` |
| P1-11 matcher margin | 完成 | 英文/CJK 别名 + 覆盖率决胜 + margin 记录；RouterAgent 默认开启并带质量/置信度护栏 |

验证：`pytest -q` 全量通过；parser_core 1.0.28 已发布 stable，`hanson-sandbox-runtime:local` 重建，orchestration / recipe-registry 重建重启（含 `COPY tests`）；4 份受影响文档重跑并回填 `full-runs-p1.json`；Web 无改动。

## 3.7 执行顺序（2026-11-14 确定）

按用户要求，**50 份标准暂不重跑**，先完成整体开发任务，最后再跑 50 份验收：

1. **等待 30 份金标全量重跑完成**（parser 1.0.41），刷新 `gold-eval.json/md`、gold 门禁与失败文档报告。
2. **Phase 1 收口**：
   - P1-05 重复键 ≤5 组（条件继承/多牌号拆分/冲突消歧）；
   - P1-04 原文命中率 ≥99%（W3 `column_units/column_conditions/column_elements`、跨页/合并表头、证据回查）；
   - P1-06 F1/静默分阶段达标（gold 实测 + 门禁）；
   - W2 补齐（Tier 1 文本坐标聚类、Tier 2 结构模型 PoC、表格质量分）；
   - W3 原始/归一化双口径指标。
3. **Phase 1 之后的后续任务**：P1-12 EditionProfile/DriftAnalyzer/AdaptationController 能力骨架，W4/W6 配套（灰度对比与回滚）。
4. **Phase 2**：L0/L1 自动适配、L2/L3 候选包 + 沙箱 + 人工审 diff；50 份 ≥45/50、F1 ≥0.70、静默 ≤2%。
5. **Phase 3**：W5 异步队列/多引擎、P2-01 progress、P2-02 压测、P2-03 K8s/ADR/uv.lock、P2-04 V-007、P2-05 可观测、P2-06 安全。
6. **最后**：重跑并验收 50 份标准（`full-runs50` + 报告/门禁）。

## 4. 处置路线

> 评审稿建议冻结 2–4 周。本清单采用“Phase 0 冻结期”表述，不承诺具体工期；冻结期只做可信闭环，不新增配方/页面/模型/服务。

### Phase 0：冻结与可信基础

- P0-01 review→repair→reparse 有界闭环；
- P0-02 人工审核进状态机；
- P0-03 删除默认 mechanical fallback，新增 UNROUTED；
- P0-04 L3 candidate/tests/regression/shadow/鉴权；
- P1-01 自动 feedback 自动 process（带预算）；
- P1-08 版本治理：一版一测试、digest 全包、清理候选、修正 parser candidate 指针。

### Phase 1：质量与数据

- P1-02 金标 ≥30（已完成 2026-11-14）；
- P1-03 10 份失败文档归因；
- P1-04 原文命中率；
- P1-05 重复键；
- P1-06 F1/静默分阶段达标；
- P1-09 Context/Review 证据覆盖；
- P1-10 OCR 表级质量；
- P1-11 matcher margin；
- W2/W3 能力补齐。

### Phase 2：新版本适配

- P1-12 EditionProfile + DriftAnalyzer + AdaptationController；
- L0/L1 自动适配；L2/L3 候选代码包 + 沙箱 + 人工审 diff；
- 旧版本继续 pin 旧 edition，新版本使用新 edition；
- W4 金标/CI 与 W6 灰度能力配套。

### Phase 3：规模化与运维

- W5 异步队列、多引擎、健康检查；
- P2-01 progress、P2-02 并发压测、P2-03 K8s、P2-04 V-007、P2-05 可观测、P2-06 安全。

## 5. 验收指标

| 类别 | 指标 | 目标 | 对应项 |
|---|---|---|---|
| 闭环 | review finding 自动修复率 | ≥60%，其余转人工 | P0-01 / P1-01 |
| 闭环 | 自动修复后重解析通过率 | ≥70% | P0-01 |
| 闭环 | 自动修复引入回归率 | ≤2% | P0-01 |
| 人工 | Run 经人工审核比例 | 100% | P0-02 |
| 人工 | 人工审核平均处理时间 | 比纯人工下降 ≥50% | P0-02 |
| 数据 | 金标数量 | ≥30 份 | P1-02 |
| 数据 | 50 份结构化 | Phase 2 ≥45/50；Phase 3 ≥48/50 | P1-03 |
| 数据 | 牌号/值原文命中 | ≥99% / ≥99% | P1-04 |
| 数据 | 文档内重复键 | ≤5 组 | P1-05 |
| 质量 | Field F1 | 发布 ≥0.60；Phase 2 ≥0.70；Phase 3 ≥0.80 | P1-06 |
| 质量 | 静默错误 | 发布 ≤3%；Phase 3 ≤2% | P1-06 |
| 版本 | candidate 测试覆盖 | 100% 有 tests；digest 覆盖全包 | P1-08 |
| 版本 | stable 回滚时间 | ≤5 分钟 | P0-04 / P1-08 |
| 新版本 | 新版本有记录覆盖率 | ≥90% | P1-12 |
| 新版本 | 新版本 F1 相对旧版 | 不低于 -0.01 | P1-12 |
| 运维 | P0 故障数 | 0 | P2-05 / P2-06 |
| 运维 | 扫描件成功率 | ≥90% | P1-07 |

## 6. 风险与决策建议

1. **先修代码，不要把文档改松。** L3 直推 stable、默认 mechanical fallback、无 HUMAN_REVIEW 都是实现与目标不一致，应改代码或正式登记决策，不能用“文档已更新”掩盖。
2. **P0 未完成前不放开 L2/L3 代码适配。** 否则新版本适配会把“不可信闭环”放大到代码层。
3. **金标是 0.80 的硬瓶颈。** 严格合格仅 2/89，必须用 `accepted_snapshot` 累计人工审核样本；在此之前 0.80 只能作为 Phase 3 目标，不能当发布门禁。
4. **候选指针异常要先修。** parser 出现 `candidate 1.0.14 < stable 1.0.22`，说明候选/发布通道有测试残留；版本治理要先于 L3 继续发布。
5. **W2/W3 不应优先于 P0。** 表格能力和列级继承能提高命中率，但闭环和人工门不修，新增能力仍无法证明“没修坏”。

## 7. 证据索引

### 代码

- 主链路：[workflow.py](../../services/orchestration/workflow.py)、[state.py](../../services/orchestration/state.py)
- 反馈修复：[feedback/service.py](../../services/orchestration/feedback/service.py)、[feedback/api.py](../../services/orchestration/feedback/api.py)
- 审核：[review/service.py](../../services/review/service.py)、[review/rules.py](../../services/review/rules.py)
- Agent/Context：[harness.py](../../services/agent/harness.py)、[context/manager.py](../../services/agent/context/manager.py)、[agents/review.py](../../services/agent/agents/review.py)
- OCR：[ocr/service.py](../../services/ocr/service.py)、[adapters/pdf.py](../../services/ocr/adapters/pdf.py)、[adapters/layout_first.py](../../services/ocr/adapters/layout_first.py)
- 配方/资产：[matcher.py](../../services/recipe_registry/matcher.py)、[registry.py](../../services/recipe_registry/registry.py)、[package.py](../../services/recipe_registry/package.py)、[assets/registry.json](../../services/recipe_registry/data/assets/registry.json)
- 沙箱：[workspace.py](../../services/sandbox/workspace.py)、[runtime/runner.py](../../services/sandbox/runtime/runner.py)
- 安全/部署：[docker-compose.yml](../../deploy/compose/docker-compose.yml)
- 可观测：[hanson_obs](../../packages/observability/src/hanson_obs/__init__.py)

### 报告

- [项目全维度核查报告](project-full-audit-2026-11-12.md)
- [项目差距清单报告](project-gap-report-2026-11-13.md)
- [最新 50 份审计](full-audit50.md)
- [发布门禁](scale-gate.md)
- [金标](gold-standards.json)
- [M8 验收](../acceptance/M8.md)
- [方案对比](implementation-plan-current-vs-target.md)
