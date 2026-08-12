# 术语集问题修复报告（描述保存 / 名称列策略 / 审核流 / 缓存）

- 日期：2026-08-12

## 1. 术语集描述没有成功保存

根因：
- 前端创建 API/DB 术语集时 payload 未携带 `description`（manual 分支有，api/db 分支漏传）；
- 编辑器页没有“编辑术语集信息”入口，导致描述修改无处保存。

修复：
- `frontend/src/views/kb/KbGlossaryPage.tsx`：api/db 创建 payload 补 `description`；
- `frontend/src/views/kb/KbGlossaryEditorPage.tsx`：新增“编辑信息”弹窗（名称/描述），保存调用更新接口。

## 2. 接口/数据库术语集第一列默认成了术语

原项目实现（`kb_term_bases.py::_rows_to_terms`）：
- 名称列按白名单识别：`name/term/value/term_name/名称/术语名称`；
- 白名单未命中时 `columns[0]` 兜底，再回退 `rows[0]` 第一列；
- api/db 类型 term_name 仅用于搜索，所有字段存 extras。

当前实现修复（不再第一列兜底）：
- 保留白名单识别（term_name/term/name/value/名称/术语名称/词汇/关键词）；
- **去掉第一列兜底**：未识别名称列时跳过该行并统计 `skipped`，同步提示“跳过 N 行（未识别名称列）”；
- 新增“字段配置”中的“术语名称列”单选：保存为 `column_aliases["__name_column__"] = 原始列名`，
  同步时按该列生成术语名；显示名与名称列互不冲突；
- `backend/app/services/glossary/term_base_service.py` 同步返回 `{imported, total, skipped}`。

## 3. 通过/驳回的实质作用（结论：保留，作用如下）

当前审核流（pending/active/rejected）的实际作用：
1. **状态展示与筛选**：术语管理页可按“待审核/已通过/已驳回”过滤，状态徽标可见；
2. **抽取联动硬约束（已实现，抽取阶段消费）**：`term_base_loader` 只加载 `status=active` 的词条，
   pending/rejected 不参与术语展开/分组取值——这是审核流未来的核心价值；
3. **导出留痕**：CSV 导出包含状态列，审核人/审核时间落库（reviewed_by/reviewed_at）；
4. **审计**：审核操作记录 `term.review` 审计日志。

当前“看起来没用”是因为抽取模块尚未接入（C6 预留），下游消费未生效；
删除该功能需要同时移除 loader 的 active 过滤、外部同步默认 pending、审核端点与 UI，
且与方案 C2（原项目保留审核流）冲突。因此保留，后续抽取联动时即产生实质约束。

## 4. 附带修复：同步后进入编辑器显示旧数据

根因：全局 React Query staleTime=30s，先进入编辑器（同步前，空列表）→ 返回列表 →
同步成功 → 再进入编辑器时命中 30s 内旧缓存，未重新请求，页面仍显示空。

修复：`KbGlossaryPage.invalidate` 扩展失效 key（kb-term-base/kb-terms/kb-term-categories），
同步/删除/创建后编辑器缓存一并失效。

## 验证

| 项目 | 结果 |
|------|------|
| 后端五层全量回归 | ✅ 70/70 |
| ruff | ✅ 通过 |
| S4 E2E（描述保存、无名称列跳过、字段配置指定名称列后重同步） | ✅ 16/16 |
| S5 E2E（卡片入口进入、编辑信息描述保存） | ✅ 17/17 |
| 前端 type-check + build | ✅ 通过 |
