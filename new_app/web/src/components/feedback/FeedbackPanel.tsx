import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, MessageSquarePlus, PlayCircle, ShieldCheck } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { feedbackApi } from "../../api/feedback";
import type { FeedbackDetail } from "../../api/types";
import { Badge, Button, Card, CardContent, EmptyState, Skeleton } from "../ui/primitives";
import { Select } from "../ui/form";
import { FEEDBACK_STATUS, ROOT_CAUSE_LABELS } from "../../lib/status";
import { formatDateTime } from "../../lib/utils";
import { FeedbackDialog } from "./FeedbackDialog";
import { VerificationDialog } from "./VerificationDialog";

export function FeedbackPanel({
  documentId,
  runId,
  recipeId,
  seed,
  onSeedConsumed
}: {
  documentId: string;
  runId: string;
  recipeId: string;
  seed?: { measure: string; description: string } | null;
  onSeedConsumed?: () => void;
}) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("");
  const [createOpen, setCreateOpen] = useState(false);
  const [verifyTarget, setVerifyTarget] = useState<FeedbackDetail | null>(null);

  useEffect(() => {
    if (seed) setCreateOpen(true);
  }, [seed]);

  const query = useQuery({
    queryKey: ["feedback", documentId, status],
    queryFn: () => feedbackApi.list({ document_id: documentId, status }),
    enabled: Boolean(documentId)
  });

  const processMutation = useMutation({
    mutationFn: (id: string) => feedbackApi.process(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["feedback", documentId] });
    }
  });

  const items = useMemo(() => query.data ?? [], [query.data]);

  function refresh() {
    void queryClient.invalidateQueries({ queryKey: ["feedback", documentId] });
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Select
          value={status}
          onChange={(event) => setStatus(event.target.value)}
          className="w-40"
        >
          <option value="">全部状态</option>
          {Object.entries(FEEDBACK_STATUS).map(([value, meta]) => (
            <option key={value} value={value}>
              {meta.label}
            </option>
          ))}
        </Select>
        <Button
          className="ml-auto"
          icon={<MessageSquarePlus className="h-4 w-4" />}
          onClick={() => setCreateOpen(true)}
          disabled={!runId}
        >
          新建反馈
        </Button>
      </div>

      {query.isLoading ? (
        <Skeleton className="h-32 w-full" />
      ) : items.length === 0 ? (
        <Card>
          <CardContent>
            <EmptyState
              title="暂无反馈"
              description="在结果表点击字段旁的反馈按钮，或直接新建反馈"
              action={
                <Button onClick={() => setCreateOpen(true)} disabled={!runId}>
                  新建反馈
                </Button>
              }
            />
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {items.map((item) => {
            const meta = FEEDBACK_STATUS[item.status] ?? {
              label: item.status,
              tone: "neutral" as const
            };
            const canProcess = item.status === "open" || item.status === "needs_more_info";
            return (
              <Card key={item.id}>
                <CardContent className="space-y-3">
                  <div className="flex flex-wrap items-start gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="text-sm font-medium">{item.description}</span>
                        <Badge tone={meta.tone} dot>
                          {meta.label}
                        </Badge>
                        <Badge tone="neutral">{item.category}</Badge>
                        {item.target.measure ? (
                          <Badge tone="info">字段 {item.target.measure}</Badge>
                        ) : null}
                      </div>
                      <p className="mt-1 text-[11px] text-muted-foreground">
                        {formatDateTime(item.created_at)}
                        {item.target.recipe_id ? ` · ${item.target.recipe_id}` : ""}
                        {item.expected_value ? ` · 期望 ${item.expected_value}` : ""}
                      </p>
                    </div>
                    <div className="flex items-center gap-1.5">
                      {canProcess ? (
                        <Button
                          size="sm"
                          variant="secondary"
                          icon={<PlayCircle className="h-3.5 w-3.5" />}
                          loading={
                            processMutation.isPending && processMutation.variables === item.id
                          }
                          onClick={() => processMutation.mutate(item.id)}
                        >
                          处理
                        </Button>
                      ) : null}
                      {item.verification ? (
                        <Button
                          size="sm"
                          variant="secondary"
                          icon={<ShieldCheck className="h-3.5 w-3.5" />}
                          onClick={() => setVerifyTarget(item)}
                        >
                          验证结果
                        </Button>
                      ) : null}
                    </div>
                  </div>

                  {item.triage ? (
                    <div className="rounded-lg border border-border bg-background-soft px-3 py-2 text-xs">
                      <p>
                        <span className="text-muted-foreground">根因：</span>
                        {ROOT_CAUSE_LABELS[item.triage.root_cause] ?? item.triage.root_cause}
                        <span className="ml-3 text-muted-foreground">范围：</span>
                        {item.triage.repair_scope}
                        <span className="ml-3 text-muted-foreground">置信度：</span>
                        {(item.triage.confidence * 100).toFixed(0)}%
                      </p>
                      <p className="mt-1 text-muted-foreground">{item.triage.summary}</p>
                    </div>
                  ) : null}

                  {item.proposal ? (
                    <div className="rounded-lg border border-border px-3 py-2 text-xs">
                      <p className="font-medium">修复提案</p>
                      <p className="mt-0.5 text-muted-foreground">{item.proposal.summary}</p>
                      {item.proposal.patch.ops?.length ? (
                        <pre className="mt-1 overflow-x-auto rounded bg-muted px-2 py-1.5 font-mono text-[11px]">
                          {JSON.stringify(item.proposal.patch.ops, null, 2)}
                        </pre>
                      ) : null}
                      {item.candidate ? (
                        <p className="mt-1 text-muted-foreground">
                          候选：{item.candidate.recipe_id}@{item.candidate.candidate_version}
                          （基线 {item.candidate.base_version}）
                        </p>
                      ) : null}
                    </div>
                  ) : null}

                  {item.verification ? (
                    <div
                      className={`rounded-lg border px-3 py-2 text-xs ${
                        item.verification.passed
                          ? "border-emerald-200 bg-emerald-50/60"
                          : "border-amber-200 bg-amber-50/60"
                      }`}
                    >
                      <div className="flex flex-wrap items-center gap-2">
                        <Badge tone={item.verification.passed ? "success" : "warning"} dot>
                          {item.verification.passed ? "验证通过" : "验证未通过"}
                        </Badge>
                        <span className="text-muted-foreground">
                          {item.verification.user_summary}
                        </span>
                      </div>
                    </div>
                  ) : null}

                  {item.messages.length > 0 ? (
                    <details className="group">
                      <summary className="flex cursor-pointer items-center gap-1 text-xs text-muted-foreground">
                        <ChevronDown className="h-3.5 w-3.5 transition-transform group-open:rotate-180" />
                        处理记录（{item.messages.length}）
                      </summary>
                      <ol className="mt-2 space-y-1.5 border-l border-border pl-3">
                        {item.messages.map((message, index) => (
                          <li key={`${item.id}-message-${index}`} className="text-xs">
                            <span className="text-[11px] text-muted-foreground">
                              {message.role} · {formatDateTime(message.at)}
                            </span>
                            <p className="mt-0.5">{message.content}</p>
                          </li>
                        ))}
                      </ol>
                    </details>
                  ) : null}
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      <FeedbackDialog
        open={createOpen}
        runId={runId}
        recipeId={recipeId}
        initialMeasure={seed?.measure ?? ""}
        initialDescription={seed?.description ?? ""}
        onClose={() => {
          setCreateOpen(false);
          onSeedConsumed?.();
        }}
        onCreated={refresh}
      />
      <VerificationDialog
        feedback={verifyTarget}
        onClose={() => setVerifyTarget(null)}
        onDecided={refresh}
      />
    </div>
  );
}
