import { CheckCircle2, CircleDashed, XCircle } from "lucide-react";

import type { RunTimeline } from "../../api/types";
import { Badge, Card, CardContent, CardHeader } from "../ui/primitives";
import { STAGE_LABELS, runStatusMeta } from "../../lib/status";
import { formatDateTime, formatDuration } from "../../lib/utils";

export function RunTimelineView({ timeline }: { timeline: RunTimeline }) {
  const run = timeline.run;
  const meta = runStatusMeta(run.status);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title="运行概览"
          description={`trace ${run.trace_id}`}
          actions={<Badge tone={meta.tone} dot>{meta.label}</Badge>}
        />
        <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="创建时间" value={formatDateTime(run.created_at)} />
          <Field label="开始时间" value={formatDateTime(run.started_at)} />
          <Field label="结束时间" value={formatDateTime(run.finished_at)} />
          <Field
            label="总耗时"
            value={formatDuration(
              run.started_at && run.finished_at
                ? new Date(run.finished_at).getTime() -
                    new Date(run.started_at).getTime()
                : null
            )}
          />
          <Field label="配方通道" value={run.recipe_channel} />
          <Field label="引擎版本" value={run.engine_version} />
          <Field label="错误码" value={run.error_code || "—"} />
          <Field label="运行 ID" value={run.id.slice(0, 8)} mono />
        </CardContent>
      </Card>

      <Card>
        <CardHeader title="阶段耗时" />
        <CardContent className="space-y-3">
          {timeline.stages.map((stage) => (
            <div
              key={stage.id}
              className="flex flex-wrap items-center gap-3 rounded-lg border border-border bg-background-soft px-4 py-3"
            >
              <StageIcon status={stage.status} />
              <span className="w-24 text-sm font-medium">
                {STAGE_LABELS[stage.stage] ?? stage.stage}
              </span>
              <Badge
                tone={
                  stage.status === "completed"
                    ? "success"
                    : stage.status === "failed"
                      ? "danger"
                      : "info"
                }
              >
                {stage.status}
              </Badge>
              <span className="text-xs text-muted-foreground">
                {formatDateTime(stage.started_at)} → {formatDateTime(stage.finished_at)}
              </span>
              <span className="ml-auto font-mono text-xs text-muted-foreground">
                {formatDuration(stage.duration_ms)}
              </span>
              {stage.error_code ? (
                <Badge tone="danger">{stage.error_code}</Badge>
              ) : null}
            </div>
          ))}
          {timeline.stages.length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无阶段记录。</p>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader title="事件流" description={`${timeline.events.length} 条`} />
        <CardContent>
          <ol className="relative space-y-3 border-l border-border pl-5">
            {timeline.events.map((event) => (
              <li key={event.id} className="relative">
                <span className="absolute -left-[23px] top-1.5 h-2.5 w-2.5 rounded-full bg-primary ring-4 ring-emerald-50" />
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs font-medium">{event.type}</span>
                  <Badge tone="neutral">{event.stage}</Badge>
                  <span className="text-[11px] text-muted-foreground">
                    {formatDateTime(event.occurred_at)}
                  </span>
                </div>
                {Object.keys(event.payload).length > 0 ? (
                  <pre className="mt-1 overflow-x-auto rounded-md bg-muted/70 px-2.5 py-1.5 font-mono text-[11px] text-slate-600">
                    {JSON.stringify(event.payload)}
                  </pre>
                ) : null}
              </li>
            ))}
          </ol>
          {timeline.events.length === 0 ? (
            <p className="text-sm text-muted-foreground">暂无事件。</p>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}

function StageIcon({ status }: { status: string }) {
  if (status === "completed") return <CheckCircle2 className="h-4 w-4 text-emerald-500" />;
  if (status === "failed") return <XCircle className="h-4 w-4 text-rose-500" />;
  return <CircleDashed className="h-4 w-4 text-sky-500" />;
}

function Field({
  label,
  value,
  mono = false
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`mt-0.5 text-sm ${mono ? "font-mono" : ""}`}>{value}</p>
    </div>
  );
}
