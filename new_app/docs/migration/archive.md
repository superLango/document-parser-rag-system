# 旧系统归档清单

> 日期：2026-11-12
> 原则：**只读保留、不删除、不修改**；归档不阻塞新旧并行观察。
> 关联：[切换方案](cutover.md)、[回滚手册](../runbooks/rollback.md)

## 1. 归档范围

| 类别 | 路径 | 体量 | 状态 |
|---|---|---|---|
| 旧代码 | `legacy/` | ≈935 MB | 只读保留；本轮不改动 |
| 旧平台数据库 | `data/platform/platform.db` | 1.0 MB | 只读保留（SQLite） |
| 旧上传文件 | `data/platform/uploads/` | 4.3 MB 目录 | 只读保留 |
| 旧验证/审计数据 | `data/validation-2026-11-06/`、`data/audit-2026-11-09/`、`data/reparse20-20261109/` | 大（含 PDF/JSON） | 只读保留，作为效果对比基线 |
| 旧词典快照 | `legacy/metal-doc-agent/configs/business_dictionary*.json`、`dictionaries/` | ≈1.6 MB | 只读保留；已导入新系统 |
| 旧容器 | `hanson-r1-*`（web/platform-api/engine-api/postgres/worker） | — | 保留运行至观察期结束 |
| 旧前端构建 | `legacy/apps/web/dist/` | — | 只读保留 |

## 2. 归档动作（当前状态）

- [x] 旧代码目录未修改（仅作为参考与对比）。
- [x] 旧数据库与上传文件未迁移、未写入。
- [x] 旧词典已导入新系统（2203 条，对账通过），旧文件保留。
- [x] 旧服务保持运行，可随时回滚。
- [ ] 观察期结束后打只读标签（建议 `legacy-r1-archive-20261112`）。
- [ ] 观察期结束后停止旧容器（保留数据卷/目录）。
- [ ] 归档清单签字。

建议的只读标签（观察期结束后执行，本轮不执行）：

```bash
git tag -a legacy-r1-archive-20261112 -m "Legacy R1 read-only archive before cutover"
git push origin legacy-r1-archive-20261112
```

## 3. 保留周期

| 项 | 保留期 | 说明 |
|---|---|---|
| 旧代码 | ≥1 个发布周期 | 只读；不再合入修改 |
| 旧数据库/上传 | ≥1 个发布周期 | 只读；用于对比与回滚 |
| 旧容器 | 观察期 | 回滚通道；结束后停止但保留卷 |
| 旧词典快照 | 长期 | 溯源与再导入 |

## 4. 禁止事项

- 不删除 `legacy/`、`data/platform/`、旧数据卷。
- 不把旧文档/运行/产物导入新系统（Q4 决策）。
- 不在旧系统上执行新功能开发。
- 不修改旧数据库结构。

## 5. 归档验证

- [x] 旧 Web `http://localhost:8080/` 返回 200。
- [x] 旧 API `http://localhost:8000/health` 返回 `{"status":"ok","version":"0.1.0",...}`。
- [x] 新系统词典版本与旧系统一致：`hanson-ht-64c316a7`。
- [x] 回滚演练通过（455 ms 切回旧系统）。
