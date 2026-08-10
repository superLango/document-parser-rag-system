# UI 交互与动效规范

> 本文档定义 HansonDOC RAG 重构版前端的**交互语言与动效规则**，与
> [UI_THEME.md](UI_THEME.md) 配套使用。动效 token（时长/缓动）以
> UI_THEME.md 第 5 节为准，样式落地见
> [frontend/src/styles/globals.css](/home/grainuser/hansonDoc_RAG/frontend/src/styles/globals.css)。

## 1. 设计原则

1. **动效服务于反馈，不做装饰**：每个动效都对应一种状态变化（进入/悬停/按下/弹出/消失）。
2. **克制**：单屏内同时进行中的动效实例不超过约 6 个（骨架屏加载态除外），
   同一区块不得叠加三种以上动画。
3. **可降级**：所有动效必须被 `prefers-reduced-motion` 关闭，globals.css 已提供全局降级。
4. **节奏一致**：悬停反馈 ≤ 220ms，弹窗/Toast ≤ 420ms，页面编排入场 ≤ 520ms。
5. **键盘可达**：任何可交互元素必须有可见焦点环，不依赖 hover 承载关键操作。

## 2. 动效清单（权威）

| 动效 | 触发 | 时长/缓动 | 用途 | 代码位置 |
|------|------|-----------|------|----------|
| `fade-up` | 页面/区块首次进入 | 520ms `ease-out-soft`，组内错峰 60-240ms | 标题、卡片、表单分区编排入场 | [globals.css](/home/grainuser/hansonDoc_RAG/frontend/src/styles/globals.css)、[PageHeader.tsx](/home/grainuser/hansonDoc_RAG/frontend/src/components/PageHeader.tsx) |
| `fade-in` | 遮罩/轻量内容出现 | 360ms `ease-out` | 弹窗遮罩、页脚淡入 | [globals.css](/home/grainuser/hansonDoc_RAG/frontend/src/styles/globals.css) |
| `scale-in` | 浮层/下拉出现 | 300ms `ease-out-soft` | 用户菜单、弹窗面板 | [AppShell.tsx](/home/grainuser/hansonDoc_RAG/frontend/src/layouts/AppShell.tsx)、[dialog.tsx](/home/grainuser/hansonDoc_RAG/frontend/src/components/ui/dialog.tsx) |
| `toast-in` | Toast 出现 | 280ms `ease-out-soft`，4s 自动消失 | 操作结果反馈 | [toast.tsx](/home/grainuser/hansonDoc_RAG/frontend/src/components/ui/toast.tsx) |
| `aurora-drift` | 持续（14s/18s/22s 交替） | `ease-out-soft` | 登录页/横幅/侧栏 Logo 的绿意光晕氛围光源 | [globals.css](/home/grainuser/hansonDoc_RAG/frontend/src/styles/globals.css) |
| `doc-grid` | 静态底纹 | — | “文档书架”网格隐喻，横幅背景 | [globals.css](/home/grainuser/hansonDoc_RAG/frontend/src/styles/globals.css) |
| `btn-shine` | 主按钮 hover | 700ms 流光 | 主按钮品牌光效 | [button.tsx](/home/grainuser/hansonDoc_RAG/frontend/src/components/ui/button.tsx) |
| 按压反馈 | 主按钮按下 | `active:scale-[0.98]` | 物理按压感 | [button.tsx](/home/grainuser/hansonDoc_RAG/frontend/src/components/ui/button.tsx) |
| `card-hover` | 卡片 hover | 220ms `ease-out-soft`，上浮 -3px + `shadow-lift` | 可交互卡片浮起 | [card.tsx](/home/grainuser/hansonDoc_RAG/frontend/src/components/ui/card.tsx) |
| 侧栏活动指示条 | 导航 hover/激活 | 200ms | 当前页标识 | [AppShell.tsx](/home/grainuser/hansonDoc_RAG/frontend/src/layouts/AppShell.tsx) |
| `skeleton-shimmer` | 加载中 | 1.4s 循环 | 骨架屏微光 | [globals.css](/home/grainuser/hansonDoc_RAG/frontend/src/styles/globals.css) |
| `pulse-dot` | 持续（2s 呼吸） | `ease-out` | “服务运行中/在线”状态点 | [globals.css](/home/grainuser/hansonDoc_RAG/frontend/src/styles/globals.css) |
| 焦点环 | `:focus-visible` | 即时 | 双层环（2px 背景色 + 4px `--ring`） | [globals.css](/home/grainuser/hansonDoc_RAG/frontend/src/styles/globals.css) |

