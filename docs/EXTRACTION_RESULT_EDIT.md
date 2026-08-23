# 抽取结果人工编辑（新增/修改/删除 + 保存）

> 版本：v1 · 2026-08-23 · 状态：已实现并部署验证

## 一、功能说明

结构化抽取结果页（含系统对接结果页）允许用户对抽取结果进行人工修正：

- **修改记录**：表格单元格直接编辑；
- **新增记录**：类型内「新增记录」按钮（以该类型现有字段初始化空行）；
- **删除记录**：每行删除按钮；
- **删除类型**：类型头部删除按钮 + 确认弹框（删除该类型及其全部记录）；
- **保存**：右下角「保存修改」按钮（存在改动时出现），点击后保存为新版本（version +1，旧版归档到历史）；
- **取消**：放弃本次编辑，恢复已保存结果；
- 无编辑权限（非 editor+）时表格保持只读。

系统对接结果页（`/integration/task/:taskId`，iframe 内嵌同一抽取详情页）自动具备相同能力。

## 二、涉及文件

### 后端

| 文件 | 改动 |
|---|---|
| `backend/app/schemas/extraction.py` | 新增 `ExtractionResultUpdate`（categories 数组） |
| `backend/app/api/v1/endpoints/kb_extraction.py` | 新增 `PUT /kb/{kb_id}/extraction/{document_id}/result`：editor+ 权限，读取最新结果 → `result_store.save_result` 保存编辑后的 categories（version +1，旧版归档 history） |

### 前端

| 文件 | 改动 |
|---|---|
| `frontend/src/api/modules/extraction.ts` | `updateResult(kbId, docId, categories)` |
| `frontend/src/views/kb/KbExtractionDetailPage.tsx` | 结果表格可编辑（draft 状态）：单元格输入、记录增删、类型删除（确认弹框）、右下角保存/取消、JSON 视图同步 |

## 三、接口

### 保存编辑结果

`PUT /kb/{kb_id}/extraction/{document_id}/result`

请求体：

```json
{
  "categories": [
    {
      "feature": "室温拉伸",
      "records": [{ "材料牌号": "GH4169", "项目名称": "抗拉强度(Rm)", "标准要求": "≥1275" }],
      "rejected": [],
      "missing_fields": []
    }
  ]
}
```

响应：`{"version": 2}`（保存后新版本号）。要求存在最新结果；无结果返回 404。

## 四、数据行为

- 保存复用 `result_store.save_result`：旧版本归档到 `extraction_history`（保留最近 50 条），`extraction_results` 更新为新版本，`documents.extraction_status` 保持 completed；
- 前端编辑为本地 draft（深拷贝），仅保存时提交，中途取消不落库；
- JSON 视图实时展示编辑中的 draft。

## 五、验证

- 单元测试：`qa/unit/test_integration_unit.py`（结果保存 Schema 校验）；
- 前端 `tsc --noEmit` 通过；
- 容器部署端到端：模拟结果 version 1 → PUT 编辑（修改记录/删除类型/新增类型）→ version 2，GET 返回更新后的类别与记录内容。
