# Agent 自动修复：市场调研与优化方案

> 调研时间：2026-11-13
> 调研对象：智能文档处理（IDP）、数据/ML 管道自愈、自动化程序修复（APR）、Schema/列匹配、Kubernetes 自愈运维
> 结合项目：汉唐标准解析平台（feedback → triage → repair → candidate → verify → promote）

## 一、结论摘要

业界没有任何一家把"LLM 自由生成补丁 + 直接上线"作为默认路径。成熟做法高度一致：

1. **验证器是行为 oracle，不是模型自评**：补丁必须让可量化的验收指标变化（AWS 的 Validator、APR 的 FAIL_TO_PASS 测试、K8s 的就绪探针）。
2. **确定性闸门优先，LLM 只做上下文诊断**：已知故障走规则；只有需要理解上下文时才交给 agent（arXiv 2608.01955 的核心设计原则）。
3. **补丁空间必须与验证空间重合**，且动作白名单化；高风险动作人工审批（K8s 的 L2/L3/L4 分级、AWS 的 guardrail agent）。
4. **证据决定上限**：Schema 匹配研究显示，结构化上下文 + 硬性可采纳约束带来的提升远大于换更强的模型（ConStruM 95.4% vs 无上下文 51.6%；约束闸门 F1 0.08 → 0.66）。
5. **失败必须回灌迭代**，并沉淀为可复用记忆：AWS 把修好的 extraction instructions 存进向量库供同类文档复用；自愈架构把处置结果写入 incident memory。
6. **APR 的最大陷阱是 patch overfitting**：补丁能通过自己生成的用例，却过不了真实回归集。必须有独立回归集（PASS_TO_PASS）与多候选筛选。

对照本项目 13 条复测：7 条无补丁、6 条有补丁但 diff 为空、验证通过 0。根因与上述规律逐条对得上——缺证据、补丁空间与验证空间不重合、缺可采纳性闸门、无迭代、无记忆。

## 二、业界做法

### 2.1 智能文档处理：AWS 自改进 IDP（最接近本项目）

