import {
  BookOpen,
  ChevronRight,
  FileSearch,
  Layers,
  ListChecks
} from "lucide-react";
import type { ComponentType } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";

import { cn } from "./lib/utils";

const NAV = [
  { to: "/", label: "文档库", icon: FileSearch, end: true },
  { to: "/runs", label: "运行记录", icon: ListChecks },
  { to: "/dictionary", label: "业务词典", icon: BookOpen },
  { to: "/recipes", label: "配方版本", icon: Layers }
];

const TITLES: Record<string, { eyebrow: string; title: string }> = {
  "/": { eyebrow: "标准拆分", title: "文档库" },
  "/runs": { eyebrow: "运行", title: "运行记录" },
  "/dictionary": { eyebrow: "数据", title: "业务词典" },
  "/recipes": { eyebrow: "版本", title: "配方版本" }
};

function NavItem({
  to,
  label,
  icon: Icon,
  end
}: {
  to: string;
  label: string;
  icon: ComponentType<{ className?: string; strokeWidth?: number }>;
  end?: boolean;
}) {
  return (
    <NavLink
      to={to}
      end={end}
      className={({ isActive }) =>
        cn(
          "group relative flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-all duration-200",
          isActive
            ? "bg-sidebar-accent text-sidebar-accent-foreground shadow-soft"
            : "text-sidebar-foreground hover:bg-muted hover:pl-4"
        )
      }
    >
      {({ isActive }) => (
        <>
          <span
            className={cn(
              "absolute left-0 top-1/2 h-5 w-1 -translate-y-1/2 rounded-r-full bg-primary transition-opacity",
              isActive ? "opacity-100" : "opacity-0 group-hover:opacity-40"
            )}
          />
          <Icon className="h-4 w-4 shrink-0" strokeWidth={1.9} />
          {label}
        </>
      )}
    </NavLink>
  );
}

function HeaderTitle(pathname: string) {
  if (pathname.startsWith("/documents/") && pathname.endsWith("/viewer")) {
    return { eyebrow: "标准拆分", title: "原文预览" };
  }
  if (pathname.startsWith("/documents/")) {
    return { eyebrow: "标准拆分", title: "解析详情" };
  }
  return TITLES[pathname] ?? { eyebrow: "HansonDOC", title: "标准拆分平台" };
}

export default function App() {
  const location = useLocation();
  const heading = HeaderTitle(location.pathname);

  return (
    <div className="min-h-dvh bg-background-soft">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-sidebar-border bg-gradient-to-b from-sidebar via-white to-sidebar md:flex">
        <div className="flex items-center gap-3 px-5 py-6">
          <div className="relative flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-lift">
            <FileSearch className="h-5 w-5" strokeWidth={1.7} />
            <span className="pulse-dot absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full bg-emerald-300" />
          </div>
          <div>
            <p className="text-[15px] font-semibold leading-tight">HansonDOC</p>
            <p className="text-xs text-muted-foreground">标准拆分平台</p>
          </div>
        </div>
        <nav className="flex-1 space-y-1 overflow-y-auto px-3 py-2">
          <p className="mb-1 mt-2 px-3 text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            工作区
          </p>
          {NAV.map((item) => (
            <NavItem key={item.to} {...item} />
          ))}
        </nav>
        <div className="border-t border-sidebar-border p-4">
          <div className="rounded-xl border border-emerald-100 bg-white/70 p-3 shadow-soft">
            <div className="flex items-center gap-2 text-xs font-medium text-foreground">
              <span className="pulse-dot h-2 w-2 rounded-full bg-emerald-500" />
              服务已连接
              <span className="ml-auto rounded-full bg-emerald-50 px-1.5 py-0.5 text-[10px] text-emerald-700">
                M7
              </span>
            </div>
            <p className="mt-1.5 text-[11px] text-muted-foreground">
              本地工作区 · 无登录 / 多租户
            </p>
          </div>
        </div>
      </aside>

      <div className="md:pl-60">
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-border/80 bg-card/85 px-4 backdrop-blur-md sm:px-6">
          <div className="flex items-center gap-3">
            <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-emerald-500 to-teal-600 text-white md:hidden">
              <FileSearch className="h-4 w-4" />
            </div>
            <div>
              <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-primary-strong">
                {heading.eyebrow}
              </p>
              <h2 className="flex items-center gap-1 text-base font-semibold leading-tight">
                {heading.title}
                <ChevronRight className="h-3.5 w-3.5 text-muted-foreground md:hidden" />
              </h2>
            </div>
          </div>
          <div className="hidden items-center gap-2 text-xs text-muted-foreground sm:flex">
            <span className="rounded-full border border-border bg-card px-2.5 py-1">
              操作员 local
            </span>
          </div>
        </header>

        <div className="overflow-x-auto border-b border-border bg-card/85 md:hidden">
          <div className="flex gap-1 px-3 py-2">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) =>
                  cn(
                    "whitespace-nowrap rounded-lg px-3 py-1.5 text-xs font-medium",
                    isActive
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground"
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </div>
        </div>

        <main className="p-4 sm:p-6 lg:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
