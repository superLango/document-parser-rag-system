import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Ban,
  Download,
  FileText,
  MessageSquarePlus,
  RefreshCcw,
  RotateCcw,
  ShieldCheck
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useParams, useSearchParams } from "react-router-dom";

import { documentsApi } from "../api/documents";
import { runsApi } from "../api/runs";
import type { RecordItem, SandboxResult } from "../api/types";
import { CrossStandardPanel } from "../components/cross-standard/CrossStandardPanel";
import { FeedbackPanel } from "../components/feedback/FeedbackPanel";
import { FeedbackDialog } from "../components/feedback/FeedbackDialog";
import { ResultJson } from "../components/result/ResultJson";
import { ResultTable } from "../components/result/ResultTable";
import { RunTimelineView } from "../components/timeline/RunTimeline";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  PageHeader,
  Skeleton
} from "../components/ui/primitives";
import { Select } from "../components/ui/form";
import { Tabs } from "../components/ui/tabs";
import { useToast } from "../components/ui/toast";
import { RUN_TERMINAL, runStatusMeta } from "../lib/status";
import { formatBytes, formatDateTime } from "../lib/utils";
import {
  buildResultCsv,
  downloadBlob,
  resultCsvFilename
} from "../lib/resultExport";

const TABS = [
  { id: "result", label: "结果" },
  { id: "cross", label: "跨标准" },
  { id: "feedback", label: "反馈" },
  { id: "timeline", label: "时间线" }
];

type ExtractionPageProps = {
  /** 一站式解析页从对接任务解析出 document_id 后复用同一套解析详情。 */
  documentIdOverride?: string;
};

