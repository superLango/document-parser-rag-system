# 文档解析平台收尾测试报告

> 日期：2026-11-12
> 分支：`new_doc_parse`
> 环境：Compose 生产镜像（`hanson-new-app:local` + `hanson-sandbox-runtime:local`）
> 模型：Qwen3.6-35B-A3B-NVFP4（agent/review）、GLM-OCR（扫描件 OCR）
> 结论：**分支与全链路门禁全部通过；新旧字段级 F1 未达 0.80 目标，剩余差距已定位并记录**

## 1. 结论摘要

| 维度 | 结果 | 判定 |
|---|---|---|
| 单元/集成测试 | 102 项，全部通过（Docker 相关 4 项在容器内跳过） | 通过 |
| API/状态机/异常分支 | 18/18 通过 | 通过 |
| 真实 PDF 全链路 | 40 份；34 份结构化就绪（85%）；6 份失败（28–37 页大扫描件 OCR 超时/后端不可用） | 有条件通过 |
| 旧文档重建解析 | 60 份，0 失败，覆盖率 100% | 通过 |
| 新旧字段对比（60 份） | F1 0.5153；Value match 0.8959；静默错误 10.41% | 未达目标 |
| 新旧字段对比（M8 同 12 份） | F1 0.5497（基线 0.3489，+57.5%）；p95 73.91s（基线 74.97s） | 显著改善，未达 0.80 |
| 性能压测 | 185 请求，0 错误，最大场景 p95 2.9s | 通过 |
| 切换/回滚演练 | 切旧 455ms，回切 475ms，旧 Web 200 | 通过 |

上线判定建议：**功能与稳定性可上线；解析质量按灰度观察，大扫描件采用异步批处理，字段 F1 需在下一迭代继续收敛到 0.80。**

## 2. 测试环境与部署

| 项 | 值 |
|---|---|
| 编排 | Docker Compose，7 个服务 + Postgres/Redis/MinIO |
| 镜像 | 应用镜像与沙箱运行时均从当前源码重新构建，非旧镜像 |
| 服务 | api-gateway:18000、orchestration:18001、ocr:18002、agent:18003、sandbox:18004、recipe-registry:18005、review:18006 |
| 配方 | stable 通道：chemical/mechanical/hardness/chemical_element_rows 1.1.0，其余 1.0.0 |
| 测试入口 | `scripts/benchmark/closeout_e2e.py`、`scripts/benchmark/m8_effect_compare.py`、`scripts/benchmark/m8_loadtest.py` |
| 生产模式校验 | 单元测试在 `hanson-new-app:local` 容器内执行；E2E 仅通过网关 API，不直连内部服务 |

## 3. 测试范围与用例清单

### 3.1 单元与集成测试（102 项）

覆盖模块：OCR 表格算法、表型识别、配方包/注册表/匹配、沙箱运行时契约、沙箱执行器、编排状态机、对象存储、Agent 上下文/路由/审核规则、反馈修复、健康检查。

本次新增用例：

| 用例 | 目的 |
|---|---|
| `test_single_letter_elements_match_exact_columns` | C/P/S 等单字符元素列可抽取，且 C 不误吃 Cr |
| `test_header_symbol_overrides_recipe_binding` | KV2/KU2、HBW/HB 以表头符号为准 |
| `test_sentence_like_row_keys_are_rejected` | 注释长句不再成为牌号 |
| `test_transposed_element_rows_become_condition_records` | 元素行（熔炼/成品分析）布局 |
| `test_element_columns_layout_produces_one_record_per_row` | 元素列布局 |
| `test_grade_less_chemical_table_gets_synthetic_record` | 无牌号化学成分表兜底 |
| `test_numeric_grades_use_material_column` | “常用材料”列 + 45/35 数值牌号 |
| `test_negative_composition_values_are_ignored` | 成分偏差表负值不进入成分记录 |
| `test_text_layer_pdf_uses_native_backend` | 文本层 PDF 走本地解析 |
| `test_image_only_pdf_falls_back_to_vision_model` | 扫描件回退 GLM |
| `test_symbols_with_units_route_to_mechanical` | σb N/mm² 等带单位符号正确路由 |
| `test_composition_tolerance_table_is_admin` | “允许偏差”表不进入成分解析 |
| `test_model_errors_are_advisory` | 模型审核错误降级为警告，不阻断 |
| `test_state_machine` REVIEW_FAILED | 审核门禁终态与迁移 |

