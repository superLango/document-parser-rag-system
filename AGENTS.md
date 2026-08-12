# AGENTS.md — 项目协作与工程规范入口

本文件约束所有在本仓库工作的 AI 代理与协作者（包括 Codex）。

## 工作顺序

1. 先阅读本文件，再按任务类型阅读 `docs/` 对应规范：
   - 架构/模块边界 → `docs/ARCHITECTURE.md`
   - 技术选型 → `docs/TECH_STACK.md`
   - 目录与文件位置 → `docs/DIRECTORY_STRUCTURE.md`
   - 代码风格/分层 → `docs/CODING_STANDARDS.md`
   - 前后端接口 → `docs/API_CONTRACT.md`
   - 前端视觉 → `docs/UI_THEME.md`
   - 业务术语 → `docs/GLOSSARY.md`
   - 重构任务 → `docs/REFACTORING_PLAN.md`
2. 涉及旧系统行为时，以 `document-parser-rag-system/` 内**实际源码**为准。

## 硬性规则

- **禁止编造**：源码中不存在的内容必须说明“未找到相关代码”，不得凭印象补写。
- **路径标注**：修改/新增文件时，在交付说明中给出相对路径或绝对路径。
- **冻结基线**：`document-parser-rag-system/` 是旧版基线，默认只读；
  需要改动时必须显式说明理由并经确认。
- **规范优先**：新代码不得绕过 `docs/` 中已定规范（如主题色、目录结构、API 契约）。
- **增量迁移**：重构保持系统可运行；每次变更范围最小化，禁止一次性大爆炸式重写。
- **验证**：Python 后端改动用 ruff/mypy 与测试验证；前端改动用
  `pnpm type-check` 与 `pnpm lint` 验证；无法运行验证时必须说明原因。
- **页面闭环铁律**：前端功能（新增/改造/迁移）必须满足
  `qa/TESTING_PROCESS.md` 第 6 节页面全流程闭环测试——真实入口进入、
  数据真实落库、进入内页、返回状态一致；禁止仅用直接 URL 验证页面可达。

## 沟通约定

- 使用中文交流。
- 结论先行，附证据（文件路径、代码片段、文档章节）。
- 阻塞时说明具体阻塞点与可选方案，不臆断权限。