AWS 用 8 个 agent 组成两条工作流（[AWS 博客，2026-10](https://aws.amazon.com/blogs/machine-learning/build-self-improving-document-processing-using-amazon-bedrock-agentcore/)）：

- **训练流（新文档类型）**：Instructions agent 生成抽取指令 → Extractor 抽取 → **Validator 按 schema 与业务规则校验** → 失败则 **Instructions Fixer 基于具体报错修订指令** → 成功后 **Save Instructions 持久化到向量库**。
- **自动流（已知类型）**：Matcher 向量检索命中已有指令 → Extractor 直接抽取 → 失败时 **Troubleshooter 直接修数据、不改指令**。

关键细节：

- Validator 返回的是**可执行的具体错误**，例如 `'SB-004' does not match '^AB-[A-Z]{2}-\d{3}$'`；Fixer 据此追加"给供应商 SKU 加 `AB-` 前缀"这一条明确规则，第二次即通过。
- 指令按文档类型持久化，第二份同类文档端到端从 3m49s 降到 1m30s。
- "**改配置**"与"**改数据**"两条路径分离：训练流修指令，自动流只补数据，避免用配置补丁掩盖一次性数据问题。

### 2.2 数据/ML 管道：guarded self-healing 参考架构

arXiv 2608.01955 把自愈定义为八阶段闭环：**detect → triage → diagnose → plan → approve → remediate → verify → learn**（[论文](https://arxiv.org/html/2608.01955)）。其设计原则：

- 已知故障路由到**确定性规则**，LLM agent 只用于需要上下文推理的故障；
- 处置动作**只允许白名单内**的动作，高风险动作进入人工审批；
- 验证阶段确认系统真正恢复，而不是"补丁已应用"；
- 处置结果写入**组织记忆**，下次同类事件直接复用；
- 成本随事件数增长，而不是随资产规模增长。

AWS Glue 的 ETL 自愈 agent 同样设边界：schema/类型错误重生成代码，OOM 换更大 worker，但"**如果第二次运行可能重复写入已产生的数据，则跳过重试**"（[AWS Big Data 博客](https://aws.amazon.com/blogs/big-data/automate-etl-pipeline-creation-with-amazon-bedrock-agentcore-and-aws-glue/)）。

### 2.3 自动化程序修复（APR）：补丁过拟合是主要风险

- LLM 修复的**测试过拟合**仍是系统性问题：用测试驱动迭代会提高通过率，但同时提高过拟合率（[Is the Cure Still Worse Than the Disease? 2026](https://arxiv.org/html/2511.16858v1)）。
- 补丁是否"过拟合"用独立判定：通过自己生成的复现用例，但 **FAIL_TO_PASS 不过或 PASS_TO_PASS 被破坏**，即判为过拟合（[Traceability 实证研究](https://arxiv.org/html/2506.08311v2)）。
- 提升手段是**故障定位 + 更强的 oracle**：ADVERINTENT 用"推理 agent 生成对抗性意图 → 测试 agent 生成带期望值的对抗用例 → 修复 agent 同时满足两者"（[论文](https://arxiv.org/pdf/2505.13008)）。

对本项目的映射：不能只验证"目标规则变好"，必须同时验证"其它文档/字段不退化"，并且验证用例不能由 repair agent 自己生成。

### 2.4 Schema / 列匹配：结构化上下文与硬约束是决定性因素

- **ConStruM**：把表结构、上下文一并给 LLM，HRS-B/PSID-B 平均准确率 **95.4%**，无上下文 LLM 仅 **51.6%**（[论文](https://arxiv.org/html/2601.20482)）。
- **约束引导的企业数据映射**：先用"硬可采纳性"把候选空间压缩约 480 倍且不掉真值，该闸门（而非模型）是决定性提升，**F1 0.08 → 0.66**，且模型无关、无额外推理成本（[论文](https://arxiv.org/html/2608.24218v1)）。
- 匹配结果普遍要求**输出置信度**（0–10 归一化），低置信度进入人工复核（[ACM 电力注册表研究](https://energy.acm.org/eir/poster-abstract-evaluating-large-language-models-for-schema-matching-on-real-world-power-plant-registries/)）。

### 2.5 Kubernetes 自愈运维：风险分级 + guardrail

- 能力分级：L2 只调查并给建议（无需审批）／L3 执行已批准的低风险动作（策略控制）／L4 高影响动作必须人工审批（[AWS 事故响应实践](https://dev.to/omayrashraf/building-an-ai-powered-kubernetes-incident-response-system-on-aws-1nj8)）。
- 独立 **guardrail agent** 逐项判断动作是否放行，例如有 PDB 的 deployment 允许改内存、没有的拒绝（[AWS DevOps Agent + A2A](https://aws.amazon.com/blogs/mt/controlled-self-healing-amazon-eks-clusters-with-aws-devops-agent-and-a2a-remote-agents/)）。
- Salesforce 的 self-remediation 用 Argo 工作流承载"safe operations"，默认只读诊断，生产变更需 on-call 甚至二级审批（[案例](https://www.zenml.io/llmops-database/ai-powered-self-remediation-loop-for-large-scale-kubernetes-operations)）。

### 2.6 商业 IDP 的反馈回路

Azure Document Intelligence、UiPath Document Understanding 的主流做法是**人工反馈 → 增量训练/重新训练自定义模型**，并用主动学习挑选最有价值的样本送审（[Azure 增量训练](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/whats-new?view=doc-intel-4.0.0)、[UiPath ML Trainer](https://docs.uipath.com/document-understanding/automation-cloud/latest/classic-USER-GUIDE/machine-learning-extractor-trainer)、[主动学习综述](https://arxiv.org/pdf/2312.09880)）。它们不追求"agent 直接改线上规则"，而是把人工修正沉淀为模型/模板资产。

## 三、共性规律

| # | 规律 | 代表系统 |
|---|---|---|
| 1 | 验证器输出**具体、可定位、可执行的错误** | AWS Validator → Instructions Fixer |
| 2 | **确定性规则优先**，LLM 只处理需要上下文的部分 | 2608.01955、AWS Glue |
| 3 | 动作**白名单 + 风险分级 + 人工审批** | K8s L2/L3/L4、guardrail agent |
| 4 | 补丁必须让**独立 oracle** 变好，且不破坏回归集 | APR FAIL_TO_PASS / PASS_TO_PASS |
| 5 | **结构化上下文 + 硬可采纳约束**比换模型更有效 | ConStruM、约束引导映射 |
| 6 | 失败结果**回灌**形成多轮迭代，而非一次定生死 | Reflexion 系、AWS 二次通过 |
| 7 | 成功处置沉淀为**可复用记忆/指令库** | AWS Save Instructions、incident memory |
| 8 | "修配置"与"修数据"分离，避免用配置补丁掩盖数据问题 | AWS Troubleshooter vs Fixer |

## 四、对照本项目的差距

| 差距 | 当前实现 | 业界做法 | 后果（13 条复测证据） |
|---|---|---|---|
| 补丁空间 ≠ 验证空间 | 允许 `/signature`、`/templates`、`/compatibility`；验证固定原 routing + candidate 覆盖 | 只允许验证能触达的动作；其余转建议 | 6 条有补丁样本 diff 全为空 |
| 证据不足 | feedback target 仅 rule_id/document_id/run_id；repair 只看到目标表摘要 | 错误定位到表/列/期望值，附样例行 | 模型 3 次输出 "No concrete measure in feedback" |
| 目标表定位错 | 默认取 `tables[0]` | 取规则命中最严重的表 | 补丁作用在无关表上 |
| 无"可修复性"闸门 | 所有 DOC-* 都进 repair | 确定性分流：engine/data/recipe | 7 条无补丁（其中 4 条本就不该生成补丁） |
| 验证判定过严且单轮 | 严格单调改善、一次定生死 | 不倒退 + 目标指标改善；失败回灌迭代 | 6 条全部 `not fixed` 且无第二轮 |
| 无动作白名单/分级 | 任意 JSON Patch 路径 | 白名单 + 风险分级 + 审批 | 生成过 no-op、签名类无效补丁 |
| 无记忆沉淀 | patch_chain 只堆版本 | 成功指令入库、同类复用 | 13 条没有一条可复用产物 |

## 五、优化方案

### 5.0 设计基点：Agent 必须拿到"任务包"

这个判断是对的，而且还需要再收紧一步：不是把一堆内容直接丢给 Agent，而是给一个**结构化、有界、可验证的任务包**，让它能回答四个问题：

1. **做什么**：问题是什么、验收标准是什么（`goal` + `acceptance`）
2. **从哪找**：原文、表网格、已解析记录、诊断信息（`evidence`，带页码/表/行/列与引文）
3. **做到什么程度**：正解 `expected`、目标阈值、不允许退化的指标
4. **允许怎么做**：可用算子、可采纳列集合、输出 schema、禁止项（`constraints`）

行业证据支持这个判断：AWS 的 Fixer 能一次修好，是因为 Validator 给的是 `'SB-004' does not match '^AB-[A-Z]{2}-\d{3}$'` 这种可执行错误；ConStruM 把表结构一起给模型，准确率从 51.6% 提升到 95.4%；约束闸门把候选空间压缩约 480 倍，F1 从 0.08 升到 0.66。**给什么、给多少、以什么形式给，直接决定上限。**

#### RepairContext v1（任务包契约）

```json
{
  "task": {
    "feedback_id": "fb_...",
    "source": "review | user",
    "rule_id": "DOC-UNBOUND-COLUMNS",
    "verdict": "wrong | missing | extra | ambiguous",
    "priority": "P0 | P1",
    "goal": "让 T5 的 C/Si/Mn 列产出记录，且记录数不少于 1",
    "acceptance": {"metric": "MEASURE_COLUMN_MISSING", "current": 3, "target": 0}
  },
  "problem": {
    "description": "用户原话或审核消息",
    "target": {"document_id": "...", "table_id": "T5", "record_id": null, "property": "C", "page_no": 8},
    "observed": {"records": 0, "diagnostics": ["MEASURE_COLUMN_MISSING", "NO_RECORDS"]},
    "expected": "≤0.22（能从原文确定时填写，否则为 null）"
  },
  "evidence": {
    "source_quote": "原文引文（可选）",
    "page_text": "第 8 页文本（按预算裁剪）",
    "table": {
      "table_id": "T5", "page_no": 8, "profile": "chemical_composition",
      "orientation": "grade_rows", "header_paths": [["牌号"], ["C"], ["Si"]],
      "sample_rows": [["Q355B", "0.20", "0.55"]], "merges": [], "footnotes": []
    },
    "records": [
      {"record_id": "T5-R1", "grade": "Q355B", "properties": {"C": {"raw": "0.20", "unit": "%"}}}
    ]
  },
  "recipe": {
    "recipe_id": "chemical_element_rows_v1", "version": "1.2.3",
    "profile": "chemical_composition",
    "bindings": {"row_key": ["元素"], "conditions": ["牌号"], "measures": {}},
    "rules": {"transposed": true},
    "bound_columns": [], "unbound_columns": ["C", "Si", "Mn"]
  },
  "constraints": {
    "allowed_levels": ["L1", "L2"],
    "allowed_operators": ["recipe.binding_override", "table_repair.add"],
    "admissible": {"columns": ["C", "Si", "Mn"], "measures": ["C", "Si", "Mn"]},
    "forbidden": ["修改其它表", "编造原文没有的数值", "改生产配置", "改代码"],
    "output_schema": "RepairProposal/v2",
    "max_ops": 5
  },
  "history": {
    "previous_attempts": [{"patch": "...", "verification": "not fixed; new errors=0"}],
    "similar_cases": [{"header_fingerprint": "chem|element_rows|3col", "patch": "...", "verified": true}]
  }
}
```

任务包构建规则（关键）：

1. **证据优先级**：原文 > 表网格 > 已解析记录 > 模型推断；每个字段标注来源，模型引用的内容必须能落回 `page/table/row/col`。
2. **有界**：表格最多 N 行、页文本按 token 预算裁剪、诊断 ≤20 条；超限部分用"摘要 + 指针（artifact key）"，不允许无界拼接。
3. **目标可量化**：`acceptance` 必须能被 gate 直接计算；不能量化的反馈先转 `needs_more_info`，不进入 repair。
4. **可采纳集合由程序算**：`constraints.admissible` = 可映射列 × 测量词典 × 现有绑定的差集，模型只在集合内选择。
5. **幂等可追溯**：任务包计算 hash 并记入 run，便于复现、对比和评估。

#### RepairProposal v2（输出契约）

在现有 `RepairProposal` 上增加：`diagnosis`（root_cause / scope / expected / mechanism / first_divergence / evidence）、`level`（L1/L2/L3）、`operator` + `params`（白名单算子，替代自由 JSON Patch）、`target_signature`、`confidence`、`needs_human`、`test_plan`。

### 5.1 七步闭环（融合旧项目与业界做法）

1. **意图解析（Intent Agent）**：从模糊描述中解析"断言类型 + 范围 + 候选目标"，不直接改配置
2. **定位与诊断**：在候选目标上核对证据，确定 root_cause、scope、expected、rule_change（11 类 root_cause / 7 类 scope / 6 类 action）
3. **求正解**：从表单元格、封面、条款自动算 `expected`，减少"请用户补充期望值"
4. **可修复性闸门**：`engine / data / recipe_binding / unknown` 四路分流
5. **三级修复**：L1 文档级（表修复/指定表绑定覆盖，沙箱重解析）→ L2 配方（白名单算子 + overlay + shadow + 表型签名）→ L3 代码（默认 `proposal_only`）
6. **门禁**：evidence_grounded / reproduction / target_metric / no_new_errors / iteration_limit / regression / diff_policy，三态决策 `accept / rollback / propose_only`
7. **沉淀**：verified 补丁入指令库/learned overlay，失败原因入 case 库；生产字典只读 + hash

#### 5.1.1 意图解析 Agent（应对"说不清"的反馈）

真实反馈通常只有一句话："室温拉伸抽取效果不好"、"化学成分试验方法没有正确抽取"、"冲击没有从文档中抽取出来"。这类描述**既没给字段，也没给期望值**，直接进 repair 必然靠猜。因此把"意图"独立成一段，只做三件事：判断断言类型、圈定范围、给出候选目标，不生成补丁。

**输入**（有界，不塞全文）：

```json
{
  "utterance": "室温拉伸标准要求抽取的不对",
  "document": {"filename": "GBT 1591-2018.pdf", "standard_no": "GB/T 1591-2018", "pages": 20},
  "outline": [
    {"table_id": "T12", "page_no": 9, "caption": "表12 室温拉伸性能",
     "profile": "mechanical_properties", "header_tokens": ["牌号", "Rm", "Rp0.2", "A"],
     "records": 18, "diagnostics": []}
  ],
  "dictionary": [
    {"item": "室温拉伸", "aliases": ["室温拉伸", "常温拉伸", "拉伸试验"],
     "measures": ["Rm", "Rp0.2", "A"], "kind": "mechanical"}
  ],
  "sections": [{"page_no": 8, "kind": "chemical_composition"}, {"page_no": 12, "kind": "test_method"}],
  "history": [{"utterance": "...", "resolved_table": "T12"}]
}
```

**可用只读工具**（最多 3 步，避免一次性塞全文）：`search_tables(query)`、`get_table(table_id)`、`get_page_text(page_no)`、`get_records(table_id)`。

**输出契约**：

```json
{
  "category": "wrong_requirement",
  "verdict": "wrong",
  "scope": "field",
  "subject": "室温拉伸",
  "interpretation": "用户认为室温拉伸的比较符/标准要求与原文不符，未指出具体字段",
  "candidate_targets": [
    {"table_id": "T12", "page_no": 9, "record_ids": ["T12-R1"], "property": null,
     "reason": "表题与表头命中 室温拉伸", "confidence": 0.82}
  ],
  "assumption": "按整张室温拉伸表核对比较符",
  "clarifying_question": null,
  "evidence": [{"page_no": 9, "quote": "表12 室温拉伸性能"}],
  "confidence": 0.82
}
```

**四类典型模糊反馈的解析结果**：

| 用户原话 | 意图解析 | 后续动作 |
|---|---|---|
| 室温拉伸抽取效果不好 | category=unspecified，scope=table，target=T12（整表） | 逐字段对比原文；有表无记录→recipe/OCR 分流 |
| 室温拉伸标准要求抽取的不对 | category=wrong_requirement，scope=field，property=Rm/Rp0.2/A | 诊断比较符与上下限 |
| 化学成分试验方法没有正确抽取 | category=missing_value，scope=clause，kind=test_method | 走条款/检验规则抽取，**不修成分表** |
| 冲击没有从文档中抽取出来 | category=missing_value，scope=table/document，target=KV2/KU2 表 | 先确认原文是否有冲击表：有表无记录→recipe；无表→engine |

**约束**：

1. 先做确定性匹配：词典别名 → 表题/表头 token → 记录属性；匹配不到再让模型在 `outline` 内选择，禁止凭空发明 table_id。
2. 候选目标必须带 `reason` 与 `confidence`；低于阈值（如 0.5）或出现多个互斥解释时，只问**一个**带选项的澄清问题，其余情况按最可能解释继续并显式记录 `assumption`。
3. 意图 Agent 不产出补丁、不判断"该怎么修"；它只回答"用户指的是哪类问题、在哪张表/哪条记录"。
4. 意图结果与 `RepairContext` 合并后交给修复 Agent；修复 Agent 不允许绕过 `candidate_targets` 改其它表。

#### 5.1.2 职责分工：确定性 vs Agent

三段不必都由 LLM 完成，也不应该。原则是"**确定性优先，Agent 兜底**"：能算的不要生成，能查的不要推理，只有需要语义判断和方案设计时才调用模型。

| 环节 | 首选实现 | 何时交给 Agent | 理由 |
|---|---|---|---|
| 意图定位 | 词典别名 → 表题/表头 token → 记录属性 → 诊断码（毫秒级） | 无命中、多个互斥解释、指代模糊（"效果不好"、"不对"） | 可复现、可审计、成本低 |
| 断言分类 | 关键词 + category 映射表 | 长句、隐喻、跨概念描述 | 规则覆盖 80% 常见说法 |
| 证据核对 | 原文/单元格/引文归一化匹配 | 不需要 | 证据必须可落点，不能由模型自证 |
| 求正解 | 从表单元格、封面、条款直接取值 | 需要跨段推理（如"按表注应为 ≥"） | 确定性取值最可靠 |
| 根因归因 | 诊断码 → root_cause 映射表 | 多因并存、跨表一致性判断 | 旧项目实测规则诊断可覆盖多数场景 |
| 修复方案 | — | **必须 Agent**（受算子白名单与可采纳集合约束） | 需要组合与泛化 |
| 验证/门禁 | 沙箱重跑 + 指标 diff + 回归集 | **禁止 Agent** | 验证器是 oracle，不能自己判自己 |
| 沉淀 | hash 指纹、模板入库 | 可选（生成相似案例摘要） | 入库必须确定性 |

目标比例：意图约 70% 规则 / 30% 模型，诊断约 80% 确定性 / 20% 模型，修复 100% Agent 但强约束，验证 100% 确定性。这样单条反馈通常只产生 1–2 次模型调用，而不是 3 次。

#### 5.1.3 通用化方案：词汇鸿沟 → 候选集合 → 证据收敛

"室温拉伸"只是举例。真正要解决的是**用户词表、文档词表、规范词表三者不一致**，而且用户往往说不清粒度与断言。方案不能靠堆同义词，要按下面三层抽象处理。

**第一步：把模糊反馈拆成三类不确定性**

| 不确定性 | 典型说法 | 通用处理 |
|---|---|---|
| 指称不确定 | 用户说"室温拉伸"，原文写"力学性能""拉伸性能""Tensile Properties" | 概念层同义词 + 上下位 + **列语义**（Rm/Rp0.2/A） |
| 粒度不确定 | "抽取效果不好"可能指整张表、某条记录或某个字段 | 先给候选目标分层（表/记录/字段/条款），由诊断收敛 |
| 断言不确定 | "不对""不好"没说什么错 | 断言分类（缺失/值错/要求错/单位错/重复）+ 规则检查枚举 |

**第二步：五层解析框架（与具体业务词无关）**

1. **概念层（业务词典）**：每个概念包含 `concept_id / 名称 / 同义词 / 上下位 / 关联 measure / 章节类型 / 条件维度 / 中英文变体`。例如"室温拉伸"的父概念是"力学性能"，关联 measure 是 Rm/Rp0.2/A/Z，条件维度是温度。
2. **文档实例层**：把文档变成可检索对象——表目录（caption / header_paths / profile / orientation / 条件列 / 记录数 / 诊断码）、章节图（哪几页是化学成分、试验方法、检验规则）、记录索引（grade / condition / properties）。
3. **匹配层**：多信号打分，输出 top-k 候选 + 每个信号的解释 + 置信度。信号包括：字面（别名/缩写/中英文/全半角）、结构（表题/表头路径/profile/章节位置/表注）、语义（canonical measure 集合/单位/比较符/值域）、条件（温度/方向/状态/规格/厚度）、统计（记录数/诊断码）、历史（同文档/同标准/同表型的既往反馈）。
4. **证据层**：候选必须能落回原文（引文、单元格、记录）；落不到证据的候选降权或丢弃。
5. **沉淀层**：用户确认或纠正后写入 learned mapping（作用域：当前文档 / 表型 / 全局），带版本与 hash，不直接改生产词典。

**第三步：歧义处理阶梯（从便宜到贵，最多一次澄清）**

1. 唯一高分 → 直接采用，记录 `assumption`
2. 多候选 → 先用条件（室温/高温）、章节类型（试验方法 vs 化学成分）、记录数与诊断码消歧
3. 仍并列 → 让 LLM 在**已有候选 id 内**重排，只输出选择与理由，不允许新增 id
4. 仍不确定 → 最多问一次带选项的澄清问题
5. 完全无法定位 → 降级为 `document` 范围，交给诊断层枚举候选

**第四步：同类问题不只拉伸，词典要覆盖"说法 → 概念 → 证据"的映射**

| 用户可能说 | 原文可能写 | 关键证据信号 |
|---|---|---|
| 冲击不行 / 冲击没抽出来 | 夏比 V 型缺口冲击、KV2、Charpy impact | KV2/KU2 列 + 冲击表题 |
| 硬度不对 | HBW、布氏硬度、Rockwell | HB/HRC/HV 列 |
| 成分超差 / 成分没对上 | 熔炼分析、成品分析、Chemical composition | 元素列集合 + profile=chemical_composition |
| 尺寸错了 | 外径、壁厚、允许偏差、tolerance | 尺寸表/公差表（注意：公差表不是性能记录表） |
| 试验方法没抽对 | 检验规则、取样、试验方法、Test method | 章节类型=clause，不是数据表 |
| 强度不够 | 抗拉强度、屈服强度、Tensile/Yield | Rm/Rp0.2 列 + 比较符 |

**第五步：意图/诊断到底是不是 Agent**

是 Agent，但不是"纯 LLM 自由发挥"，而是三种不同形态：

| 层 | 形态 | 内核 | LLM 只负责 |
|---|---|---|---|
| 意图 | **检索 Agent** | 词典、索引、多信号打分、规则 | 候选内重排、解释、生成澄清问题 |
| 诊断 | **混合 Agent** | 证据核对、规则检查、求正解 | 多因并存归因、跨表一致性 |
| 修复 | **生成 Agent** | 算子白名单、受限 spec、可采纳集合 | 方案生成 |
| 验证 | 非 Agent | 沙箱重跑 + 门禁 + 回归集 | 无 |

判断标准很简单：**能用检索/计算回答的，不交给生成**；只有在"候选需要语义排序"或"方案需要组合泛化"时才让模型介入。这样既覆盖"说法千变万化"，又保持可复现与低成本。

**第六步：新领域/新说法的接入方式（避免每来一种说法就改代码）**

1. 在概念词典加条目：名称、同义词、上下位、关联 measure、章节类型、条件维度、中英文变体
2. 在文档画像加类型：profile / orientation / 条件列命名习惯
3. 每个概念准备 3–5 份金标（表、记录、期望值），进入意图回归集
4. 验收：新增概念不得降低既有概念的 top-1 命中率
5. 线上纠正先进 learned overlay，稳定后再晋升为词典版本

**度量**：意图 top-1 / top-3 命中率（按概念分层）、错误定位率、澄清率、诊断归因准确率、概念覆盖率（有词典条目且有金标的概念占比）。

### 5.2 P0：让闭环"能跑通"（改造量小、收益最大）

**1. RepairContext 任务包（含 Evidence Pack）**

在 `feedback_from_findings` 生成 DOC-* feedback、以及用户提交反馈时构造完整任务包：

- `task` / `problem` 的目标部分由意图 Agent 的 `candidate_targets` 填充（用户模糊描述先经过 5.1.1 解析）
- `evidence.tables`：命中表清单，每张表含 `table_id / page_no / headers / header_paths / profile / orientation / bound_columns / unbound_columns / sample_rows(3) / merges / footnotes`
- `task.acceptance`：规则当前值、期望阈值
- `problem.target.table_id`：选缺口最大的表，而不是 `tables[0]`
- `constraints`：算子白名单、可采纳集合、禁止项、输出 schema

repair 输入同步注入任务包；prompt 明确"只能在 `constraints.admissible` 内选择"。

**2. 诊断契约（移植旧项目 `diagnose.py`）**

triage 输出从"三字段"扩展为诊断契约：

- `root_cause`（ocr / layout / table_structure / header_mapping / value_parsing / extraction_rule / schema_dictionary / document_meta / source_absent / pipeline_code / unknown）
- `scope`（field / table / clause / document / missing_item / missing_field / document_meta）
- `action`（reparse / table_repair / rule_fix / code_patch / document_meta / report_only）
- `expected`、`rule_change`（规则标识 + before/after 通用逻辑）、`first_divergence`、`evidence`、`confidence`

prompt 硬约束：不得把反馈里的具体值、牌号、标准号写成代码常量；`expected` 必须能在证据原文中找到；`rule_change` 必须描述通用逻辑。字段缺失时回退到规则诊断。

**3. 确定性求正解（移植旧项目 `resolve.py`）**

从引擎已产出的产物中自动求 `expected`：

- 字段级：evidence 的 `row/col` → 表网格单元格
- 文档级：封面标准号、标题、版本
- 条款/项目级：页面文本、条款行中按属性名检索

命中则写入 `problem.expected` 并附引文；未命中标记 `unverifiable`，不把"请提供期望值"直接踢回用户。

**4. 可修复性闸门（Repairability Gate）**

在诊断后加确定性判定，按规则×证据矩阵分流：

| 条件 | 分流 |
|---|---|
| `DOC-NO-TABLES` / 表格为 0 | `engine`，不生成补丁 |
| 目标表头无任何可映射测量词/牌号列 | `data`，输出人工建议 |
| 列存在但未绑定（`unbound_columns` 与测量词典有交集） | `recipe_binding`，允许补丁 |
| row_key/conditions 缺失但有候选列 | `recipe_binding`，允许补丁 |
| `expected` 无法确定且无法量化验收 | `needs_more_info` |

**5. 补丁空间对齐验证空间 + 算子白名单**

- 候选补丁只接受 `/bindings/*`、`/rules/*`；
- `/signature`、`/compatibility`、`/templates` 类 op 转成"路由建议"，不进入 candidate、不计入失败；
- 用旧项目的算子注册表替代自由 JSON Patch：`recipe.binding_override`、`table_repair.add`、`column_alias.add`、`unit_normalize.add` 等，每个算子做必填参数校验；
- 区分 EFFECTIVE（能改变解析结果）与 ADVISORY（只给建议）；
- 增加 `remove` 语义，允许删除错绑 measure。

**6. 消除空 proposal**

`needs_human` 默认 `true`、`scope` 枚举强校验；proposal 为空时输出结构化人工建议（表、列、建议动作），而不是空对象。

### 5.3 P1：让通过率起来

**7. 约束引导的候选生成（hard admissibility）**

不要让模型自由写 JSON Pointer。流程改为：

1. 从任务包算出**可采纳集合**：可绑列 × 允许的 measure 词典 × 现有 bindings 的差集；
2. 模型只在集合内选择映射（多选题而非开放题）；
3. 输出必须带置信度，低于阈值转人工。

依据：约束闸门是 F1 0.08 → 0.66 的决定性因素，且与模型无关。

**8. L1 表级修复（移植旧项目 `table_fix.py`）**

表头合并、错列、比较符丢失这类问题，加别名解决不了，需要"修表 + 重解析"：

- 模型读源表 + 当前记录 + 反馈，输出受限 spec：`header_rows / replace_rows / patch_cells / delete_rows`；
- `_validated_spec` 校验：行号/列号越界、源表不存在的数字、超出上限 → 直接拒绝；
- 由 L1 沙箱重解析执行，只影响当前文档，不写生产配置；
- 分工原则：单文档表结构问题走 L1；跨文档共性才升级为 L2 配方候选。

**9. 验证分级 + 失败回灌（最多 2 轮）**

- 文档级改为**逐表验证**：只重跑命中表（`table_id` 已支持），减少全文档重跑噪声；
- 判定从"严格增加"改为"**记录数不减少 且 目标规则计数下降 ≥1 且 无新增 error 诊断**";
- 失败后把 `before/after diagnostics diff`、`records diff`、失败表头回灌 repair，进行第二轮；仍失败则 `needs_human` 并附诊断。

**10. 门禁补齐 + 动作分级**

补齐旧项目的七项门禁：`evidence_grounded`、`reproduction`、`target_metric`、`no_new_errors`、`iteration_limit`、`regression`、`diff_policy`；决策三态 `accept / rollback / propose_only`。

动作分级：

- L1 自动应用：单表别名扩展、units、conditions、table_repair（过门禁后）
- L2 自动应用但需复审：删除绑定、调整 strategy_chain、nonrecord 规则、跨表配方变更
- L3 人工审批：修改兼容性/模板、跨配方切换、代码补丁

迭代上限 3 次，超限转人工并标 `quarantined`。

### 5.4 P2：让能力复利

**11. 成功案例记忆（Instruction Library）**

- verified 的 patch 按"表头指纹（去数字/单位后的 token 集合）→ patch"入库；
- repair 先做相似检索，命中则作为 few-shot 或直接候选，模型只负责确认；
- 对应 AWS 的 Save Instructions + incident memory。

**12. 独立回归集（PASS_TO_PASS）**

- 固定 50 份代表性样本（已有 `rerun-sample-50.json`）作为回归集；
- 任何 candidate 晋升前跑回归：记录数不降、占位牌号不升、重复键不升、目标规则改善；
- 防止 APR 式过拟合：补丁只对单文档有效、对同类文档无效的，不予晋升。

**13. 度量体系**

| 指标 | 定义 | 当前 | 目标 |
|---|---|---|---|
| 意图定位准确率 | 模糊反馈解析出的表/记录与人工判断一致的比例 | 未度量 | ≥85% |
| 澄清率 | 需要追问用户的比例 | 未度量 | ≤15% |
| 任务包完整率 | 含 acceptance + admissible + evidence 的 feedback 占比 | 未度量 | 100% |
| 诊断字段完整率 | 输出 expected/rule_change/evidence 的 triage 占比 | 未度量 | ≥90% |
| 求正解命中率 | 自动确定 expected 的反馈占比 | 未度量 | ≥50% |
| 可修复子集识别率 | 被正确分流为 recipe_binding 的比例 | 未度量 | ≥90% |
| 补丁有效率 | 有 op 且验证通过的占比 | 0/6 | ≥40% |
| 无效/空转补丁率 | diff 为空的补丁占比 | 6/6 | ≤10% |
| 回归破坏率 | 晋升后回归集指标变差的占比 | 未度量 | 0 |
| 人工接管率 | 进入 needs_more_info 的比例 | 13/13 | ≤50%（可修复子集内） |
| 单条处理成本 | tokens / 时延 | p50 10.9s | 持平或下降 |

## 六、实施顺序建议

1. **第 0 步：概念词典 + 文档大纲索引**——把"说法 → 概念 → measure/章节/条件"建成版本化词典（室温拉伸只是第一条），把每份文档的大纲、表目录、记录索引、诊断码建成可检索对象
2. **第 1 步：意图解析（检索优先，Agent 兜底）**——多信号打分 + 候选解释 + 歧义阶梯；LLM 只在候选内重排与生成澄清问题；RepairContext 任务包同步落地
3. **第 2 步：诊断契约 + 求正解**——确定性证据核对（值/单位/比较符/重复/缺失）为主，LLM 只做多因归因；从表单元格、封面、条款自动求 expected
4. **第 3 步：可修复性闸门 + 补丁空间对齐**——四路分流；只允许 `/bindings`、`/rules`；算子白名单与参数校验
5. **第 4 步：L1 表级修复 + 验证分级 + 门禁 + 两轮回灌**——table_repair 受限 spec、逐表验证、七项门禁、失败原因回灌
6. **第 5 步：动作分级 + 记忆库 + 回归集**——风险分级、相似案例复用、50 份 PASS_TO_PASS、概念分层度量

### 6.1 阶段状态

| 阶段 | 状态 | 交付物 | 测试 |
|---|---|---|---|
| 第 0 步：概念词典 + 文档大纲索引 | **已完成** | `feedback/data/concepts.json`（版本化词典）、`concepts.py`（加载/匹配）、`outline.py`（表目录/列语义/条件/诊断索引） | 词典加载、诊断表头回退用例 |
| 第 1 步：意图解析 + RepairContext | **已完成（规则部分）** | `intent.py`（词典驱动、多信号打分、歧义阶梯、概念无硬编码）、`context.py`（RepairContext：acceptance/admissible/目标表/hash）、`service._context` 注入 intent 与任务包、triage/repair prompt 更新 | 13 条单测覆盖拉伸/高温/冲击/硬度/英文/条款/歧义/无命中/任务包 |
| 第 1 步补：LLM 候选重排 | **已完成** | `intent_rerank` agent（`SingleCallAgent` + `intent_rerank.v1`）：仅当 `scope=table` 且前两名置信度差 ≤0.05 或记录数相同但页码不同时触发；模型只能在已有 `table_id` 内选择，越界/失败保留规则结果；`intent.rerank` 记录应用情况 | 测试见 LLM passes 12 项 |
| 第 2 步：诊断契约 + 求正解 | **已完成（规则部分）** | `diagnosis.py`：11 类 root_cause 映射、6 类 action、expected 推导（表单元格 vs 记录 raw）、first_divergence/rule_change/checks/needs_model；已注入 triage/repair 输入与 prompt | 8 条单测覆盖未绑定/无表/有表零记录/重复键/值不一致求正解/无法求正解/单位缺失 |
| 第 2 步补：LLM 归因 | **已完成** | `diagnosis` agent（`diagnosis.v1`）：仅 `needs_model=true` 时调用；输出 root_cause/action/scope/expected/mechanism/first_divergence/rule_change/evidence；枚举校验 + 别名归一，非法输出保留规则诊断；`model_attribution` 记录是否应用 | 测试见 LLM passes 12 项 |
| 第 3 步：可修复性闸门 + 补丁空间对齐 | **已完成** | `repairability.py`（engine/data/recipe_binding/needs_more_info 四路分流）、`patching.py`（有效根 `/bindings`/`/rules`；`/signature`/`/templates`/`/compatibility` 转建议；非法路径与 op 拒绝；支持 remove；算子注册表与参数校验）、`service.process` 在 triage 后分流、候选前 sanitize | 14 条测试覆盖分流、有效/建议/拒绝 op、算子校验、空补丁 |
| 第 4 步：L1 表级修复 + 门禁 + 两轮回灌 | **已完成** | `table_repair.py`（受限 spec 校验：行/列越界、编造数字、超量、全删拦截；apply 生成修复后的表副本与 OCR 副本）、`gates.py`（evidence/reproduction/target_metric/no_new_errors/no_removed/iteration_limit/regression/diff_policy 八项，决策 accept/rollback/propose_only）、`_verify` 集成门禁并把 checks/decision 写入验证包、`process` 支持最多两轮修复并把上一轮验证结果回灌 `repair_context.history` | 14 条测试覆盖 spec 校验/应用/OCR 副本、门禁通过/回滚/L3/回归 |
| 第 4 步补：L1 沙箱执行 | **已完成** | `build_sandbox_request` 支持 `ocr_override`；`_process_l1` + `_run_l1_table_repair` 把修复后的 OCR 副本写入对象存储、重跑沙箱、按目标表做记录 diff 并过门禁；repair prompt 增加 `scope="data"` 的 table_repair 输出格式；`extract_table_repair` 兼容三种补丁形态 | 提取器单测 + 全量 orchestration/agent 测试 |
| 第 5 步：动作分级 + 案例记忆 + 回归集 | **已完成（工具/接线部分）** | `actions.py`（auto/review/human 三级，删除绑定/规则变更/建议类强制复审）、`memory.py`（表头指纹 + JSON 案例库 + 分层汇总）、`regression.py`（PASS_TO_PASS 快照对比）、验证包新增 `action_tier`、`_context` 注入相似案例、验证通过后自动入库 | 8 条测试覆盖分级、指纹稳定性、记忆去重/检索、回归通过/状态回退/记录下降/缺失 |
| 回归门禁接入晋升 | **已完成** | `verify` 在 `_registry_promote` 前读取 `HANSON_REGRESSION_BASELINE` / `CURRENT` 快照对比，失败抛 `REGRESSION_FAILED(409)` 阻断晋升；未配置时跳过 | 2 条测试覆盖跳过与阻断 |
| Stage A：工具取证 | **已完成** | 新增 `get_table`（分页行范围）与 `get_records`（按表/记录过滤、分页）；repair 任务启用这两个工具、最多 3 次调用；`tool_data` 与 prompt facts 分离，模型只按需取数 | 3 条工具测试 + 真实 feedback 复测 |
| 真实反馈端到端（Stage 0-5 + 工具） | **已完成** | 13 条真实 feedback：4 条 verified（3 条 DOC-DUP-KEYS + 1 条 L1 表修复）、7 条 L1 执行后 rollback（均为 target_metric 未改善）、9 条 needs_more_info；p50 14.6s、p95 19.9s；无 400/500 | 结果见 `agent-repair-e2e-final.md` |
| 固定 Schema 驱动验收 | **已完成** | `schema_contract.py`（必填/条件字段、属性名映射）、`coverage.py`（required_rate/complete_rows/missing+cause）、RepairContext 注入 schema/coverage、acceptance 切换为 complete_items/required_items、门禁新增 required_no_loss（仅对 schema 指标生效） | 8 条测试 |
| 真实反馈端到端（Schema 版） | **已完成** | 13 条：4 条 verified（1 条 L1 + 3 条 DOC-DUP-KEYS）、7 条 L1 尝试、9 条 needs_more_info；p50 17.1s / p95 21.7s | 结果见 `agent-repair-e2e-final.md` |
| Stage 6：Schema 覆盖度 + 行级诊断回灌 | **已完成** | `schema_contract.py` + `coverage.py`（必填/条件字段、complete_rows/required_present/missing+cause）；验证包写入 `coverage_before/after/after_diagnostics`；`history.previous_attempts` 回灌 coverage 差分（resolved/still_missing）与 ROW_SKIPPED 行号；门禁 `required_no_loss` | 16 条 schema/回灌测试 |
| Stage 6 补：repair 上下文瘦身 | **已完成** | `_tool_tables` 仅下发目标表行、其它表仅元数据；`evidence.table.merges` 仅保留表头区 ≤40 条；单条任务从 146 KB 降到 38 KB，消除模型 400 | 2 条测试 |
| Stage 6 补：路由与 spec 容错 | **已完成** | `MEASURE_COLUMN_MISSING.detail.measure` 并入 `unbound_columns`（UNBOUND 从 data 路由 recipe）；`replace_rows` 兼容数组形式；兼容扁平 `table_repair.spec`、嵌套 proposal、`scope=data` 但只有配方 ops | 3 条测试 + 5 条真实反馈复测 |
| Stage 6 补：hard admissibility + max_ops | **已完成** | `sanitize_patch` 强制新增 measure 绑定落在 `admissible` 内；`max_ops` 按规则强制（DUP-KEYS=20，其余=5），越界 op 拒绝并记录原因 | 5 条测试 |
| Stage 6 补：回归集运行器 | **已完成** | `regression.py` 新增 `metrics_from_records`（records/fields/placeholders/duplicates），快照门禁增加 complete_rows 下降、占位牌号与重复键上升拦截；新增 `scripts/benchmark/feedback_regression.py`：按 manifest 跑 stable/candidate 通道、生成 baseline/current 快照并可直接 compare | 3 条测试 + 脚本 |
| 真实反馈端到端（Stage 6） | **已完成** | 13 条真实 feedback：4 verified、9 needs_more_info；L1 尝试 5 次（3 rollback、1 verified、另有 1 条 spec 拒绝→修复后进入验证）；无 400/500；回灌生效（第二轮 prompt_tokens 上升且补丁变化） | 结果见 `agent-repair-e2e-final.md` 第三轮 |
| Stage 6 补：度量体系 | **已完成** | `metrics.py`（状态/验证率、L1 尝试与回滚、动作分级、门禁失败、补丁 ops/空补丁率、意图重排/澄清/top-1/top-3（支持 gold 标注）、诊断 needs_model/模型归因/expected/rule_change/证据覆盖率、概念分层、时延 p50/p95）；`service` 把 intent/diagnosis/repairability 摘要持久化到 `feedback.root_cause`；新增 `scripts/benchmark/feedback_metrics.py` 生成 JSON/Markdown 报表 | 7 条测试 + 报表 `feedback-metrics.md` |
| Stage 6 补：澄清问题 | **已完成** | `_build_clarification`：并列候选（置信度差 ≤0.05 或记录数相同不同页）生成 A/B/C + “都不是”选项；单候选置信度 <0.5 生成是/否确认；LLM 重排成功后清除；`process` 在 triage/repair 前 `_clarify` 落 needs_more_info 并写入消息，避免无效模型调用 | 7 条测试 |
| Stage 6 补：确定性求正解 | **已完成** | `resolve.py`：OCR 文本 mojibake 修复；封面标准号/标准名称解析；条款行按属性/关键词检索并跳过表格行；`diagnose` 在无单元格正解时附加 `expected/expected_source/expected_evidence`，并回填 `repair_context.problem.expected` | 8 条测试 |
| Stage 6 补：结构化人工建议 | **已完成** | `suggestions.py`：按 engine/data/recipe_binding/needs_more_info 生成 `reparse_or_fix_ocr` / `repair_table_structure` / `bind_measures` / `manual_review` / `manual_triage` / `confirm_table`，带 table_id/page_no/columns/reason/confidence/options；`_store_root_cause`、`_clarify`、`_needs_more_info` 落库，`FeedbackDetail.suggestions` 对外返回 | 8 条测试 |
| Stage 6 补：案例复用 | **已完成** | `select_reusable_case` 按指纹+rule_id+level 选已验证案例；L1/L2 首轮直接复用缓存补丁（不再调模型），验证失败后第二轮回落模型；案例库默认路径改到挂载目录 `services/orchestration/data/feedback/cases.json`，重建不丢；案例记录补充 root_cause | 5 条测试 |
| Stage 6 补：沉淀晋升 | **已完成** | `promotion.py`：重复已验证案例（默认 ≥2 次）晋升为 `learned_overlay.json`，带 sha256 防篡改；生产词典/配方只读；`OverlayStore` 优先参与案例复用；新增 `scripts/benchmark/promote_cases.py`（支持 dry-run） | 4 条测试 |
| Stage 6 补：L3 审批发布 | **已完成** | `approve_code`：确认 + engine scope + 安全门 + 非空文件四重校验；按 stable 版本自增发布 `parser/parser_core` 资产并晋升 stable，记录 `root_cause.code_release`；新增 `POST /v1/feedback/{id}/approve-code` 与内部路由 | 5 条测试 + 409 冒烟 |
| 剩余未完成项 | **无** | 方案条目已全部落地 | — |

### 6.2 方案未完成项（逐条核对）

| 方案条目 | 状态 | 缺口 |
|---|---|---|
| 5.1.1 / 第 1 步补：LLM 候选重排 | **已完成** | 置信度差 ≤0.05 或记录数相同页码不同时触发；只在候选内选择，越界保留规则结果 |
| 5.1.1：澄清问题生成 | **已完成** | 并列候选输出 A/B/C + “都不是”，低置信度输出是/否确认；重排成功即清除；在 triage/repair 前返回 needs_more_info |
| 第 2 步补：LLM 归因 | **已完成** | `needs_model=true` 时调用 `diagnosis` agent，枚举校验通过后覆盖规则归因，失败保留规则结果 |
| 5.2.3 确定性求正解 | **已完成** | 表单元格 vs 记录 raw、封面标准号/名称、条款行三路求正解；命中写入 expected + 证据，未命中保持 None |
| 5.3.7 hard admissibility | **已完成** | `sanitize_patch` 新增 `admissible` / `max_ops`：新增 measure 绑定必须落在 `admissible.measures`/`columns`，越界 op 直接拒绝；`max_ops` 按规则强制（DOC-DUP-KEYS=20，其余=5），超出部分标记拒绝；条件/row_key 仍由算子白名单约束 | 5 条测试 |
| 5.2.6 结构化人工建议 | **已完成** | `FeedbackDetail.suggestions` 返回表/页/列/动作/原因/置信度；有澄清选项时返回 `confirm_table` + options；needs_human proposal 覆盖规则原因 |
| 5.4.11 案例复用 | **已完成** | 命中同表型+同 rule 的已验证案例时，首轮直接作为候选补丁进入沙箱验证；失败后第二轮回落模型，并把复用失败原因写入 history；案例库落到挂载目录 |
| 5.4.12 独立回归集 | **已完成** | `feedback_regression.py` 按 manifest 跑 stable/candidate 两批并生成快照；门禁比对记录数下降、状态回退、complete_rows/required_present 下降、占位牌号与重复键上升；`HANSON_REGRESSION_BASELINE/CURRENT` 接入晋升 |
| 5.4.13 度量体系 | **已完成** | `feedback_metrics.py` 从 `/internal/feedback` 聚合 11 类指标并输出 JSON/Markdown；`service` 持久化 intent/diagnosis/repairability 摘要；支持 gold 标注计算意图 top-1/top-3 |
| 5.1 第 7 步：沉淀晋升 | **已完成** | 重复 verified 案例晋升为 hash 保护的 learned overlay，复用优先级高于普通案例；生产词典/配方只读，不修改 concepts.json |
| L3 代码补丁审批发布 | **已完成** | 人工 `confirm=true` 后发布 parser bundle 并晋升 stable；未确认/非 engine/安全门未过/空文件均返回 409 `CODE_RELEASE_BLOCKED` |

当前测试结果：意图 14 + 诊断 8 + 闸门/补丁 18 + Stage4 14 + Stage5 13 + 工具 3 + triage/repair/data patch 11 + Schema 17 + LLM passes 19 + 度量 7 + 求正解 8 + 建议 8 + 案例复用 5 + 沉淀晋升 4 + L3 5 = 154 项通过；`tests/integration` 全量通过；`ruff check` 改动目录通过。

## 七、风险与边界

- **不要追求全自动**：`DOC-NO-TABLES`、扫描件 OCR 差、文档本身无牌号列等问题，正确处置是分流与人工建议，不是生成补丁。
- **避免"补丁通过但语义错误"**：LLM 修复存在过拟合风险，必须有独立回归集与人工确认门。
- **配方版本可回滚**：candidate/stable 与 snapshot 机制已具备，L2/L3 动作必须保留回滚点。

## 八、旧项目（legacy `metal_doc_agent/selfheal`）实现与可采纳点

旧项目已经实现过一套"自动审查 + 用户反馈 + 受控修复"的独立路线，代码位于 `legacy/metal-doc-agent/metal_doc_agent/selfheal/`，设计文档为 `legacy/metal-doc-agent/docs/selfheal_route_plan.md`。它的机制比新项目当前实现更完整，但同样没有拿到高通过率（Phase 0 实测 35B 审查严格召回 0.725、误报率 0.625，结论是"不能无人值守"）。因此值得采纳的是**机制**，不是结果。

### 8.1 旧项目的模块划分

| 模块 | 职责 |
|---|---|
| `audit.py` | 自动审查：确定性规则先跑（证据缺失/引文不符/单位缺失/重复记录），模型只审裁剪后的审计包，finding 必须指向真实 record/field，否则丢弃 |
| `feedback.py` / `triage.py` | 反馈受理：category → verdict 映射、目标校验、`observed` 抓取、按 scope 决定 `reparse / audit / need_more_info` |
| `diagnose.py` | 诊断：输出 root_cause（11 类）、scope（7 类）、action（6 类）、expected、mechanism、first_divergence、rule_change、evidence、confidence |
| `resolve.py` | 确定性求正解：从表单元格、封面标准号/标题、条款文本中自动求出 expected，用户只需确认 |
| `evidence.py` | 证据包：把原文、表网格、记录、trace 打包给诊断与修复 |
| `planner.py` | L2 规划：模型只能在 7 个白名单算子中选一个，非法算子直接拒绝 |
| `l1.py` / `l2.py` / `l3.py` | 三级修复：L1 文档级沙箱重解析、L2 配置 overlay + shadow、L3 代码补丁（默认 `propose_only`） |
| `table_fix.py` | 表结构修复：模型读源表生成受限 spec（表头行/替换行/补丁单元格/删除行） |
| `gates.py` | 门禁：evidence / reproduction / target_metric / no_new_errors / iteration_limit / regression / L3 diff_policy |
| `learn.py` | 沉淀：应用成功的修正转成 learned alias overlay 与 rule proposal，字典文件只读 + hash 校验 |

### 8.2 旧项目的关键设计（对新项目最有价值的 10 点）

1. **统一 Finding**：自动审查与用户反馈归一为同一模型（verdict 六态、target、expected、evidence、rule_code、confidence），按 `doc_id + target + verdict` 去重；用户反馈优先但必须复现。
2. **诊断先于修复**：先产出 root_cause / scope / action / expected / rule_change，再决定修哪里；prompt 硬约束"不能把反馈里的具体值、牌号、标准号写死"、"expected 必须能在原文找到"。
3. **确定性求正解**：`resolve_correction` 从已有产物中算出正确值，避免把"请提供期望值"踢回给用户。
4. **三级修复逐级降级**：L1 文档级（只影响当前文档）→ L2 配置/配方（同类表型）→ L3 代码（提案制），每级都有独立沙箱产物。
5. **算子白名单 + 参数校验**：7 个算子，区分 EFFECTIVE（真正改变结果）与 ADVISORY（只给建议），非法算子直接拒绝。
6. **表型签名隔离**：`signature = hash(profile, orientation, n_cols, header_paths)`，候选规则只作用于同类表型。
7. **table_repair 受限 spec**：模型不能编造源表没有的数字，`_validated_spec` 会校验；表结构问题走"修表 + 重解析"，而不是硬加别名。
8. **七项门禁 + 三态决策**：accept / rollback / propose_only；任何一项不过即回滚，超过迭代上限转 quarantine。
9. **反馈回复结构化**：判定、正解、机制、依据（页码/表/行/列 + 原文引文）、已执行、结果，用户可核对。
10. **学习沉淀隔离**：修正只写 learned overlay，生产字典只读并用 hash 校验，避免"修一次污染全局"。

### 8.3 映射到当前项目的采纳清单

| 可采纳点 | 旧项目实现 | 当前差距 | 建议落点 |
|---|---|---|---|
| 统一 Finding 与去重 | `contracts.Finding` + `store.find_finding` | feedback 直接用，无统一问题模型 | 在 feedback 层引入 verdict/target/evidence，按 doc+target+verdict 去重 |
| 诊断先行 | `diagnose.py` 的 Diagnosis 契约 | triage 只有 root_cause/scope/confidence | 扩展 triage 输出 expected / rule_change / evidence / first_divergence / action |
| 确定性求正解 | `resolve.py` | feedback 无 expected，靠模型猜 | 生成 feedback 时从 OCR 表格/记录/封面自动求 expected |
| 三级降级 | L1→L2→L3 | 只有配方补丁一级 | 增加 L1 文档级覆盖（表修复/指定表绑定覆盖），L2 配方，L3 仅提案 |
| 算子白名单 | `l2.OPERATORS` + `validate_operator` | 自由 JSON Patch，可写任意路径 | 用算子注册表替代自由 patch，EFFECTIVE/ADVISORY 分开 |
| 表型签名隔离 | `table_signature()` | 无 | 候选只影响同类表型，避免全局回归 |
| table_repair | `table_fix.py` + `_validated_spec` | 缺 | 表头/合并/错列类问题走受限 spec + 重解析 |
| 七项门禁 | `gates.py` | 只有 target_fixed / new_errors / not removed | 补 evidence_grounded、reproduction、iteration_limit、regression |
| 迭代上限 | `max_iterations` + quarantine | 一次定生死 | 失败回灌后最多 2–3 轮，超限转人工 |
| 学习沉淀 | `learn.py` + learned overlay | 无记忆 | verified patch 入 alias/指令库，生产字典只读 + hash |

### 8.4 旧项目的教训（不要照搬的部分）

- 审查模型误报率 0.625，说明**不能把模型 finding 直接当修复输入**；必须先过证据门禁，默认 `proposed`。
- 旧项目 L2 的 shadow 是整文档重跑，定位精度不如新项目的 `table_id` 级 override；这一点新项目更好，应保留。
- 旧项目没有解决"补丁空间与验证空间不重合"的问题（它的 ADVISORY 算子也会进入流程），新项目要显式区分。

## 九、参考来源

- [Build self-improving document processing using Amazon Bedrock AgentCore（AWS, 2026-10）](https://aws.amazon.com/blogs/machine-learning/build-self-improving-document-processing-using-amazon-bedrock-agentcore/)
- [Agentic Self-Healing for Data & AI Pipelines（arXiv 2608.01955, 2026-08）](https://arxiv.org/html/2608.01955)
- [Automate ETL pipeline creation with Amazon Bedrock AgentCore and AWS Glue（AWS）](https://aws.amazon.com/blogs/big-data/automate-etl-pipeline-creation-with-amazon-bedrock-agentcore-and-aws-glue/)
- [Is the Cure Still Worse Than the Disease? Test Overfitting by LLMs in Automated Program Repair（arXiv 2511.16858）](https://arxiv.org/html/2511.16858v1)
- [Understanding Automated Program Repair Agents Through the Lens of Traceability（arXiv 2506.08311）](https://arxiv.org/html/2506.08311v2)
- [Adversarial Reasoning for Repair Based on Inferred Program Intent（arXiv 2505.13008）](https://arxiv.org/pdf/2505.13008)
- [ConStruM: A Structure-Guided LLM Framework for Context-Aware Schema Matching（arXiv 2601.20482）](https://arxiv.org/html/2601.20482)
- [Constraint-Guided Enterprise Data Mapping with Large Language Models（arXiv 2608.24218）](https://arxiv.org/html/2608.24218v1)
- [Evaluating LLMs for Schema Matching on Real-World Power Plant Registries（ACM e-Energy）](https://energy.acm.org/eir/poster-abstract-evaluating-large-language-models-for-schema-matching-on-real-world-power-plant-registries/)
- [RegReAct: Self-Correcting Multi-Agent Pipelines for Structured Regulatory Information Extraction（arXiv 2604.12054）](https://arxiv.org/html/2604.12054v1)
- [CodeStrange at GenSIE 2026: Metric-Aware Hybrid Pipelines for Schema-Guided IE](https://ceur-ws.org/Vol-4273/GenSIE2026_paper1.pdf)
- [Large Language Models as Control Planes for Industrial-Scale Web Data Extraction（VLDB 2025 Workshop）](https://www.vldb.org/2025/Workshops/VLDB-Workshops-2025/PhD/PhD25_4.pdf)
- [Safe Autonomy in Kubernetes: AI Troubleshooting Agents with Human-in-the-Loop（DEV）](https://dev.to/gde/safe-autonomy-in-kubernetes-building-ai-troubleshooting-agents-with-google-cloud-and-h8l)
- [Building an AI-Powered Kubernetes Incident Response System on AWS（DEV）](https://dev.to/omayrashraf/building-an-ai-powered-kubernetes-incident-response-system-on-aws-1nj8)
- [Controlled self-healing Amazon EKS clusters with AWS DevOps Agent and A2A remote agents（AWS）](https://aws.amazon.com/blogs/mt/controlled-self-healing-amazon-eks-clusters-with-aws-devops-agent-and-a2a-remote-agents/)
- [Salesforce: AI-Powered Self-Remediation Loop for Large-Scale Kubernetes Operations（ZenML）](https://www.zenml.io/llmops-database/ai-powered-self-remediation-loop-for-large-scale-kubernetes-operations)
- [What's new in Azure AI Document Intelligence（Microsoft Learn）](https://learn.microsoft.com/en-us/azure/ai-services/document-intelligence/whats-new?view=doc-intel-4.0.0)
- [UiPath Document Understanding: Machine Learning Extractor Trainer](https://docs.uipath.com/document-understanding/automation-cloud/latest/classic-USER-GUIDE/machine-learning-extractor-trainer)
- [Information Extraction from Unstructured Documents Using Augmented Intelligence（arXiv 2312.09880）](https://arxiv.org/pdf/2312.09880)
