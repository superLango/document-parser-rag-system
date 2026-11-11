import { ChevronLeft, ChevronRight, ImageOff } from "lucide-react";
import { useState } from "react";

import { runsApi } from "../../api/runs";
import type { OcrPayload } from "../../api/types";
import { Badge, Button, Card, CardContent, CardHeader, EmptyState } from "../ui/primitives";
import { Table, TableBody, TableCell, TableHead, TableHeaderCell, TableRow } from "../ui/table";
import { cn } from "../../lib/utils";

export function PagePreview({
  runId,
  ocr,
  pageNo,
  onPageChange,
  tall = false
}: {
  runId: string;
  ocr: OcrPayload;
  pageNo: number;
  onPageChange: (value: number) => void;
  tall?: boolean;
}) {
  const [imageFailed, setImageFailed] = useState(false);
  const pages = ocr.pages ?? [];
  const page = pages.find((item) => item.page_no === pageNo) ?? pages[0];
  const tables = (ocr.tables ?? []).filter((table) => table.page_no === page?.page_no);
  const index = pages.findIndex((item) => item.page_no === page?.page_no);

  if (!page) {
    return (
      <Card>
        <CardContent>
          <EmptyState title="没有页面信息" description="OCR 尚未产出页面" />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader
        title={`第 ${page.page_no} 页`}
        description={`${page.width.toFixed(0)} × ${page.height.toFixed(0)} · ${page.dpi || "—"} dpi`}
        actions={
          <div className="flex items-center gap-1">
            <Button
              size="sm"
              variant="secondary"
              disabled={index <= 0}
              onClick={() => onPageChange(pages[index - 1].page_no)}
              icon={<ChevronLeft className="h-3.5 w-3.5" />}
            >
              上一页
            </Button>
            <Button
              size="sm"
              variant="secondary"
              disabled={index < 0 || index >= pages.length - 1}
              onClick={() => onPageChange(pages[index + 1].page_no)}
            >
              下一页
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        }
      />
      <CardContent className="space-y-4">
        {page.image_key && !imageFailed ? (
          <div className="flex justify-center rounded-lg border border-border bg-muted/40 p-2">
            <img
              src={runsApi.pageImage(runId, page.page_no)}
              alt={`第 ${page.page_no} 页预览`}
              className={cn(
                "max-w-full rounded-md bg-white shadow-soft",
                tall ? "max-h-[72vh]" : "max-h-[52vh]"
              )}
              onError={() => setImageFailed(true)}
            />
          </div>
        ) : (
          <div className="rounded-lg border border-border">
            <div className="flex items-center gap-2 border-b border-border bg-background-soft px-3 py-2 text-xs text-muted-foreground">
              <ImageOff className="h-3.5 w-3.5" />
              当前页面没有页图，展示 OCR 文本
            </div>
            <pre className="max-h-[46vh] overflow-auto whitespace-pre-wrap px-4 py-3 font-mono text-xs leading-relaxed text-slate-700">
              {page.markdown || "（空页面）"}
            </pre>
          </div>
        )}

        {tables.length > 0 ? (
          <div className="space-y-3">
            {tables.map((table) => (
              <div key={table.table_id} className="rounded-lg border border-border">
                <div className="flex flex-wrap items-center gap-2 border-b border-border bg-background-soft px-3 py-2">
                  <span className="text-xs font-medium">表 {table.table_id}</span>
                  <Badge tone="info">{table.profile || "unknown"}</Badge>
                  <span className="text-[11px] text-muted-foreground">
                    {table.n_rows ?? 0} 行 × {table.n_cols ?? 0} 列
                  </span>
                </div>
                <Table>
                  <TableHead>
                    <TableRow>
                      {(table.header_paths ?? []).map((path, columnIndex) => (
                        <TableHeaderCell key={`${table.table_id}-h-${columnIndex}`}>
                          {path.join(" / ")}
                        </TableHeaderCell>
                      ))}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {(table.rows ?? [])
                      .slice(1, 6)
                      .map((row, rowIndex) => (
                        <TableRow key={`${table.table_id}-r-${rowIndex}`}>
                          {row.map((cell, cellIndex) => (
                            <TableCell key={`${table.table_id}-c-${rowIndex}-${cellIndex}`}>
                              {cell || "—"}
                            </TableCell>
                          ))}
                        </TableRow>
                      ))}
                  </TableBody>
                </Table>
              </div>
            ))}
          </div>
        ) : null}

        {ocr.warnings.length > 0 ? (
          <div className="rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2 text-xs text-amber-800">
            {ocr.warnings.join("；")}
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