### 3.2 API/状态机/异常分支（18 项，全部通过）

1. 网关健康
2. 空文件上传 400
3. 重复上传按 sha256 去重
4. 非法配方通道 422
5. 不存在的文档创建 run 404
6. 不存在的 run 404
7. 不存在的配方 404
8. 词典查询
9. 运行中取消
10. 取消后 result 返回 200（result=null）
11. 取消后 records 404
12. 正常路径 STRUCTURED_READY
13. 时间线阶段顺序 ocr→routing→sandbox→review
14. 产物清单
15. 不存在的页图 404
16. **审核门禁：确定性负值 → REVIEW_FAILED**
17. SSE 事件流（stage.started/completed/completed/done）
18. 删除带活动 run 的文档（204 → 文档 404 → run 删除）

### 3.3 真实 PDF 全链路（40 份）

来源与覆盖：

| 类别 | 份数 | 说明 |
|---|---|---|
| 采购规范/技术协议 | 25 | 旧项目 reparse20 原件（去重后） |
| 国家标准 GB | 4 | 含 GB/T 1220、GB/T 1591 等 |
| 国军标 GJB | 3 | 含 GJB 2294A、GJB 1538A 等 |
| 美国标准 ASTM/AMS | 4 | 含 AMS 4945J、ASTM B381 等 |
| 行业标准 YS/HB | 2 | YS/T 255、HB 20079 |
| 企业标准 | 1 | GGX-FJLA-1-22 |
| 国际标准 ISO | 1 | ISO 5832-2 |

流程：上传 → 创建 run → OCR（文本层本地 / 扫描件 GLM）→ 配方路由 → 沙箱容器解析 → 规则+模型审核 → 结构化产物。

### 3.4 旧文档重建解析（60 份）

从旧系统 436 个运行结果中按化学/力学/其他三类分层抽取 60 份，将旧 `result.json` 的表格重建为 HTML 输入新系统，隔离 OCR 差异，逐字段对比。与 M8 的 12 份基线使用同一选择函数复测。

## 4. 执行结果

### 4.1 真实 PDF E2E

| 指标 | 首次结果 | 重试后 |
|---|---|---|
| 文档数 | 40 | 40 |
| STRUCTURED_READY | 30（75%） | 34（85%） |
| FAILED | 9（OCR_BACKEND_UNAVAILABLE） | 6（大扫描件 OCR 超时） |
| REVIEW_FAILED | 1（成分允许偏差表负值） | 0（修复后重试通过） |
| 记录数 | 1,143 | 1,379（含重试） |
| 字段数 | 1,608 | 2,236（含重试） |
| 端到端 p50 | 100.66s | 100.66s |
| 端到端 p95 | 278.14s | 278.14s |
| 最大 | 287.89s | 287.89s |

阶段耗时（PDF 套件）：

| 阶段 | p50 | p95 | 说明 |
|---|---|---|---|
| OCR | 49.35s | 277.75s | 文本层 PDF 本地 9.2s/30 页；扫描件 GLM 为主 |
| 路由 | 0.28s | 0.42s | 稳定 |
| 沙箱 | 0.92s | 1.22s | 稳定 |
| 审核 | 38.70s | 137.14s | 单模型串行，主要延迟源 |

失败根因：28–37 页扫描件在单卡 GLM-OCR 上逐页识别，超过单页/文档预算；部分请求返回 `Server disconnected`。已实施：文本层优先、页数×20s 文档预算（上限 900s）、OCR 错误不重试、快速失败。

