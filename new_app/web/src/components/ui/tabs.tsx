import type { ReactNode } from "react";

import { cn } from "../../lib/utils";

export type TabItem = {
  id: string;
  label: string;
  badge?: ReactNode;
};

export function Tabs({
  items,
  active,
  onChange,
  className
}: {
  items: TabItem[];
  active: string;
  onChange: (id: string) => void;
  className?: string;
}) {
  return (
    <div
      role="tablist"
      aria-label="详情分区"
      className={cn(
        "flex flex-wrap items-center gap-1 border-b border-border",
        className
      )}
    >
      {items.map((item) => {
        const selected = item.id === active;
        return (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(item.id)}
            className={cn(
              "relative -mb-px flex items-center gap-2 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors",
              selected
                ? "border-primary text-primary-strong"
                : "border-transparent text-muted-foreground hover:text-foreground"
            )}
          >
            {item.label}
            {item.badge}
          </button>
        );
      })}
    </div>
  );
}
