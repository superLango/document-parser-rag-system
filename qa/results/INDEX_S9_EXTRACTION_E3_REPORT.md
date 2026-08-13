# 结构化抽取 E3 · 抽取流水线 报告

- 日期：2026-08-13
- 范围：类别构建与召回、上下文组装、Prompt 渲染、LLM 抽取、脚本后处理/校验、流水线编排。

## 交付内容

- [extraction_models.py](/home/grainuser/hansonDoc_RAG/backend/app/services/extraction/extraction_models.py)：ExtractionTarget / CategoryResult / SkippedFeature。
- [category_builder.py](/home/grainuser/hansonDoc_RAG/backend/app/services/extraction/category_builder.py)：Schema 驱动目标构建、term_base 名称展开（上限 200）、fixed_query + Query 术语集组装、现有 dense+BM25+RRF 检索、零命中剔除、类别 schema 构建。
- [context_assembler.py](/home/grainuser/hansonDoc_RAG/backend/app/services/extraction/context_assembler.py)：按 top_k/max_tokens/chars_per_token/截断标记拼接上下文。
- [prompt_renderer.py](/home/grainuser/hansonDoc_RAG/backend/app/services/extraction/prompt_renderer.py)：按类别精确匹配 Prompt，替换 ${feature/context/schema/return_type/字段/字段.属性/术语集.字段}；未绑定报错。
- [llm_extractor.py](/home/grainuser/hansonDoc_RAG/backend/app/services/extraction/llm_extractor.py)：OpenAI 兼容调用（json_mode/温度/max_tokens），BaseExtract 长文本分批，围栏剥离与 JSON 解析，必填字段缺失检测。
- [script_processor.py](/home/grainuser/hansonDoc_RAG/backend/app/services/extraction/script_processor.py)：按规则组执行 post/validation 脚本（受限子进程、术语集只读注入、超时/返回校验）。
- [pipeline.py](/home/grainuser/hansonDoc_RAG/backend/app/services/extraction/pipeline.py)：E3 主流程编排（配置解析→类别构建→类别并发抽取→结果汇总），进度回调；成功结果返回 categories/summary/timing，由 E1 任务服务落库。

## 测试覆盖率

| 层 | 用例数 | 覆盖内容 | 结果 |
|----|--------|----------|------|
| L1 单元 | 4 | JSON 解析/必填检测/上下文截断/Prompt 占位符 | ✅ |
| L2/L3 集成 | 1 | 配置+检索+术语集+Prompt+LLM+脚本全流程产出记录 | ✅ |
| L4 边界 | 2 | 零命中剔除、非法 JSON 不中断 | ✅ |
| L5 安全 | 1 | 非成员角色流水线 RLS 隔离返回空 | ✅ |

后端全量回归：**158/158 通过**（M34+M33+全局配置+E1+E2+E3）。

## 说明

- E1 失败路径用例已随 E3 更新：缺 LLM 资源配置触发失败（不再依赖占位报错）。
- 类别置信度阈值仍为预留（B15 第一版：零命中剔除）；命中分数/跳过原因已进入 summary。
