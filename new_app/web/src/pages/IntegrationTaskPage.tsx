import { useQuery } from "@tanstack/react-query";
import { FileSearch, ShieldCheck } from "lucide-react";
import { useParams } from "react-router-dom";

import { integrationApi, type IntegrationTaskView } from "../api/integration";
import { Badge, Card, CardContent, Skeleton } from "../components/ui/primitives";
import ExtractionPage from "./ExtractionPage";

function statusLabel(task: IntegrationTaskView): { text: string; tone: "neutral" | "info" | "success" | "warning" | "danger" } {
  if (task.ocr_status === "failed") return { text: "OCR 失败", tone: "danger" };
  if (task.extract_status === "failed") return { text: "解析失败", tone: "danger" };
  if (task.extract_status === "completed") return { text: "解析完成", tone: "success" };
  if (task.extract_status === "running") return { text: "结构化解析中", tone: "info" };
  if (task.ocr_status === "processing") return { text: "OCR 解析中", tone: "info" };
  return { text: "排队中", tone: "warning" };
}

export default function IntegrationTaskPage() {
  const { taskId = "" } = useParams();
  const statusQuery = useQuery({
    queryKey: ["integration-task", taskId],
    queryFn: () => integrationApi.status(taskId),
    enabled: Boolean(taskId),
    retry: 1,
    refetchInterval: (query) => {
      const data = query.state.data as IntegrationTaskView | undefined;
      if (!data) return 2500;
      return data.ocr_status === "completed" && data.extract_status === "completed"
        ? false
        : 2500;
    }
  });

  const task = statusQuery.data;
  const meta = task ? statusLabel(task) : null;

  return (
    // LIMS 用 scrolling="no" 的 iframe 嵌入本页，视口滚动被禁用，必须在自有容器内滚动。
    <div className="h-dvh overflow-y-auto bg-background-soft">
      <header className="sticky top-0 z-20 flex h-16 items-center justify-between gap-4 border-b border-border/80 bg-card/90 px-4 backdrop-blur-md sm:px-6">
        <div className="flex min-w-0 items-center gap-3">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br from-emerald-500 to-teal-600 text-white shadow-soft">
            <FileSearch className="h-4.5 w-4.5" strokeWidth={1.8} />
          </div>
          <div className="min-w-0">
            <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-primary-strong">
              HansonDOC
            </p>
            <h1 className="truncate text-base font-semibold leading-tight">一站式标准解析</h1>
          </div>
        </div>
        <div className="flex min-w-0 items-center gap-2">
          {task ? (
            <span className="hidden max-w-[360px] truncate text-xs text-muted-foreground md:inline">
              {task.filename}
            </span>
          ) : null}
          {meta ? <Badge tone={meta.tone}>{meta.text}</Badge> : null}
          <span className="hidden items-center gap-1 rounded-full border border-border bg-card px-2.5 py-1 text-[11px] text-muted-foreground sm:flex">
            <ShieldCheck className="h-3.5 w-3.5" />
            任务只读视图
          </span>
        </div>
      </header>

      <main className="mx-auto max-w-[1680px] p-4 sm:p-6 lg:p-8">
        {statusQuery.isError ? (
          <Card>
            <CardContent className="space-y-2 py-16 text-center">
              <p className="text-sm font-medium text-foreground">无法加载解析任务</p>
              <p className="text-xs text-muted-foreground">
                {(statusQuery.error as Error)?.message || "任务不存在或服务暂不可用"}
              </p>
            </CardContent>
          </Card>
        ) : task ? (
          <ExtractionPage documentIdOverride={task.document_id} />
        ) : (
          <div className="space-y-4">
            <Skeleton className="h-24 w-full" />
            <Skeleton className="h-96 w-full" />
          </div>
        )}
      </main>
    </div>
  );
}
