# 编码规范

## 1. 通用原则

- 配置优先、禁止硬编码：服务地址/模型名/阈值必须来自配置中心或 `.env`。
- 无静默回退：关键配置缺失即报错；降级必须显式记录日志并在前端提示。
- 变更最小化：一次提交只做一件事。
- 代码注释说明“为什么”，不重复“是什么”。

## 2. Python（后端）

- 格式化与检查：`ruff format` + `ruff check` + `mypy`（strict 可选，至少 no-any-return）。
- 类型注解：所有公共函数完整注解；禁止裸 `Any` 扩散。
- 分层依赖：`endpoints → services → models`；禁止 endpoints 直连 DB；
  services 禁止 import FastAPI Request/Response。
- 数据库会话：路由用 `Depends(get_db)`；worker 用 `AsyncSessionLocal` 并显式
  `_activate_kb_rls`。
- 异步：IO 密集操作必须 async；本地模型推理用 `asyncio.to_thread` 包装。
- 异常：业务异常统一抛 `AppException` 子类，禁止裸 raise 字符串。
- 日志：使用 structlog，携带 `kb_id` / `document_id` / `task_id` / `trace_id`。
- 循环依赖：优先重构模块边界；禁止用函数内 import 掩盖（迁移期允许并登记）。

## 3. TypeScript / React（前端）

- 严格模式：`tsconfig` 开启 `strict`；禁止 `any`（必要处显式 `unknown` + 收窄）。
- 组件：函数组件 + hooks；默认导出组件文件；props 使用 `interface` 并导出。
- 状态：服务端数据用 TanStack Query；客户端全局态用 Zustand；
  局部 UI 态用 `useState`。
- 样式：只用 Tailwind 工具类与主题 token；禁止内联色值；
  颜色一律引用 `docs/UI_THEME.md` 定义的 token。
- 请求：统一走 `src/api/` axios 实例（自动注入 JWT、`X-Trace-Id`、统一解包）。
- 格式化：ESLint + Prettier，`pnpm lint` / `pnpm type-check` 必须通过。
- 命名：hooks `useXxx`；事件回调 `onXxx`；布尔状态 `isXxx` / `canXxx`。

## 4. Git 规范

- 提交信息使用 Conventional Commits：
  `feat|fix|refactor|docs|chore|test|perf(scope): description`。
- 分支命名：`feat/ui-theme`、`fix/qa-history`、`refactor/backend-models`。
- 禁止直接向 main 提交；PR 必须通过 CI（lint + type-check + 后端测试）。

## 5. 文档规范

- 业务术语必须使用 `docs/GLOSSARY.md` 的定义，不另造同义词。
- 新功能必须有对应 API/UI/架构文档更新，否则视为未完成。