export default function ExtractionPage({ documentIdOverride }: ExtractionPageProps = {}) {
  const { documentId: routeDocumentId = "" } = useParams();
  const documentId = documentIdOverride || routeDocumentId;
  const [searchParams, setSearchParams] = useSearchParams();
  const { push } = useToast();
  const queryClient = useQueryClient();

  const [tab, setTab] = useState("result");
  const [view, setView] = useState<"table" | "json">("table");
  const [selectedRunId, setSelectedRunId] = useState(searchParams.get("run") ?? "");
  const [feedbackSeed, setFeedbackSeed] = useState<{
    measure: string;
    description: string;
  } | null>(null);
  const [manualFeedbackOpen, setManualFeedbackOpen] = useState(false);
  const [exporting, setExporting] = useState(false);

  const documentQuery = useQuery({
    queryKey: ["document", documentId],
    queryFn: () => documentsApi.get(documentId),
    enabled: Boolean(documentId)
  });

  const runsQuery = useQuery({
    queryKey: ["runs", documentId],
    queryFn: async () => {
      const all = await runsApi.list();
      return all.filter((run) => run.document_id === documentId);
    },
    enabled: Boolean(documentId),
    refetchInterval: (query) => {
      const data = query.state.data as { status: string }[] | undefined;
      return data?.some((run) => !RUN_TERMINAL.has(run.status)) ? 1500 : false;
    }
  });

  const runs = useMemo(() => runsQuery.data ?? [], [runsQuery.data]);
  const runVersions = useMemo(() => {
    const ascending = [...runs].sort(
      (left, right) =>
        new Date(left.created_at).getTime() - new Date(right.created_at).getTime()
    );
    return new Map(ascending.map((run, index) => [run.id, index + 1]));
  }, [runs]);

  useEffect(() => {
    if (runs.length === 0) return;
    if (!selectedRunId || !runs.some((run) => run.id === selectedRunId)) {
      setSelectedRunId(runs[0].id);
    }
  }, [runs, selectedRunId]);

  const selectedRun = runs.find((run) => run.id === selectedRunId) ?? null;
  const runId = selectedRun?.id ?? "";
  const terminal = selectedRun ? RUN_TERMINAL.has(selectedRun.status) : false;
  const ocrReady =
    selectedRun !== null &&
    selectedRun.status !== "RECEIVED" &&
    selectedRun.status !== "OCR_RUNNING";

  const resultQuery = useQuery({
    queryKey: ["result", runId],
    queryFn: () => runsApi.result(runId),
    enabled: Boolean(runId) && terminal
  });
  const recordsQuery = useQuery({
    queryKey: ["records", runId],
    queryFn: () => runsApi.records(runId),
    enabled: Boolean(runId) && terminal,
    retry: false
  });
  const ocrQuery = useQuery({
    queryKey: ["ocr", runId],
    queryFn: () => runsApi.ocr(runId),
    enabled: Boolean(runId) && ocrReady,
    retry: false
  });
  const timelineQuery = useQuery({
    queryKey: ["timeline", runId],
    queryFn: () => runsApi.timeline(runId),
    enabled: Boolean(runId),
    // SSE 为主，轮询仅作为连接失败时的兜底。
    refetchInterval: terminal ? false : 5000
  });

  useEffect(() => {
    if (!runId || terminal) return;
    let timer: number | undefined;
    const stop = runsApi.subscribeEvents(runId, 0, () => {
      window.clearTimeout(timer);
      timer = window.setTimeout(() => {
        void queryClient.invalidateQueries({ queryKey: ["timeline", runId] });
        void queryClient.invalidateQueries({ queryKey: ["runs", documentId] });
      }, 150);
    });
    return () => {
      window.clearTimeout(timer);
      stop();
    };
  }, [runId, terminal, documentId, queryClient]);

  const runMutation = useMutation({
    mutationFn: () => documentsApi.createRun(documentId),
    onSuccess: (run) => {
      push("success", "解析已开始", `运行 ${run.id.slice(0, 8)}`);
      setSelectedRunId(run.id);
      setSearchParams({ run: run.id }, { replace: true });
      void queryClient.invalidateQueries({ queryKey: ["runs", documentId] });
    },
    onError: (error: Error) => push("error", "发起解析失败", error.message)
  });

  const cancelMutation = useMutation({
    mutationFn: () => runsApi.cancel(runId),
    onSuccess: () => {
      push("info", "已请求取消");
      void queryClient.invalidateQueries({ queryKey: ["runs", documentId] });
    },
    onError: (error: Error) => push("error", "取消失败", error.message)
  });

  const approveMutation = useMutation({
    mutationFn: () => runsApi.approve(runId),
    onSuccess: () => {
      push("success", "已确认结果");
      void queryClient.invalidateQueries({ queryKey: ["runs", documentId] });
    },
    onError: (error: Error) => push("error", "确认失败", error.message)
  });

  function selectRun(value: string) {
    setSelectedRunId(value);
    setSearchParams({ run: value }, { replace: true });
  }

  function feedbackFor(record: RecordItem, measure: string) {
    setFeedbackSeed({
      measure,
      description: `${record.grade} 的 ${measure} 抽取有误`
    });
    setTab("feedback");
  }

  async function exportResult(currentRecords: RecordItem[]) {
    if (!currentRecords.length) {
      push("error", "暂无可导出的结构化结果");
      return;
    }
    const filename = documentQuery.data?.filename || "解析结果";
    setExporting(true);
    try {
      const csv = buildResultCsv(
        currentRecords,
        filename,
        ocrQuery.data?.markdown ?? ""
      );
      const target = resultCsvFilename(filename);
      downloadBlob(new Blob([csv], { type: "text/csv;charset=utf-8" }), target);
      push("success", "导出完成", target);
    } finally {
      setExporting(false);
    }
  }

  const result = resultQuery.data?.result ?? null;
  const records = recordsQuery.data?.records ?? [];
  const recipeId = result?.recipes?.[0]?.recipe_id ?? "";
  const statusMeta = selectedRun ? runStatusMeta(selectedRun.status) : null;

  return (
    <div className="animate-fade-up">
      <PageHeader
        eyebrow="标准拆分"
        title={documentQuery.data?.filename ?? "解析详情"}
        description={
          documentQuery.data
            ? `${formatBytes(documentQuery.data.size)} · 上传于 ${formatDateTime(
                documentQuery.data.created_at
              )}`
            : undefined
        }
        actions={
          <>
            <Select
              value={selectedRunId}
              onChange={(event) => selectRun(event.target.value)}
              className="w-56"
              aria-label="选择运行"
            >
              {runs.length === 0 ? <option value="">暂无运行</option> : null}
              {runs.map((run) => (
                <option key={run.id} value={run.id}>
                  v{runVersions.get(run.id) ?? "?"} · {formatDateTime(run.created_at)}
                </option>
              ))}
            </Select>
            <Button
              variant="secondary"
              icon={<Download className="h-4 w-4" />}
              loading={exporting}
              disabled={!terminal || records.length === 0}
              onClick={() => void exportResult(records)}
            >
              导出
            </Button>
            <Button
              variant="secondary"
              icon={<RotateCcw className="h-4 w-4" />}
              loading={runMutation.isPending}
              onClick={() => runMutation.mutate()}
            >
              重新解析
            </Button>
            {selectedRun?.status === "HUMAN_REVIEW" ? (
              <Button
                icon={<ShieldCheck className="h-4 w-4" />}
                loading={approveMutation.isPending}
                onClick={() => approveMutation.mutate()}
              >
                确认结果
              </Button>
            ) : null}
            {selectedRun && !terminal ? (
              <Button
                variant="secondary"
                icon={<Ban className="h-4 w-4" />}
                loading={cancelMutation.isPending}
                onClick={() => cancelMutation.mutate()}
              >
                取消
              </Button>
            ) : null}
          </>
        }
      />

      {selectedRun ? (
        <div className="mb-4 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
          {statusMeta ? (
            <Badge tone={statusMeta.tone} dot>
              {statusMeta.label}
            </Badge>
          ) : null}
          <span>v{runVersions.get(selectedRun.id) ?? "?"}</span>
          <span>阶段 {selectedRun.stage}</span>
          {selectedRun.started_at && selectedRun.finished_at ? (
            <span>
              耗时{" "}
              {(
                (new Date(selectedRun.finished_at).getTime() -
                  new Date(selectedRun.started_at).getTime()) /
                1000
              ).toFixed(1)}{" "}
              s
            </span>
          ) : null}
          {selectedRun.error_code ? (
            <Badge tone="danger">{selectedRun.error_code}</Badge>
          ) : null}
        </div>
      ) : null}

      <Tabs items={TABS} active={tab} onChange={setTab} className="mb-4" />

      {!selectedRun ? (
        <Card>
          <EmptyState
            title="还没有运行"
            description="点击「重新解析」创建第一个运行"
            action={
              <Button onClick={() => runMutation.mutate()} loading={runMutation.isPending}>
                发起解析
              </Button>
            }
          />
        </Card>
      ) : null}

      {tab === "result" && selectedRun ? (
        <ResultTab
          documentId={documentId}
          view={view}
          onView={setView}
          terminal={terminal}
          records={records}
          loading={recordsQuery.isLoading}
          error={recordsQuery.isError ? recordsQuery.error.message : ""}
          result={result}
          filename={documentQuery.data?.filename ?? ""}
          markdown={ocrQuery.data?.markdown ?? ""}
          onFeedback={feedbackFor}
          onNewFeedback={() => setManualFeedbackOpen(true)}
          onRetry={() => void recordsQuery.refetch()}
        />
      ) : null}

      {tab === "cross" && selectedRun ? (
        <CrossStandardPanel documentId={documentId} runId={selectedRun.id} />
      ) : null}

      {tab === "feedback" && selectedRun ? (
        <FeedbackPanel
          documentId={documentId}
          runId={selectedRun.id}
          recipeId={recipeId}
          seed={feedbackSeed}
          onSeedConsumed={() => setFeedbackSeed(null)}
        />
      ) : null}

      {tab === "timeline" && selectedRun ? (
        timelineQuery.isLoading ? (
          <Skeleton className="h-64 w-full" />
        ) : timelineQuery.isError || !timelineQuery.data ? (
          <Card>
            <EmptyState
              title="时间线加载失败"
              description={timelineQuery.error?.message}
            />
          </Card>
        ) : (
          <RunTimelineView timeline={timelineQuery.data} />
        )
      ) : null}

      {selectedRun ? (
        <FeedbackDialog
          open={manualFeedbackOpen}
          runId={runId}
          recipeId={recipeId}
          onClose={() => setManualFeedbackOpen(false)}
          onCreated={() => {
            void queryClient.invalidateQueries({
              queryKey: ["feedback", documentId]
            });
            setTab("feedback");
          }}
        />
      ) : null}
    </div>
  );
}

