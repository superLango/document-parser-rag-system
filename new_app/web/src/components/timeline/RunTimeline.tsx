import {
  CheckCircle2,
  CircleDashed,
  SkipForward,
  XCircle
} from "lucide-react";

import type { RunEvent, RunStage, RunTimeline } from "../../api/types";
import { Badge, Card, CardContent, CardHeader } from "../ui/primitives";
import { STAGE_LABELS, runStatusMeta } from "../../lib/status";
import { formatBytes, formatDateTime, formatDuration } from "../../lib/utils";

const STAGE_ORDER = ["ocr", "routing", "sandbox", "cross_standard", "review"];
const STAGE_STATUS: Record<string, { label: string; tone: "success" | "danger" | "info" | "neutral" }> = {
  completed: { label: "完成", tone: "success" },
  failed: { label: "失败", tone: "danger" },
  started: { label: "进行中", tone: "info" },
  running: { label: "进行中", tone: "info" },
  skipped: { label: "跳过", tone: "neutral" },
  warning: { label: "警告", tone: "danger" },
  waiting: { label: "等待", tone: "info" }
};

export function RunTimelineView({ timeline }: { timeline: RunTimeline }) {
  const run = timeline.run;
  const meta = runStatusMeta(run.status);
  const stages = buildStages(timeline);
  const maxDuration = Math.max(
    1,
    ...stages.map((stage) => stage.duration_ms ?? 0)
  );
  const startedAt = run.started_at ?? run.created_at;
  const stageEnds = stages
    .map((stage) => stage.finished_at)
    .filter((value): value is string => Boolean(value))
    .sort();
  const lastStageAt = stageEnds.length ? stageEnds[stageEnds.length - 1] : undefined;
  const effectiveEnd = run.finished_at ?? lastStageAt ?? new Date().toISOString();
  const totalDuration =
    new Date(effectiveEnd).getTime() - new Date(startedAt).getTime();

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title="运行概览"
          description={`trace ${run.trace_id.slice(0, 12)}`}
          actions={<Badge tone={meta.tone} dot>{meta.label}</Badge>}
        />
        <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <Field label="创建时间" value={formatDateTime(run.created_at)} />
          <Field label="开始时间" value={formatDateTime(run.started_at)} />
          <Field
            label="结束时间"
            value={
              run.finished_at
                ? formatDateTime(run.finished_at)
                : lastStageAt
                  ? `${formatDateTime(lastStageAt)}（待人工确认）`
                  : "进行中"
            }
          />
          <Field label="总耗时" value={formatDuration(totalDuration)} />
          <Field
            label="阶段"
            value={`${stages.filter((item) => item.status === "completed").length}/${STAGE_ORDER.length} 已完成`}
          />
          <Field label="事件" value={`${timeline.events.length} 条`} />
          <Field label="配方通道" value={run.recipe_channel} />
          <Field
            label="解析版本"
            value={run.parser_version || "默认版本"}
          />
          {run.error_code ? (
            <Field label="错误码" value={run.error_code} />
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader title="阶段耗时" description="按流程顺序展示，含复用 OCR" />
        <CardContent className="space-y-3">
          {stages.map((stage) => {
            const status = STAGE_STATUS[stage.status] ?? {
              label: stage.status,
              tone: "neutral" as const
            };
            const duration = stage.duration_ms ?? 0;
            return (
              <div
                key={stage.id}
                className="rounded-lg border border-border bg-background-soft px-4 py-3"
              >
                <div className="flex flex-wrap items-center gap-3">
                  <StageIcon status={stage.status} />
                  <span className="w-24 text-sm font-medium">
                    {STAGE_LABELS[stage.stage] ?? stage.stage}
                  </span>
                  <Badge tone={status.tone}>{status.label}</Badge>
                  {stage.reused ? (
                    <Badge tone="neutral">复用 OCR</Badge>
                  ) : null}
                  <span className="text-xs text-muted-foreground">
                    {formatDateTime(stage.started_at)} →{" "}
                    {formatDateTime(stage.finished_at)}
                  </span>
                  <span className="ml-auto font-mono text-xs text-muted-foreground">
                    {formatDuration(duration)}
                  </span>
                  {stage.error_code ? (
                    <Badge tone="danger">{stage.error_code}</Badge>
                  ) : null}
                </div>
                <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-border/60">
                  <div
                    className={`h-full rounded-full ${
                      stage.status === "failed" ? "bg-rose-400" : "bg-primary"
                    }`}
                    style={{
                      width: `${Math.max(
                        stage.status === "skipped" ? 4 : 10,
                        Math.round((duration / maxDuration) * 100)
                      )}%`
                    }}
                  />
                </div>
                {stage.note ? (
                  <p className="mt-2 text-[11px] text-muted-foreground">{stage.note}</p>
                ) : null}
              </div>
            );
          })}
        </CardContent>
      </Card>

      <Card>
        <CardHeader title="事件流" description={`${timeline.events.length} 条`} />
        <CardContent>
          <ol className="relative space-y-2.5 border-l border-border pl-5">
            {timeline.events.map((event) => (
              <li key={event.id} className="relative">
                <span className="absolute -left-[23px] top-1.5 h-2.5 w-2.5 rounded-full bg-primary ring-4 ring-emerald-50" />
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-mono text-xs font-medium">{event.type}</span>
                  <Badge tone="neutral">
                    {STAGE_LABELS[event.stage] ?? event.stage}
                  </Badge>
                  <span className="text-[11px] text-muted-foreground">
                    {formatDateTime(event.occurred_at)}
                  </span>
                </div>
                {payloadSummary(event) ? (
                  <p
                    className="mt-1 line-clamp-2 break-words text-[11px] text-muted-foreground"
                    title={payloadSummary(event)}
                  >
                    {payloadSummary(event)}
                  </p>
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

type DisplayStage = RunStage & { reused?: boolean; note?: string };

function buildStages(timeline: RunTimeline): DisplayStage[] {
  const byStage = new Map(timeline.stages.map((stage) => [stage.stage, stage]));
  const reused = timeline.events.find((event) => event.type === "run.ocr.reused");
  const rows: DisplayStage[] = [];
  for (const name of STAGE_ORDER) {
    const stage = byStage.get(name);
    if (stage) {
      rows.push(stage);
      continue;
    }
    if (name === "ocr" && reused) {
      rows.push({
        id: `${reused.id}-ocr`,
        run_id: timeline.run.id,
        stage: "ocr",
        status: "completed",
        input_refs: {},
        output_refs: {},
        metrics: {},
        error_code: null,
        started_at: timeline.run.created_at,
        finished_at: timeline.run.created_at,
        duration_ms: 0,
        reused: true,
        note: "本次运行复用已有 OCR 产物，未重新识别。"
      });
    }
  }
  return rows;
}

function payloadSummary(event: RunEvent): string {
  const payload = event.payload ?? {};
  const role = String(payload.role ?? "");
  if (event.type === "artifact.created") {
    const size = Number(payload.bytes ?? 0);
    return `产物 ${role || "unknown"}${size ? ` · ${formatBytes(size)}` : ""}`;
  }
  if (event.type === "run.route.needs_human") {
    return `待人工确认路由 ${payload.count ?? "?"} 张表；Agent=${
      payload.agent_used ? "已使用" : "未使用"
    }`;
  }
  if (event.type === "run.edition.adaptation") {
    return `版本画像 ${payload.standard_id ?? ""} ${payload.edition ?? ""} · ${
      payload.level ?? ""
    }`;
  }
  if (event.type?.startsWith("run.repair")) {
    const parts = Object.entries(payload)
      .filter(([, value]) => value !== null && value !== undefined && value !== "")
      .map(([key, value]) => `${key}=${formatValue(value)}`);
    return parts.join(" · ");
  }
  const parts = Object.entries(payload)
    .filter(
      ([key, value]) =>
        !["storage_key", "sha256", "document_sha256"].includes(key) &&
        value !== null &&
        value !== undefined &&
        value !== ""
    )
    .map(([key, value]) => `${key}=${formatValue(value)}`);
  return parts.join(" · ");
}

function formatValue(value: unknown): string {
  if (typeof value === "object" && value !== null) {
    return JSON.stringify(value);
  }
  return String(value);
}

function StageIcon({ status }: { status: string }) {
  if (status === "completed") return <CheckCircle2 className="h-4 w-4 text-emerald-500" />;
  if (status === "failed") return <XCircle className="h-4 w-4 text-rose-500" />;
  if (status === "skipped") return <SkipForward className="h-4 w-4 text-slate-400" />;
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
