import { ArrowRight, GitCompare } from "lucide-react";
import { useMemo } from "react";

import type { RecordItem, RunItem } from "../../api/types";
import { Badge, Card, CardContent, CardHeader, EmptyState, Skeleton } from "../ui/primitives";
import { Select } from "../ui/form";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow
} from "../ui/table";
import { runStatusMeta } from "../../lib/status";
import { formatDateTime } from "../../lib/utils";

type DiffRow = {
  recordId: string;
  grade: string;
  measure: string;
  kind: "added" | "removed" | "changed";
  left: string;
  right: string;
};

export function VersionCompare({
  runs,
  leftId,
  rightId,
  onLeft,
  onRight,
  leftRecords,
  rightRecords,
  loading
}: {
  runs: RunItem[];
  leftId: string;
  rightId: string;
  onLeft: (value: string) => void;
  onRight: (value: string) => void;
  leftRecords?: RecordItem[];
  rightRecords?: RecordItem[];
  loading?: boolean;
}) {
  const diffs = useMemo(
    () => buildDiff(leftRecords ?? [], rightRecords ?? []),
    [leftRecords, rightRecords]
  );
  const leftRun = runs.find((run) => run.id === leftId);
  const rightRun = runs.find((run) => run.id === rightId);

  if (runs.length < 2) {
    return (
      <Card>
        <CardContent>
          <EmptyState
            title="暂无版本可对比"
            description="同一文档至少需要两次运行"
            action={<GitCompare className="mx-auto h-8 w-8 text-muted-foreground" />}
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="选择对比运行" description="左侧为基准，右侧为对比版本" />
        <CardContent className="grid gap-3 sm:grid-cols-2">
          <label className="space-y-1">
            <span className="text-xs text-muted-foreground">基准运行</span>
            <Select value={leftId} onChange={(event) => onLeft(event.target.value)}>
              {runs.map((run) => (
                <option key={run.id} value={run.id}>
                  {runLabel(run)}
                </option>
              ))}
            </Select>
            {leftRun ? <RunMeta run={leftRun} /> : null}
          </label>
          <label className="space-y-1">
            <span className="text-xs text-muted-foreground">对比运行</span>
            <Select value={rightId} onChange={(event) => onRight(event.target.value)}>
              {runs.map((run) => (
                <option key={run.id} value={run.id}>
                  {runLabel(run)}
                </option>
              ))}
            </Select>
            {rightRun ? <RunMeta run={rightRun} /> : null}
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              结果差异
              <ArrowRight className="h-4 w-4 text-muted-foreground" />
              <Badge tone="neutral">{diffs.length} 项</Badge>
            </span>
          }
          description="按 record_id + measure 比较属性值"
        />
        <CardContent>
          {loading ? (
            <Skeleton className="h-24 w-full" />
          ) : diffs.length === 0 ? (
            <p className="text-sm text-muted-foreground">两次运行的记录与属性一致。</p>
          ) : (
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeaderCell>记录</TableHeaderCell>
                  <TableHeaderCell>牌号</TableHeaderCell>
                  <TableHeaderCell>字段</TableHeaderCell>
                  <TableHeaderCell>变化</TableHeaderCell>
                  <TableHeaderCell>基准</TableHeaderCell>
                  <TableHeaderCell>对比</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {diffs.map((row) => (
                  <TableRow key={`${row.recordId}-${row.measure}-${row.kind}`}>
                    <TableCell className="font-mono text-xs">{row.recordId}</TableCell>
                    <TableCell>{row.grade}</TableCell>
                    <TableCell>{row.measure}</TableCell>
                    <TableCell>
                      <Badge
                        tone={
                          row.kind === "added"
                            ? "success"
                            : row.kind === "removed"
                              ? "danger"
                              : "warning"
                        }
                      >
                        {row.kind === "added" ? "新增" : row.kind === "removed" ? "消失" : "变化"}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{row.left || "—"}</TableCell>
                    <TableCell>{row.right || "—"}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function runLabel(run: RunItem): string {
  return `${run.id.slice(0, 8)} · ${runStatusMeta(run.status).label} · ${formatDateTime(run.created_at)}`;
}

function RunMeta({ run }: { run: RunItem }) {
  return (
    <p className="mt-1 text-[11px] text-muted-foreground">
      通道 {run.recipe_channel} · 文档版本 v{run.document_version}
    </p>
  );
}

function buildDiff(left: RecordItem[], right: RecordItem[]): DiffRow[] {
  const leftMap = new Map(left.map((record) => [record.record_id, record]));
  const rightMap = new Map(right.map((record) => [record.record_id, record]));
  const rows: DiffRow[] = [];
  const ids = new Set([...leftMap.keys(), ...rightMap.keys()]);
  for (const id of ids) {
    const a = leftMap.get(id);
    const b = rightMap.get(id);
    const grade = b?.grade ?? a?.grade ?? "";
    if (!a || !b) {
      rows.push({
        recordId: id,
        grade,
        measure: "记录",
        kind: !a ? "added" : "removed",
        left: a ? a.grade : "",
        right: b ? b.grade : ""
      });
      continue;
    }
    const measures = new Set([
      ...Object.keys(a.properties),
      ...Object.keys(b.properties)
    ]);
    for (const measure of measures) {
      const leftValue = a.properties[measure];
      const rightValue = b.properties[measure];
      if (leftValue && !rightValue) {
        rows.push({
          recordId: id,
          grade,
          measure,
          kind: "removed",
          left: cellText(leftValue),
          right: ""
        });
      } else if (!leftValue && rightValue) {
        rows.push({
          recordId: id,
          grade,
          measure,
          kind: "added",
          left: "",
          right: cellText(rightValue)
        });
      } else if (leftValue && rightValue && cellText(leftValue) !== cellText(rightValue)) {
        rows.push({
          recordId: id,
          grade,
          measure,
          kind: "changed",
          left: cellText(leftValue),
          right: cellText(rightValue)
        });
      }
    }
  }
  return rows;
}

function cellText(value: { raw: string; value: number | null; unit: string }): string {
  return `${value.raw || (value.value ?? "")}${value.unit ? ` ${value.unit}` : ""}`.trim();
}