重试结果：对 5 份代表性失败文档（7–21 页）顺序重试，4 份恢复为 STRUCTURED_READY（1083 21 页、13f7 7 页、b8a 19 页、HB 20079 14 页），1 份 7 页/10.6MB 高密度扫描件仍失败。剩余 5 份未重试文档为 28–37 页大扫描件，建议改为夜间批处理或增加 OCR 节点。

### 4.2 分支与异常

18/18 通过。审核门禁用例确认：确定性规则错误会将 run 置为 `REVIEW_FAILED` 且 `error_code=REVIEW_FAILED`；模型审核错误仅降级为 `warn`，不误杀。

### 4.3 60 份新旧字段对比

| 指标 | 结果 | 目标 | 判定 |
|---|---|---|---|
| Field F1 | 0.5153 | ≥0.80 | 未达标 |
| Precision | 0.5146 | — | — |
| Recall | 0.5161 | — | — |
| Value match | 0.8959 | ≥0.90 | 接近 |
| 静默错误率 | 10.41% | ≤5% | 未达标 |
| 覆盖率 | 100% | ≥90% | 通过 |
| 证据命中率 | 100% | 参考 | 通过 |
| p95 延迟 | 119.46s | ≤120s | 通过 |
| 失败运行 | 0 | 0 | 通过 |

字段规模：旧 2,866 / 新 2,874 / 共同 1,479。

### 4.4 M8 同 12 份基线复测（改进前后）

| 指标 | M8 基线 | 本次 | 变化 |
|---|---|---|---|
| Field F1 | 0.3489 | 0.5497 | +57.5% |
| Recall | 0.2544 | 0.5612 | +120.6% |
| Precision | 0.5549 | 0.5386 | -2.9% |
| Value match | 0.9087 | 0.9196 | +1.1pt |
| 静默错误率 | 9.13% | 8.04% | -1.1pt |
| 覆盖率 | 100% | 100% | 持平 |
| p95 | 74.97s | 73.91s | -1.4% |
| 失败运行 | 0 | 0 | 持平 |

### 4.5 旧 reparse20 文档级覆盖

20 份可匹配文档：旧记录 3,696，新记录 479（含 9 份 OCR 失败文档为 0）。成功的采购规范中，新/旧记录比在 0.13–5.0 之间，说明两系统“记录”粒度不同（旧系统把检验项目、条款等计入记录）。该指标仅作覆盖参考，不作为准确率。

### 4.6 效率对比

| 系统/阶段 | p50 | p95 | 备注 |
|---|---|---|---|
| 旧系统（60 份，trace） | 0.379s | 0.935s | OCR 为 mock，不含真实视觉识别 |
| 新系统 OCR | 0.477s | 1.125s | 旧文档重建为 Markdown 的文本路径 |
| 新系统 路由 | 0.338s | 0.698s | — |
| 新系统 沙箱 | 1.062s | 2.046s | 容器隔离执行 |
| 新系统 审核 | 38.268s | 117.381s | 单模型串行，占总耗时 96% |
| 新系统 总 | 39.991s | 119.076s | 60 份对比运行 |

结论：解析主链路（OCR+路由+沙箱）已接近秒级；审核 Agent 是唯一显著瓶颈。生产建议：审核 Agent 按采样/异步执行，或默认 deterministic-only，可将 p95 降到约 2–3s。

## 5. 问题记录与修复

