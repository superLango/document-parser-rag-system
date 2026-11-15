import { useMutation, useQuery } from "@tanstack/react-query";
import {
  ArrowUpRight,
  BookOpen,
  CheckCircle2,
  FileUp,
  Loader2,
  TriangleAlert
} from "lucide-react";
import { useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { documentsApi } from "../../api/documents";
import { runsApi } from "../../api/runs";
import type { CrossStandardTask, RunItem } from "../../api/types";
import { Badge, Button, Card, CardContent, EmptyState, Skeleton } from "../ui/primitives";
import { Dialog } from "../ui/dialog";
import { useToast } from "../ui/toast";
import { RUN_TERMINAL } from "../../lib/status";
import { cn, formatBytes } from "../../lib/utils";

const STATUS_META: Record<
  string,
  { label: string; tone: "success" | "warning" | "danger" | "info" | "neutral" }
> = {
  expanded: { label: "已补全", tone: "success" },
  resolved: { label: "已找到来源", tone: "info" },
  needs_source: { label: "缺少来源正文", tone: "warning" },
  needs_agent: { label: "等待 Agent", tone: "info" },
  conflict: { label: "存在冲突", tone: "danger" },
  skipped: { label: "未补全", tone: "neutral" },
  rejected: { label: "已拒绝", tone: "neutral" }
};

const STAT_LABELS: Array<{ key: string; label: string }> = [
  { key: "tasks", label: "任务" },
  { key: "expanded", label: "已补全" },
  { key: "needs_source", label: "缺来源" },
  { key: "properties_added", label: "新增字段" }
];

export function CrossStandardPanel({
  documentId,
  runId
}: {
  documentId: string;
  runId: string;
}) {
  const { push } = useToast();
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [target, setTarget] = useState<CrossStandardTask | null>(null);
  const [file, setFile] = useState<File | null>(null);

  const query = useQuery({
    queryKey: ["cross-standard", runId],
    queryFn: () => runsApi.crossStandard(runId),
    enabled: Boolean(runId),
    refetchInterval: 5000
  });

  const uploadMutation = useMutation({
    mutationFn: async (payload: { task: CrossStandardTask; file: File }) => {
      const source = await documentsApi.upload(payload.file);
      push("info", "来源标准已上传", `正在建立 ${source.filename} 的正文索引`);
      const sourceRun = await documentsApi.createRun(source.id);
      for (let attempt = 0; attempt < 90; attempt += 1) {
        await new Promise((resolve) => setTimeout(resolve, 2000));
        const current: RunItem = await runsApi.get(sourceRun.id);
        if (RUN_TERMINAL.has(current.status)) break;
      }
      return documentsApi.createRun(documentId);
    },
    onSuccess: (run) => {
      setTarget(null);
      setFile(null);
      push("success", "来源已入库", "正在重新解析当前文档并自动补全");
      navigate(`/documents/${documentId}?run=${run.id}`);
    },
    onError: (error: Error) => push("error", "来源处理失败", error.message)
  });

  const tasks = query.data?.tasks ?? [];
  const stats = query.data?.stats ?? {};

  return (
    <div className="space-y-4">
      <div className="grid gap-3 sm:grid-cols-4">
        {STAT_LABELS.map((item) => (
          <Card key={item.key}>
            <CardContent className="py-3">
              <p className="text-[11px] text-muted-foreground">{item.label}</p>
              <p className="mt-1 text-xl font-semibold">{stats[item.key] ?? 0}</p>
            </CardContent>
          </Card>
        ))}
      </div>

      {query.isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : tasks.length === 0 ? (
        <Card>
          <CardContent>
            <EmptyState
              title="没有跨标准补全任务"
              description="当前文档没有把要求交给其他标准，或尚未完成解析"
            />
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-3">
          {tasks.map((task) => {
            const meta = STATUS_META[task.status] ?? {
              label: task.status,
              tone: "neutral" as const
            };
            const resolution = task.resolution;
            return (
              <Card key={task.task_id}>
                <CardContent className="space-y-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold">
                      {task.feature || "未分类"}
                      {task.parameter ? ` / ${task.parameter}` : ""}
                    </span>
                    <Badge tone={meta.tone} dot>
                      {meta.label}
                    </Badge>
                    <Badge tone="neutral">
                      {task.scope === "parameter" ? "参数" : "类别"}
                    </Badge>
                    <Badge tone="info">
                      {task.standard_no}
                      {task.edition ? `-${task.edition}` : ""}
                    </Badge>
                    {task.expansion?.agent ? (
                      <Badge tone="success">Agent 补全</Badge>
                    ) : null}
                    {resolution?.edition && task.edition && resolution.edition !== task.edition ? (
                      <Badge tone="warning">已用最新版 {resolution.edition}</Badge>
                    ) : null}
                  </div>

                  <div className="rounded-lg border border-border bg-background-soft px-3 py-2 text-xs text-muted-foreground">
                    <span className="text-[11px]">原文：</span>
                    {task.quote}
                    {task.clause_id ? (
                      <span className="ml-2 text-[11px]">
                        第 {task.page_no || "?"} 页 · {task.clause_id}
                      </span>
                    ) : null}
                  </div>

                  {task.gap ? (
                    <p className="flex items-center gap-1.5 text-xs text-amber-700">
                      <TriangleAlert className="h-3.5 w-3.5" />
                      {task.gap}
                    </p>
                  ) : null}

                  {task.expansion?.conflicts?.length ? (
                    <details className="rounded-lg border border-amber-200 bg-amber-50/60 px-3 py-2 text-xs text-amber-800">
                      <summary className="cursor-pointer select-none">
                        已有 {task.expansion.conflicts.length} 项值与来源不同，未覆盖（点击查看）
                      </summary>
                      <div className="mt-1 space-y-0.5">
                        {task.expansion.conflicts.slice(0, 20).map((conflict) => (
                          <p key={`${conflict.record_id}-${conflict.measure}`}>
                            {conflict.measure}：当前 {conflict.current || "空"}，来源{" "}
                            {conflict.imported || "空"}
                          </p>
                        ))}
                        {task.expansion.conflicts.length > 20 ? (
                          <p className="text-[11px]">
                            还有 {task.expansion.conflicts.length - 20} 项
                          </p>
                        ) : null}
                      </div>
                    </details>
                  ) : null}

                  <div className="flex flex-wrap items-center gap-2 text-xs">
                    {resolution?.document_id ? (
                      <Link
                        to={`/documents/${resolution.document_id}`}
                        className="inline-flex items-center gap-1 text-primary-strong hover:underline"
                      >
                        <BookOpen className="h-3.5 w-3.5" />
                        {resolution.title || "查看来源标准"}
                        <ArrowUpRight className="h-3 w-3" />
                      </Link>
                    ) : null}
                    {resolution?.status ? (
                      <span className="text-muted-foreground">
                        来源状态：{resolution.status}
                        {resolution.page_count ? ` · ${resolution.page_count} 页` : ""}
                      </span>
                    ) : null}
                    {task.expansion?.properties_added || task.expansion?.records_added ? (
                      <span className="inline-flex items-center gap-1 text-emerald-700">
                        <CheckCircle2 className="h-3.5 w-3.5" />
                        {task.expansion?.properties_added
                          ? `新增 ${task.expansion.properties_added} 项字段`
                          : `新增 ${task.expansion?.records_added} 条记录`}
                      </span>
                    ) : null}
                    {task.status === "needs_source" ? (
                      <Button
                        size="sm"
                        icon={<FileUp className="h-3.5 w-3.5" />}
                        onClick={() => {
                          setTarget(task);
                          setFile(null);
                        }}
                      >
                        上传被引标准
                      </Button>
                    ) : null}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      <Dialog
        open={target !== null}
        title="上传被引标准"
        description={`上传 ${target?.standard_no || ""} 的正文后，系统会自动解析并重新补全当前文档`}
        onClose={() => {
          if (!uploadMutation.isPending) setTarget(null);
        }}
        footer={
          <>
            <Button
              variant="secondary"
              disabled={uploadMutation.isPending}
              onClick={() => setTarget(null)}
            >
              取消
            </Button>
            <Button
              disabled={!file || uploadMutation.isPending}
              loading={uploadMutation.isPending}
              onClick={() => {
                if (file && target) uploadMutation.mutate({ task: target, file });
              }}
            >
              上传并补全
            </Button>
          </>
        }
      >
        <input
          ref={inputRef}
          type="file"
          accept=".pdf,.md,.markdown,.txt"
          className="hidden"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        <div
          className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border border-dashed border-border bg-background-soft px-6 py-8 text-center transition-colors hover:border-primary/50"
          onClick={() => inputRef.current?.click()}
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            setFile(event.dataTransfer.files?.[0] ?? null);
          }}
        >
          {uploadMutation.isPending ? (
            <Loader2 className="h-7 w-7 animate-spin text-primary" />
          ) : (
            <FileUp className="h-7 w-7 text-primary" />
          )}
          <p className="text-sm font-medium">
            {file ? file.name : `选择 ${target?.standard_no || "被引标准"} 的正文文件`}
          </p>
          <p className={cn("text-xs text-muted-foreground")}>
            {file ? formatBytes(file.size) : "PDF / Markdown / TXT，最大 100MB"}
          </p>
          {uploadMutation.isPending ? (
            <p className="text-[11px] text-muted-foreground">
              正在解析来源标准并重新解析当前文档，请勿关闭页面…
            </p>
          ) : null}
        </div>
      </Dialog>
    </div>
  );
}
