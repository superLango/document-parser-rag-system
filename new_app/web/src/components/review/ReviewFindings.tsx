import { AlertCircle, CheckCircle2, Info } from "lucide-react";

import type { ReviewReport } from "../../api/types";
import { Badge, Card, CardContent, CardHeader, EmptyState } from "../ui/primitives";
import { SEVERITY_META } from "../../lib/status";
import { formatPercent } from "../../lib/utils";

const SEVERITY_ICON = {
  error: AlertCircle,
  warning: AlertCircle,
  info: Info
};

export function ReviewFindings({ report }: { report: ReviewReport }) {
  const stats = report.stats ?? {};
  const counts = {
    error: report.findings.filter((item) => item.severity === "error").length,
    warning: report.findings.filter((item) => item.severity === "warning").length,
    info: report.findings.filter((item) => item.severity === "info").length
  };

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title="审核摘要"
          description={`规则集 ${report.ruleset_version}${report.degraded ? " · 模型降级" : ""}`}
          actions={
            <Badge
              tone={
                report.status === "pass"
                  ? "success"
                  : report.status === "warn"
                    ? "warning"
                    : "danger"
              }
              dot
            >
              {report.status === "pass"
                ? "通过"
                : report.status === "warn"
                  ? "有警告"
                  : "未通过"}
            </Badge>
          }
        />
        <CardContent className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <Stat label="错误" value={counts.error} tone="text-rose-600" />
          <Stat label="警告" value={counts.warning} tone="text-amber-600" />
          <Stat label="提示" value={counts.info} tone="text-sky-600" />
          <Stat
            label="记录数"
            value={Number(stats.records ?? stats.total ?? report.findings.length)}
            tone="text-foreground"
          />
        </CardContent>
      </Card>

      {report.findings.length === 0 ? (
        <Card>
          <CardContent>
            <EmptyState
              title="没有发现问题"
              description="规则链与模型审核均未产生 Finding"
              action={<CheckCircle2 className="mx-auto h-8 w-8 text-emerald-500" />}
            />
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-2">
          {report.findings.map((finding, index) => {
            const meta = SEVERITY_META[finding.severity] ?? SEVERITY_META.info;
            const Icon = SEVERITY_ICON[finding.severity] ?? Info;
            return (
              <Card key={finding.id ?? `${finding.category}-${index}`}>
                <CardContent className="flex gap-3">
                  <span className="mt-0.5">
                    <Icon
                      className={
                        finding.severity === "error"
                          ? "h-5 w-5 text-rose-500"
                          : finding.severity === "warning"
                            ? "h-5 w-5 text-amber-500"
                            : "h-5 w-5 text-sky-500"
                      }
                    />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-sm font-medium">{finding.category}</span>
                      <Badge tone={meta.tone}>{meta.label}</Badge>
                      <Badge tone="neutral">{finding.source}</Badge>
                      <span className="text-[11px] text-muted-foreground">
                        置信度 {formatPercent(finding.confidence)}
                      </span>
                    </div>
                    <div className="mt-1.5 grid gap-1 text-xs sm:grid-cols-2">
                      <p>
                        <span className="text-muted-foreground">观测：</span>
                        {finding.observed || "—"}
                      </p>
                      <p>
                        <span className="text-muted-foreground">期望：</span>
                        {finding.expected || "—"}
                      </p>
                    </div>
                    {finding.evidence_refs.length > 0 ? (
                      <p className="mt-1.5 font-mono text-[11px] text-muted-foreground">
                        证据：{finding.evidence_refs.join(" · ")}
                      </p>
                    ) : null}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}
    </div>
  );
}

function Stat({
  label,
  value,
  tone
}: {
  label: string;
  value: number;
  tone: string;
}) {
  return (
    <div>
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`mt-1 text-xl font-semibold ${tone}`}>{value}</p>
    </div>
  );
}
