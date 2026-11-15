import { ChevronLeft, ChevronRight } from "lucide-react";

import { cn } from "../../lib/utils";

function pageItems(page: number, pageCount: number): Array<number | "…"> {
  if (pageCount <= 7) {
    return Array.from({ length: pageCount }, (_, index) => index + 1);
  }
  const items: Array<number | "…"> = [1];
  const start = Math.max(2, page - 1);
  const end = Math.min(pageCount - 1, page + 1);
  if (start > 2) items.push("…");
  for (let value = start; value <= end; value += 1) items.push(value);
  if (end < pageCount - 1) items.push("…");
  items.push(pageCount);
  return items;
}

export function Pagination({
  page,
  pageCount,
  total,
  pageSize,
  onPageChange,
  className
}: {
  page: number;
  pageCount: number;
  total: number;
  pageSize: number;
  onPageChange: (page: number) => void;
  className?: string;
}) {
  const safeCount = Math.max(1, pageCount);
  const safePage = Math.min(Math.max(1, page), safeCount);
  return (
    <div
      className={cn(
        "flex flex-wrap items-center justify-between gap-2 border-t border-border px-5 py-3 text-xs text-muted-foreground",
        className
      )}
    >
      <span>
        共 {total} 条 · 第 {safePage} / {safeCount} 页 · 每页 {pageSize} 条
      </span>
      <div className="flex items-center gap-1">
        <button
          type="button"
          className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border bg-card disabled:opacity-40"
          disabled={safePage <= 1}
          onClick={() => onPageChange(safePage - 1)}
          aria-label="上一页"
        >
          <ChevronLeft className="h-3.5 w-3.5" />
        </button>
        {pageItems(safePage, safeCount).map((item, index) =>
          item === "…" ? (
            <span key={`gap-${index}`} className="px-1">
              …
            </span>
          ) : (
            <button
              key={item}
              type="button"
              className={cn(
                "inline-flex h-7 min-w-7 items-center justify-center rounded-md border px-1.5 text-xs",
                item === safePage
                  ? "border-primary/40 bg-primary/10 font-medium text-primary-strong"
                  : "border-border bg-card hover:border-primary/40"
              )}
              onClick={() => onPageChange(item)}
              aria-current={item === safePage ? "page" : undefined}
            >
              {item}
            </button>
          )
        )}
        <button
          type="button"
          className="inline-flex h-7 w-7 items-center justify-center rounded-md border border-border bg-card disabled:opacity-40"
          disabled={safePage >= safeCount}
          onClick={() => onPageChange(safePage + 1)}
          aria-label="下一页"
        >
          <ChevronRight className="h-3.5 w-3.5" />
        </button>
      </div>
    </div>
  );
}
