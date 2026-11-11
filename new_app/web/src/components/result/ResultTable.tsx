import { ChevronDown, ChevronRight, MessageSquarePlus } from "lucide-react";
import { useMemo, useState } from "react";

import type { RecordItem } from "../../api/types";
import { Badge } from "../ui/primitives";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow
} from "../ui/table";
import { cn } from "../../lib/utils";

export function ResultTable({
  records,
  onFeedback
}: {
  records: RecordItem[];
  onFeedback?: (record: RecordItem, measure: string) => void;
}) {
  const groups = useMemo(() => {
    const map = new Map<string, RecordItem[]>();
    for (const record of records) {
      const list = map.get(record.table_id) ?? [];
      list.push(record);
      map.set(record.table_id, list);
    }
    return [...map.entries()];
  }, [records]);

  if (records.length === 0) {
    return (
      <p className="px-5 py-8 text-center text-sm text-muted-foreground">
        当前运行没有结构化记录。
      </p>
    );
  }

  return (
    <div className="divide-y divide-border">
      {groups.map(([tableId, items]) => (
        <TableGroup
          key={tableId}
          tableId={tableId}
          records={items}
          onFeedback={onFeedback}
        />
      ))}
    </div>
  );
}

function TableGroup({
  tableId,
  records,
  onFeedback
}: {
  tableId: string;
  records: RecordItem[];
  onFeedback?: (record: RecordItem, measure: string) => void;
}) {
  const [open, setOpen] = useState(true);
  const measures = useMemo(() => {
    const keys = new Set<string>();
    for (const record of records) {
      Object.keys(record.properties).forEach((key) => keys.add(key));
    }
    return [...keys].sort();
  }, [records]);
  const conditions = useMemo(() => {
    const keys = new Set<string>();
    for (const record of records) {
      Object.keys(record.conditions).forEach((key) => keys.add(key));
    }
    return [...keys].sort();
  }, [records]);

  const recipe = records[0];

  return (
    <section>
      <button
        type="button"
        className="flex w-full items-center gap-2 px-5 py-3 text-left transition-colors hover:bg-muted/50"
        onClick={() => setOpen((value) => !value)}
        aria-expanded={open}
      >
        {open ? (
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        )}
        <span className="text-sm font-semibold">表 {tableId}</span>
        <Badge tone="info">{recipe.profile || "unknown"}</Badge>
        <Badge tone="neutral">{records.length} 行</Badge>
        <span className="ml-auto text-xs text-muted-foreground">
          {recipe.recipe_id}@{recipe.recipe_version}
        </span>
      </button>
      {open ? (
        <Table>
          <TableHead>
            <TableRow>
              <TableHeaderCell>牌号</TableHeaderCell>
              {conditions.map((key) => (
                <TableHeaderCell key={key}>{key}</TableHeaderCell>
              ))}
              {measures.map((measure) => (
                <TableHeaderCell key={measure}>{measure}</TableHeaderCell>
              ))}
            </TableRow>
          </TableHead>
          <TableBody>
            {records.map((record) => (
              <TableRow key={record.record_id}>
                <TableCell className="font-medium">{record.grade}</TableCell>
                {conditions.map((key) => (
                  <TableCell key={key} className="text-muted-foreground">
                    {record.conditions[key] || "—"}
                  </TableCell>
                ))}
                {measures.map((measure) => {
                  const property = record.properties[measure];
                  if (!property) {
                    return (
                      <TableCell key={measure} className="text-muted-foreground">
                        —
                      </TableCell>
                    );
                  }
                  return (
                    <TableCell key={measure}>
                      <button
                        type="button"
                        className="group inline-flex items-center gap-1.5 rounded-md px-1 py-0.5 text-left hover:bg-amber-50"
                        title="反馈此字段"
                        onClick={() => onFeedback?.(record, measure)}
                      >
                        <span className="font-mono text-[13px]">
                          {property.raw || property.value}
                          {property.unit ? (
                            <span className="ml-1 text-[11px] text-muted-foreground">
                              {property.unit}
                            </span>
                          ) : null}
                        </span>
                        <MessageSquarePlus
                          className={cn(
                            "h-3.5 w-3.5 text-amber-500",
                            onFeedback ? "opacity-0 group-hover:opacity-100" : "hidden"
                          )}
                        />
                      </button>
                    </TableCell>
                  );
                })}
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : null}
    </section>
  );
}