function ResultTab({
  documentId,
  view,
  onView,
  terminal,
  records,
  loading,
  error,
  result,
  filename,
  markdown,
  onFeedback,
  onNewFeedback,
  onRetry
}: {
  documentId: string;
  view: "table" | "json";
  onView: (value: "table" | "json") => void;
  terminal: boolean;
  records: RecordItem[];
  loading: boolean;
  error: string;
  result: SandboxResult | null;
  filename: string;
  markdown: string;
  onFeedback: (record: RecordItem, measure: string) => void;
  onNewFeedback: () => void;
  onRetry: () => void;
}) {
  return (
    <div className="grid items-start gap-4 xl:grid-cols-2">
      <Card className="min-w-0 overflow-hidden xl:sticky xl:top-20">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-5 py-3">
          <div>
            <h3 className="text-sm font-semibold">原文</h3>
            <p className="text-xs text-muted-foreground">{filename || "标准原文"}</p>
          </div>
          <a
            href={documentsApi.fileUrl(documentId)}
            target="_blank"
            rel="noreferrer"
            className="text-xs font-medium text-primary-strong hover:underline"
          >
            新窗口打开
          </a>
        </div>
        <iframe
          src={`${documentsApi.fileUrl(documentId)}#navpanes=0`}
          title="标准原文"
          className="h-[calc(100vh-260px)] min-h-[520px] w-full bg-white"
        />
      </Card>

      <Card className="min-w-0">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-5 py-3">
          <div>
            <h3 className="text-sm font-semibold">结构化结果</h3>
            <p className="text-xs text-muted-foreground">
              {terminal ? `${records.length} 条记录` : "解析进行中"}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              size="sm"
              variant="secondary"
              icon={<MessageSquarePlus className="h-3.5 w-3.5" />}
              onClick={onNewFeedback}
            >
              新建反馈
            </Button>
            <div className="flex items-center gap-1 rounded-lg border border-border bg-background-soft p-0.5">
              <button
                type="button"
                className={`rounded-md px-2.5 py-1 text-xs ${
                  view === "table" ? "bg-card shadow-soft" : "text-muted-foreground"
                }`}
                onClick={() => onView("table")}
              >
                表格
              </button>
              <button
                type="button"
                className={`rounded-md px-2.5 py-1 text-xs ${
                  view === "json" ? "bg-card shadow-soft" : "text-muted-foreground"
                }`}
                onClick={() => onView("json")}
              >
                JSON
              </button>
            </div>
          </div>
        </div>
        {!terminal ? (
          <div className="p-5">
            <EmptyState
              title="解析进行中"
              description="运行完成后自动展示结果，无需刷新页面"
              action={<FileText className="mx-auto h-8 w-8 text-primary" />}
            />
          </div>
        ) : loading ? (
          <div className="space-y-3 p-5">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-2/3" />
          </div>
        ) : error ? (
          <div className="p-5">
            <EmptyState
              title="结果加载失败"
              description={error}
              action={
                <Button
                  variant="secondary"
                  icon={<RefreshCcw className="h-4 w-4" />}
                  onClick={onRetry}
                >
                  重试
                </Button>
              }
            />
          </div>
        ) : view === "table" ? (
          <ResultTable
            records={records}
            filename={filename}
            markdown={markdown}
            onFeedback={onFeedback}
          />
        ) : (
          <div className="p-4">
            <ResultJson value={{ result, records }} />
          </div>
        )}
      </Card>
    </div>
  );
}
