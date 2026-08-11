# S3 嵌入服务测试报告（M26 BGE-M3）

- 日期：2026-08-11
- 关联实现：`app/services/embedding/embedding_service.py`、`app/core/config.py`、`scripts/download_embedding_model.py`
- 模型：BAAI/bge-m3（1024 维，dense only，CLS 池化 + L2 归一化），权重位于 `models/bge-m3`（pytorch_model.bin 2.27GB + 配置文件）
- 下载源：ModelScope（HF/hf-mirror 不可达），脚本支持 HF 优先 + ModelScope 自动回退

## 用例统计

| 分层 | 测试文件 | 用例数 | 结果 |
|------|----------|--------|------|
| L1 单元 | `qa/unit/test_embedding_service_unit.py` | 7 | 通过 |
| L2 集成 | `qa/integration/test_embedding_integration.py` | 5 | 通过 |
| L3 功能 | `qa/integration/test_embedding_integration.py` | 1（含分块→嵌入链路） | 通过 |
| L4 边界 | `qa/boundary/test_embedding_boundary.py` | 3 | 通过 |
| L5 安全/并发 | `qa/security/test_embedding_concurrency.py` | 2 | 通过 |
| **合计** | | **17** | **17 通过 / 0 失败** |

## 覆盖率统计表

| 模块 | L1 单测 | L2 集成 | L3 功能 | L4 边界 | L5 安全 | 用例总数 | 是否全覆盖 |
|------|---------|---------|---------|---------|---------|----------|------------|
| M26 BGE-M3 嵌入服务 | 7 | 4 | 1 | 3 | 2 | 17 | 是（5/5 层） |

行覆盖率（coverage sysmon）：`embedding_service.py` 84 语句 0 未覆盖，**100%**。

## 关键覆盖点

1. 真实模型：1024 维、L2 归一化（norm≈1.0）、中文语义相似性（相关句 > 无关句）；
2. 批量与单条编码一致性（batch_size=2 与 1 结果逐元素一致）；
3. 懒加载 + 单例 + 空输入短路（不触发模型加载）；
4. 超长文本 8192/2048 token 截断、单字符/符号编码；
5. 并发：8 个并发 embed 调用串行锁不崩溃、结果与串行一致；
6. 错误隔离：坏模型路径报明确 RuntimeError，全局服务不受影响；
7. 分块产物 → title/content 双文本编码链路（S2+S3 衔接）；
8. warmup 预热路径。

## 工程校验

- `ruff check app/services/embedding/`：通过
- 模型加载：fp16 + cuda，加载约 2s，首条推理正常
- 下载脚本：HF 优先（hf-mirror），失败自动回退 ModelScope（`allow_file_pattern` 仅拉取 PyTorch 权重 + 配置，跳过 onnx）

## 结论

S3 通过铁律验收：五层全覆盖（17/17），行覆盖率 100%，真实权重推理与并发安全验证通过。
