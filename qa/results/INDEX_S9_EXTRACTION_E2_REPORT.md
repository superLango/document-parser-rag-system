# 结构化抽取 E2 · 配置解析与 LLM 层 报告

- 日期：2026-08-13
- 范围：抽取领域配置解析器、OpenAI 兼容 LLM 客户端、KB“资源与配置”LLM 服务表单与端点。

## 交付内容

1. [extraction_resolver.py](/home/grainuser/hansonDoc_RAG/backend/app/services/extraction/extraction_resolver.py)
   - `ExtractionDomainConfig`：global_config / schema_templates（含类别与字段）/ prompt_templates / rule_groups（含类别规则脚本）/ term_bases；
   - 全部读取当前项目配置表，不做默认合并。
2. [llm_client.py](/home/grainuser/hansonDoc_RAG/backend/app/services/llm/llm_client.py)
   - `OpenAICompatibleClient`：chat/completions、json_mode、温度/最大 token、超时、连通性 ping；
   - `LLMError`、`mask_api_key`；支持注入 transport 便于测试。
3. [kb_resource_service.py](/home/grainuser/hansonDoc_RAG/backend/app/services/kb_resource_service.py)
   - `services.llm_vllm` 读写（enabled/api_base/model/api_key/timeout），GET 只返回掩码；
   - `test_llm_resource` 连通性测试；`build_llm_client` 供 E3 流水线使用。
4. 端点 [kb_resources.py](/home/grainuser/hansonDoc_RAG/backend/app/api/v1/endpoints/kb_resources.py)
   - `GET/PUT /kb/{id}/resources/llm`（成员读 / editor+ 写，audit）、`POST /llm/test`（editor+）。
5. 前端 [KbResourcesPage.tsx](/home/grainuser/hansonDoc_RAG/frontend/src/views/kb/KbResourcesPage.tsx)
   - 新增“LLM 服务”卡片：启用开关、api_base/model/api_key/timeout、保存与测试连接；viewer 只读。

## 测试覆盖率

| 层 | 用例数 | 覆盖内容 | 结果 |
|----|--------|----------|------|
| L1 单元 | 5 | LLM json_mode/HTTP 错误/非法地址/Key 掩码/Schema 校验 | ✅ |
| L2/L3 集成 | 3 | 资源配置 CRUD+掩码、测试连接不可达、解析器聚合 | ✅ |
| L4 边界 | 2 | 非法 api_base、未启用/缺模型构建客户端报错 | ✅ |
| L5 安全 | 3 | viewer 只读/editor 写、非成员 403、跨 KB 隔离 | ✅ |

后端全量回归：**150/150 通过**（M34+M33+全局配置+E1+E2）；type-check/build/ruff 通过。

## 说明

- E3 将通过 `kb_resource_service.build_llm_client` 获取 LLM 端点，并用 resolver 输出完成类别召回/检索/抽取。
