# 帮助文档维护规范

> 帮助文档面向系统用户，展示**当前已开发完成功能**的使用说明与操作截图，
> 随开发阶段逐步完善，并在功能变化时同步修改。
> 前端页面：`/help`（帮助文档）、`/about`（关于）。

## 1. 内容来源

- 功能说明与步骤：`frontend/src/content/help.ts`（`helpSections` 数组）。
- 操作截图：`frontend/public/help/*.png`，来自各阶段测试产物（`qa/results/`、
  `docs/ui-screenshots/`），人工挑选后复制为静态资源。
- 关于页数据：`/api/v1/system/info` 实时返回（应用名/版本/环境/数据库/Python/功能特性）。

## 2. 功能 → 截图映射表

| 帮助章节 | 截图文件 | 来源 |
|----------|----------|------|
| 登录与工作台 | `login.png` / `dashboard.png` | 登录页与工作台截图 |
| 个人中心 | `profile.png` | 个人中心截图 |
| 用户与角色权限 | `users.png` / `roles.png` | 用户管理/角色管理截图 |
| 知识库（卡片入口） | `kb-cards.png` | 知识库卡片列表截图 |
| 知识库概览与成员 | `kb-overview.png` / `kb-members.png` | KB 概览/成员页截图 |
| 资源与外部访问令牌 | `kb-external.png` | 资源与配置截图 |
| 文档解析（待解析/原文档预览/内页联动） | `documents-queued.png` / `documents-original-preview.png` / `documents-viewer.png` | 文档解析页与内页截图 |
| 专业术语集 | `glossary.png` | 术语集主页截图（S8-S4 E2E 产物） |
| 术语管理 | `glossary-editor.png` | 术语管理页截图（S8-S5 E2E 产物） |
| 向量搜索 | `vector-search.png` | 向量搜索页截图（S7 E2E 产物） |
| 工作空间与 API 密钥 | `workspaces.png` / `api-keys.png` | P2 功能截图 |

## 3. 更新流程（每阶段强制）

1. 新功能开发完成并通过测试后，运行对应 E2E 生成最新截图（`qa/results/`）。
2. 挑选代表性截图，覆盖到 `frontend/public/help/`（保持文件名稳定，见映射表）。
3. 在 `frontend/src/content/help.ts` 更新/新增章节：标题、说明、操作步骤、截图路径。
4. 同步更新本文档映射表与 [MAINFLOW_PLAN.md](MAINFLOW_PLAN.md) 的功能清单。
5. `/about` 无需维护，自动读取系统信息接口。

## 4. 约定

- 帮助文档只写**已上线**能力；未开发模块在知识库内为占位页，不写入帮助。
- 截图不得包含敏感数据（真实密码、密钥明文）；外部访问令牌截图使用掩码前缀。
- 步骤编号从 1 开始，语言为简体中文，措辞与 UI 文案一致。
- 每阶段帮助文档改动纳入测试（E2E L3M8-03 校验章节与截图数量）。
