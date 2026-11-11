import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { feedbackApi } from "../../api/feedback";
import type { FeedbackDetail, PropertyValue } from "../../api/types";
import { Badge, Button, Card, CardContent } from "../ui/primitives";
import { Dialog } from "../ui/dialog";
import { Field, Textarea } from "../ui/form";
import { Table, TableBody, TableCell, TableHead, TableHeaderCell, TableRow } from "../ui/table";
import { useToast } from "../ui/toast";

export function VerificationDialog({
  feedback,
  onClose,
  onDecided
}: {
  feedback: FeedbackDetail | null;
  onClose: () => void;
  onDecided: () => void;
}) {
  const { push } = useToast();
  const [reason, setReason] = useState("");
  const verification = feedback?.verification ?? null;
  const mutation = useMutation({
    mutationFn: (decision: "approve" | "reject") =>
      feedbackApi.verify(feedback!.id, decision, reason),
    onSuccess: (result) => {
      push(
        "success",
        result.status === "promoted" ? "已晋升 stable" : "候选已丢弃",
        `反馈 ${result.id.slice(0, 8)}`
      );
      onDecided();
      onClose();
    },
    onError: (error: Error) => push("error", "操作失败", error.message)
  });

  return (
    <Dialog
      open={feedback !== null}
      title="验证结果"
      description={
        verification
          ? `${verification.passed ? "验证通过" : "验证未通过"} · ${verification.user_summary}`
          : "暂无验证包"
      }
      size="lg"
      onClose={onClose}
      footer={
        <>
          <Button variant="secondary" onClick={onClose}>
            关闭
          </Button>
          <Button
            variant="danger"
            disabled={!feedback?.candidate}
            loading={mutation.isPending && mutation.variables === "reject"}
            onClick={() => mutation.mutate("reject")}
          >
            拒绝并丢弃候选
          </Button>
          <Button
            disabled={!verification?.passed || !feedback?.candidate}
            loading={mutation.isPending && mutation.variables === "approve"}
            onClick={() => mutation.mutate("approve")}
          >
            通过并晋升
          </Button>
        </>
      }
    >
      {verification ? (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <Badge tone={verification.passed ? "success" : "danger"} dot>
              {verification.passed ? "passed" : "failed"}
            </Badge>
            <Badge tone="neutral">
              回归文档 {verification.regression.documents}
            </Badge>
            <Badge tone="neutral">
              新增错误 {verification.regression.new_errors}
            </Badge>
            <Badge tone="neutral">
              F1 Δ {verification.regression.field_f1_delta.toFixed(2)}
            </Badge>
          </div>

          <DiffSection title="新增字段" tone="success" rows={verification.diff.added} />
          <DiffSection title="字段消失" tone="danger" rows={verification.diff.removed} />
          <DiffSection title="字段变化" tone="warning" rows={verification.diff.changed} />

          {verification.affected_targets.length > 0 ? (
            <Card>
              <CardContent className="text-xs">
                <p className="font-medium">影响目标</p>
                <p className="mt-1 text-muted-foreground">
                  {verification.affected_targets
                    .map(
                      (target) =>
                        `${target.recipe_id} / ${target.measure}${
                          target.table_id ? ` / ${target.table_id}` : ""
                        }`
                    )
                    .join("；")}
                </p>
              </CardContent>
            </Card>
          ) : null}

          <Field label="决策说明" hint="写入 promotions 审计">
            <Textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="例如：已验证目标字段修复，无新增错误"
            />
          </Field>
        </div>
      ) : (
        <p className="text-sm text-muted-foreground">该反馈还没有验证包。</p>
      )}
    </Dialog>
  );
}

type DiffRow = {
  record_id: string;
  measure: string;
  before?: PropertyValue;
  after?: PropertyValue;
};

function DiffSection({
  title,
  tone,
  rows
}: {
  title: string;
  tone: "success" | "danger" | "warning";
  rows: DiffRow[];
}) {
  if (rows.length === 0) return null;
  return (
    <Card>
      <CardContent>
        <p className="mb-2 text-sm font-medium">
          {title} <Badge tone={tone}>{rows.length}</Badge>
        </p>
        <Table>
          <TableHead>
            <TableRow>
              <TableHeaderCell>记录</TableHeaderCell>
              <TableHeaderCell>字段</TableHeaderCell>
              <TableHeaderCell>值</TableHeaderCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {rows.map((row, index) => {
              const value = row.after ?? row.before ?? null;
              return (
                <TableRow key={`${row.record_id}-${row.measure}-${index}`}>
                  <TableCell className="font-mono text-xs">{row.record_id}</TableCell>
                  <TableCell>{row.measure}</TableCell>
                  <TableCell className="font-mono text-xs">
                    {value
                      ? `${value.raw || (value.value ?? "")} ${value.unit}`.trim()
                      : "—"}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}