| # | 问题 | 影响 | 修复 | 状态 |
|---|---|---|---|---|
| 1 | 单字符元素（C/P/S/N/O/H/B/V/W/Y）永不匹配列 | 化学成分召回缺失 | 单字符按完整列名匹配，避免 C 误吃 Cr | 已修复 |
| 2 | KV2/KU2、HBW/HB 被配方绑定名覆盖 | 字段口径错误、静默错误 | 表头符号优先 + 两阶段精确/别名绑定 | 已修复 |
| 3 | 牌号行键被注释长句污染 | 大量无意义记录 | 牌号校验（句号/分号/逗号/说明） | 已修复 |
| 4 | `transposed` 规则未实现 | 元素行/元素列表零产出 | 实现两种元素布局解析 | 已修复 |
| 5 | 配方绑定过窄（化学 3 元素、力学 5 指标） | 召回低、F1 0.349 | 发布 1.1.0：39 元素 + 17 力学/工艺指标 | 已修复 |
| 6 | `recipe_channel` 未参与路由 | 通道选择无效 | 路由透传通道 + 非法通道 422 | 已修复 |
| 7 | 审核 fail 仍进入 STRUCTURED_READY | 静默放行错误数据 | 新增 REVIEW_FAILED 终态与门禁；模型错误降级 warn | 已修复 |
| 8 | 成分允许偏差表被判为成分表 | 负值触发审核失败 | 表头/标题识别“允许偏差”为 admin；成分负值过滤 | 已修复 |
| 9 | 带单位符号（σb N/mm²）路由到硬度配方 | 力学表零产出 | 单位拆分 + 符号别名 + 同分时按配方具体度决胜 | 已修复 |
| 10 | “常用材料”列/数值牌号（45、35）不被识别 | 力学表零产出 | 行键回退列 + 显式行键允许数值牌号 | 已修复 |
| 11 | OCR 后端故障时单文档可挂起 10+ 分钟 | 批次阻塞、超时 | 文本层优先；页数×20s 文档预算；OCR 错误不重试 | 已修复 |
| 12 | 扫描件全部走视觉模型 | 20–35 页文档超时 | 混合 OCR：文本层 PDF 本地解析（30 页 9.2s） | 已修复 |
| 13 | 前端缺 REVIEW_FAILED 状态映射 | 状态显示为原始值 | 状态映射/终态集合补齐 | 已修复 |
| 14 | Ruff 未用导入 | 静态检查失败 | 清理 | 已修复 |

## 6. 剩余风险与上线建议

1. **字段 F1 0.52 未达 0.80**：主要来自两侧表示差异（条件/牌号键、合并单元格牌号、同一牌号多条件表冲突）和大表覆盖。建议下一迭代按“单表单条件”口径继续对齐，并对合并牌号单元格做拆分。
2. **静默错误 10.41%**：集中在多表/多块文档（同一牌号出现在多个条件表时取首条）。建议输出层增加 `condition` 维度并在对比/展示中保留。
3. **大扫描件 OCR**：单卡 GLM 吞吐限制；40 份中 6 份失败（28–37 页大扫描件 + 1 份高密度 7 页扫描件）。生产建议 OCR 异步队列、夜间批处理或增加 OCR 节点；对 >20 页扫描件设定独立 SLA。
4. **审核 Agent 延迟**：占总耗时 96%。建议默认 deterministic-only 或按 10% 采样，将 p95 从 ~120s 降至秒级。
5. **旧系统效率不可直接比较**：旧运行 trace 的 OCR 为 mock（1ms），新系统为真实 OCR；效率结论仅比较非 OCR 主链路。
6. **K8s 部署**：本次验证使用 Compose 生产镜像；K8s 清单/镜像需在切换窗口同步更新。

## 7. 附件

- [E2E 结果 JSON](closeout-e2e.json) / [E2E 报告](closeout-e2e.md)
- [失败样本重试](closeout-e2e-retry.md) / [JSON](closeout-e2e-retry.json)
- [60 份新旧对比](closeout-effect-comparison.md) / [JSON](closeout-effect-comparison.json)
- [12 份基线复测](closeout-effect-12.md) / [JSON](closeout-effect-12.json)
- [新系统阶段耗时](closeout-new-stage-timing.json)
- [旧系统阶段耗时](closeout-legacy-timing.json)
- [reparse20 文档级对比](closeout-reparse20-doc-level.json)
- [M8 压测](M8-loadtest.md) / [M8 切换演练](M8-cutover-drill.json)
- [M8 验收记录](../acceptance/M8.md)
