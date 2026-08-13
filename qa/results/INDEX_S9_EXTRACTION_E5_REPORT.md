# 结构化抽取 E5 · 前端页面 报告

- 日期：2026-08-13
- 范围：抽取列表页、抽取详情页、路由、轮询进度、表格/JSON/历史/导出/删除、重新抽取；E2E 页面闭环。

## 交付内容

- [extraction.ts](/home/grainuser/hansonDoc_RAG/frontend/src/api/modules/extraction.ts)：列表/启动/状态/结果/历史/导出/删除 API。
- [KbStructuredExtractionPage.tsx](/home/grainuser/hansonDoc_RAG/frontend/src/views/kb/KbStructuredExtractionPage.tsx)：列表页（RLS 徽标 + 刷新、行内历史/抽取、历史弹窗）。
- [KbExtractionDetailPage.tsx](/home/grainuser/hansonDoc_RAG/frontend/src/views/kb/KbExtractionDetailPage.tsx)：详情页（左原文档预览 / 右 Schema 卡片 + 开始/重新抽取 + 进度条/四步流程 + 表格/JSON 双视图 + 缺失字段 + 历史回看 + 导出 + 删除确认），2 秒轮询、退出重进恢复。
- 路由：`/kb/:id/extraction`（列表）、`/kb/:id/extraction/:documentId`（详情），替换占位页。
- 修复：索引成功状态统一为 `indexed`（此前误用 completed，导致可抽取列表为空/启动前置拒绝）。

## E2E（页面闭环）

| 场景 | 结果 |
|------|------|
| E5-01 菜单进入抽取列表页并展示可抽取文档 | ✅ |
| E5-02 点击抽取进入详情页（Schema 卡片 + 原文档预览） | ✅ |
| E5-03 开始抽取 → 进度轮询 → 失败提示（不可达 LLM） | ✅ |
| E5-04 重新抽取可再次发起 | ✅ |
| E5-05 返回列表页状态一致 | ✅ |
| E5-06 移动端可用 | ✅ |

后端全量回归：168/168；type-check/build 通过。

## 说明

- E2E 使用真实上传→解析→索引→抽取链路（不可达 LLM 触发失败路径），覆盖入口闭环。
- 表格/JSON 双视图与历史回看在结果存在时生效；LLM 可用后即可完整验证。
