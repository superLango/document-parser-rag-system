---
title: 结构化抽取
category: 核心功能
order: 4
---

# 结构化抽取

结构化抽取从文档中按 Schema 定义提取字段，支持流式返回与 Hook 扩展。

## Schema 管理

Schema 定义抽取字段的结构，支持父子层级：

- **父分类**：如「材料检测」下包含多个子 Schema
- **子 Schema**：具体字段定义，如「拉伸试验」「疲劳试验」
- **字段类型**：string / number / boolean / date / enum / array
- **示例字段**：作为 LLM 抽取的 few-shot 示例

抽取时使用合并后的完整 Schema（父 + 所有子），获取全部字段定义。

## 流式抽取

在「抽取」标签执行抽取时，系统通过 SSE（Server-Sent Events）流式返回：

1. 选择已解析的文档
2. 选择目标 Schema
3. 点击「开始抽取」
4. 字段逐步填充，实时显示进度

流式抽取基于 vLLM 单 chunk 处理，最大化推理资源利用率。

## 领域模板

每个领域模板预置了：

- **类别定义**：文档分类规则
- **正则规则**：高置信度字段的正则提取
- **字段模板**：常见字段定义
- **字典配置**：基础字典映射

应用模板后可在配置中心进一步自定义。

## Hook 机制

Hook 是每 KB 独立的 Python 脚本，位于 `kb_hooks/{kb_id}/hooks.py`，提供 6 个标准接口：

| 接口 | 用途 |
|------|------|
| `extract_candidates` | 预处理抽取候选 |
| `build_category_schema` | 按类别构建 Schema |
| `validate_record` | 校验抽取记录 |
| `post_process` | 抽取后处理 |
| `category_match` | 文档类别匹配 |
| `build_doc_info_prompt` | 构建文档信息提示 |

Hook 加载失败时自动回退到默认实现，不阻断主流程。

## 抽取结果

抽取结果以结构化 JSON 存储，可在文档详情中查看。支持导出为 Excel/CSV 供下游使用。
