# UI 主题规范（浅绿 + 白）—— 权威定义

> 本文档定义 HansonDOC RAG 重构版前端的**全部视觉 token**，与
> `frontend/src/styles/globals.css` 一一对应；交互与动效规范见
> [UI_INTERACTION.md](UI_INTERACTION.md)。

## 1. 设计参考：LightRAG WebUI

调研结论（来源：HKUDS/LightRAG 官方仓库与 DeepWiki）：

- 技术栈：React 19 + TypeScript + Vite + Tailwind CSS 4 + Radix UI（shadcn/ui 风格 CSS token）。
- 设计气质：白底 + 大留白 + 中性色文字 + 圆角 + token 化主题。
- 默认色板偏中性灰，**绿色只出现在图表**。

**我们在此基础上定制**：保留“干净、留白、token 化、可扩展”的骨架，
把品牌主色替换为**浅绿 + 白**，形成轻量、清爽、适合文档/知识库类产品的视觉语言。

## 2. 色彩体系

### 2.1 基础色板（权威值，禁止内联替换）

| Token | HEX | 用途 |
|-------|-----|------|
| `--background` | `#FFFFFF` | 页面主背景 |
| `--background-soft` | `#F7FCF9` | 页面底色、分区背景 |
| `--foreground` | `#17221C` | 主文字（深绿灰） |
| `--muted-foreground` | `#64748B` | 次要文字 |
| `--card` / `--popover` | `#FFFFFF` | 卡片/浮层 |
| `--primary` | `#10B981` | 品牌主色（链接/图标/强调） |
| `--primary-strong` | `#059669` | 主按钮实底（配合白字） |
| `--primary-hover` | `#047857` | 主按钮 hover |
| `--primary-foreground` | `#FFFFFF` | 主色上的文字 |
| `--secondary` | `#ECFDF5` | 次级背景（浅绿） |
| `--secondary-foreground` | `#065F46` | 次级背景文字 |
| `--accent` | `#D1FAE5` | 选中/高亮底 |
| `--accent-foreground` | `#065F46` | 高亮底文字 |
| `--muted` | `#F0FDF4` | 弱化背景 |
| `--border` | `#DFEBE4` | 边框（绿调浅灰） |
| `--input` | `#DFEBE4` | 输入框边框 |
| `--ring` | `#34D399` | 焦点环 |
| `--destructive` | `#EF4444` | 危险操作 |
| `--success` | `#16A34A` | 成功状态 |
| `--warning` | `#F59E0B` | 警告状态 |
| `--info` | `#0EA5E9` | 信息状态 |
| `--radius` | `0.625rem` | 统一圆角基准 |

### 2.2 侧边栏

| Token | HEX |
|-------|-----|
| `--sidebar` | `#F8FDFB` |
| `--sidebar-foreground` | `#1F2937` |
| `--sidebar-primary` | `#059669` |
| `--sidebar-primary-foreground` | `#FFFFFF` |
| `--sidebar-accent` | `#D1FAE5` |
| `--sidebar-accent-foreground` | `#065F46` |
| `--sidebar-border` | `#E5F0EA` |
| `--sidebar-ring` | `#34D399` |

### 2.3 图表

| Token | HEX |
|-------|-----|
| `--chart-1` | `#10B981`（品牌绿，第一序列必须使用） |
| `--chart-2` | `#0EA5E9` |
| `--chart-3` | `#F59E0B` |
| `--chart-4` | `#8B5CF6` |
| `--chart-5` | `#F43F5E` |

### 2.4 绿色阶（扩展用）

| 色阶 | HEX |
|------|-----|
| 50 | `#ECFDF5` |
| 100 | `#D1FAE5` |
| 200 | `#A7F3D0` |
| 300 | `#6EE7B7` |
| 400 | `#34D399` |
| 500 | `#10B981` |
| 600 | `#059669` |
| 700 | `#047857` |
| 800 | `#065F46` |
| 900 | `#064E3B` |

## 3. 字体体系

| 角色 | 字体 | 说明 |
|------|------|------|
| 展示（Display） | Geist Variable | 标题 `h1-h4`、`.font-display`、数据数字，字距 `-0.015em` |
| 正文（Body） | 系统中文：PingFang SC / Hiragino Sans GB / Microsoft YaHei | 中文正文由系统字体渲染，避免全量字体包体积 |
| 数据/代码（Mono） | Geist Mono Variable | 路径、ID、状态码、时间等 `font-mono` |

原则：**拉丁与数字用 Geist，中文交给系统字体**——既保留品牌个性，又不引入数百个中文字体分片。

## 4. 阴影与层级

| Token | 值 | 用途 |
|-------|-----|------|
| `--shadow-soft` | `0 1px 2px rgb(6 78 59/.04), 0 4px 16px rgb(6 78 59/.05)` | 卡片默认 |
| `--shadow-lift` | `0 2px 4px rgb(6 78 59/.06), 0 12px 32px rgb(6 78 59/.10)` | 卡片 hover 浮起 |
| `--shadow-glow` | `0 0 0 1px rgb(16 185 129/.12), 0 8px 32px rgb(16 185 129/.18)` | 主按钮/输入聚焦/品牌图标 |
| `--shadow-modal` | `0 8px 20px rgb(6 78 59/.08), 0 32px 80px rgb(6 78 59/.18)` | 弹窗/Toast |

## 5. 动效 token

| Token | 值 | 用途 |
|-------|-----|------|
| `--ease-out-soft` | `cubic-bezier(0.22, 1, 0.36, 1)` | 统一出场/悬停缓动 |
| `--dur-fast` | 140ms | 状态切换、按下 |
| `--dur-base` | 220ms | hover 微交互、Toast |
| `--dur-slow` | 420ms | 弹窗、编排入场 |

动效清单与使用规则见 [UI_INTERACTION.md](UI_INTERACTION.md#3-动效语言)。

## 6. 使用规则（强制）

1. 页面背景：`--background`；分区/侧栏：`--background-soft` 或 `--sidebar`。
2. 主按钮：`--primary-strong` 底 + 白字；hover `--primary-hover`；必须带 `btn-shine` 流光。
3. 选中态：`--accent` 底 + `--accent-foreground` 字。
4. 链接/品牌元素：`--primary`。
5. 成功/失败/警告：一律用语义色（success/warning/destructive/info），禁止直接用绿色阶替代。
6. 图表第一序列必须用 `--chart-1`。
7. 阴影必须从四个 token 中选取，禁止自定义散落阴影值。
8. 圆角：按钮/输入 `rounded-md`，卡片 `rounded-xl`，弹窗 `rounded-2xl`。
9. 焦点：全局 `:focus-visible` 使用双层环（背景色 + `--ring`），组件不得覆盖。
10. 动画必须尊重 `prefers-reduced-motion`（globals.css 已全局降级）。

## 7. 代码落地（当前实现）

- Token 定义与 Tailwind `@theme inline` 映射：[frontend/src/styles/globals.css](/home/grainuser/hansonDoc_RAG/frontend/src/styles/globals.css)
- 字体加载：[frontend/src/main.tsx](/home/grainuser/hansonDoc_RAG/frontend/src/main.tsx)
- 组件实现：`frontend/src/components/ui/*`