## 3. 页面级交互规范

### 3.1 登录页（[LoginPage.tsx](/home/grainuser/hansonDoc_RAG/frontend/src/views/LoginPage.tsx)）

- 双栏：左侧品牌区（`doc-grid` + 2~3 个 `aurora`），右侧居中表单。
- 入场编排：Logo/品牌区 0ms → 标题 80ms → 特性卡 180ms → 页脚 300ms；
  表单侧标题 60ms → 用户名 120ms → 密码 180ms → 按钮 240ms → 页脚 320ms。
- 密码框有显隐切换（`Eye/EyeOff`），loading 时按钮显示 `Loader2` 旋转并禁用输入。
- 错误通过 Toast 反馈，不做内联红字，避免打断视觉节奏。

### 3.2 工作台（[DashboardPage.tsx](/home/grainuser/hansonDoc_RAG/frontend/src/views/DashboardPage.tsx)）

- 签名横幅：`doc-grid` + `aurora` + 服务状态 `pulse-dot`，是“品牌签名元素”。
- 统计卡四张错峰入场（0/60/120/180ms），图表卡 120ms、系统信息 180ms、
  最近活动 240ms。
- 图表第一序列固定 `--chart-1`，Tooltip 使用圆角白底 + `shadow-modal` 同级阴影。

### 3.3 个人中心（[ProfilePage.tsx](/home/grainuser/hansonDoc_RAG/frontend/src/views/ProfilePage.tsx)）

- 头部账户卡复用签名横幅语言（`doc-grid` + `aurora` + 头像），展示角色与账号状态徽章。
- 资料卡与密码卡错峰入场，均可 `card-hover` 浮起；密码强度实时反馈。
- 表单提交成功/失败统一走 Toast，不额外弹窗。

### 3.4 管理页（用户管理 / 审计日志）

- 弹窗统一 `animate-fade-in` 遮罩 + `animate-scale-in` 面板，关闭按钮在右上角。
- 危险操作（删除/禁用）必须二次确认弹窗；操作完成后刷新列表并 Toast 反馈。
- 表格行 hover 使用 150ms 浅绿底过渡，不做位移。

## 4. 禁止事项

1. 禁止自定义散落阴影、颜色、圆角绕过 UI_THEME.md token。
2. 禁止新增无限循环动画（`pulse-dot`/`aurora-drift` 之外的常驻动画需评审）。
3. 禁止 hover 位移超过 4px、缩放超过 1.03，禁止 3D 翻转等强效果。
4. 禁止同一卡片同时启用 `card-hover` 与自写 transform 动画（冲突且破坏性能）。
5. 禁止用动画代替状态文案（如“成功”只闪绿不显示结果）。
6. 禁止把 `animate-spin` 用于非 loading 元素；旋转必须语义化。
7. 禁止移除 `:focus-visible` 双层焦点环。
8. 禁止在 `prefers-reduced-motion: reduce` 下保留位移/闪烁动画。

## 5. 无障碍与降级

- 键盘可完整操作：导航、表单、弹窗、下拉菜单、Toast 关闭路径均可用 Tab/Enter/Esc。
- 全局焦点环由 `:focus-visible` 统一提供，组件层不得覆盖为 `outline: none`。
- `prefers-reduced-motion: reduce` 下所有动画/过渡时长压至 0.01ms（globals.css 已实现）。
- 装饰性光晕/网格一律 `aria-hidden="true"`，不进入读屏。
- Toast 容器 `z-[100]` 置于弹窗之上，最多保留 4 条，避免堆叠。

## 6. 新增动效的接入流程

1. 先在本文档登记（名称/触发/时长/用途）；
2. 在 [globals.css](/home/grainuser/hansonDoc_RAG/frontend/src/styles/globals.css) 实现
   `@keyframes` + `.animate-*` 类，并确认 reduced-motion 覆盖；
3. 页面中只引用现有类名，禁止内联 `style={{ animation: ... }}` 自定义。
