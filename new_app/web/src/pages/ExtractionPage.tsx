import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Ban,
  ExternalLink,
  FileText,
  RefreshCcw,
  RotateCcw,
  ShieldCheck
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { documentsApi } from "../api/documents";
import { runsApi } from "../api/runs";
import type {
  RecordItem,
  ReviewReport,
  RunItem,
  SandboxResult
} from "../api/types";
import { FeedbackPanel } from "../components/feedback/FeedbackPanel";
import { PagePreview } from "../components/preview/PagePreview";
import { RecipeTraceCard } from "../components/recipe/RecipeTraceCard";
import { ResultJson } from "../components/result/ResultJson";
import { ResultTable } from "../components/result/ResultTable";
import { ReviewFindings } from "../components/review/ReviewFindings";
import { RunTimelineView } from "../components/timeline/RunTimeline";
import { VersionCompare } from "../components/version/VersionCompare";
import {
  Badge,
  Button,
  Card,
  CardContent,
  EmptyState,
  PageHeader,
  Skeleton
} from "../components/ui/primitives";
import { Select } from "../components/ui/form";
import { Tabs } from "../components/ui/tabs";
import { useToast } from "../components/ui/toast";
import { RUN_TERMINAL, runStatusMeta } from "../lib/status";
import { formatBytes, formatDateTime } from "../lib/utils";

const TABS = [
  { id: "result", label: "结果" },
  { id: "review", label: "审核" },
  { id: "feedback", label: "反馈" },
  { id: "timeline", label: "时间线" },
  { id: "versions", label: "版本" },
  { id: "preview", label: "原文预览" }
];

export default function ExtractionPage() {
  const { documentId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const { push } = useToast();
  const queryClient = useQueryClient();

  const [tab, setTab] = useState("result");
  const [view, setView] = useState<"table" | "json">("table");
  const [selectedRunId, setSelectedRunId] = useState(searchParams.get("run") ?? "");
  const [pageNo, setPageNo] = useState(1);
  const [feedbackSeed, setFeedbackSeed] = useState<{
    measure: string;
    description: string;
  } | null>(null);
  const [leftId, setLeftId] = useState("");
  const [rightId, setRightId] = useState("");

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

  useEffect(() => {
    if (runs.length === 0) return;
    if (!selectedRunId || !runs.some((run) => run.id === selectedRunId)) {
      setSelectedRunId(runs[0].id);
    }
  }, [runs, selectedRunId]);

  useEffect(() => {
    if (runs.length >= 2 && !leftId) {
      setLeftId(runs[1].id);
      setRightId(runs[0].id);
    }
  }, [runs, leftId]);

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
  const reviewQuery = useQuery({
    queryKey: ["review", runId],
    queryFn: () => runsApi.review(runId),
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
    refetchInterval: terminal ? false : 1500
  });

  const leftRun = runs.find((run) => run.id === leftId) ?? null;
  const rightRun = runs.find((run) => run.id === rightId) ?? null;
  const leftRecords = useQuery({
    queryKey: ["records", leftId],
    queryFn: () => runsApi.records(leftId),
    enabled: Boolean(leftId) && (leftRun ? RUN_TERMINAL.has(leftRun.status) : false),
    retry: false
  });
  const rightRecords = useQuery({
    queryKey: ["records", rightId],
    queryFn: () => runsApi.records(rightId),
    enabled: Boolean(rightId) && (rightRun ? RUN_TERMINAL.has(rightRun.status) : false),
    retry: false
  });

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
                  {run.id.slice(0, 8)} · {runStatusMeta(run.status).label} ·{" "}
                  {formatDateTime(run.created_at)}
                </option>
              ))}
            </Select>
            <Button
              variant="secondary"
              icon={<RotateCcw className="h-4 w-4" />}
              loading={runMutation.isPending}
              onClick={() => runMutation.mutate()}
            >
              重新解析
            </Button>
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
            {runId ? (
              <Link
                to={`/documents/${documentId}/viewer?run=${runId}`}
                className="inline-flex h-9 items-center gap-2 rounded-lg border border-border bg-card px-3.5 text-sm font-medium text-foreground shadow-soft transition-colors hover:border-primary/40"
              >
                <ExternalLink className="h-4 w-4" />
                预览
              </Link>
            ) : null}
          </>
        }
      />

      {selectedRun ? (
        <div className="mb-4 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          {statusMeta ? (
            <Badge tone={statusMeta.tone} dot>
              {statusMeta.label}
            </Badge>
          ) : null}
          <span>运行 {selectedRun.id.slice(0, 8)}</span>
          <span>通道 {selectedRun.recipe_channel}</span>
          <span>阶段 {selectedRun.stage}</span>
          {selectedRun.error_code ? (
            <Badge tone="danger">{selectedRun.error_code}</Badge>
          ) : null}
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
        </div>
      ) : null}

      <Tabs
        items={TABS}
        active={tab}
        onChange={setTab}
        className="mb-4"
      />

      {!selectedRun ? (
        <Card>
          <CardContent>
            <EmptyState
              title="还没有运行"
              description="点击「重新解析」创建第一个运行"
              action={
                <Button onClick={() => runMutation.mutate()} loading={runMutation.isPending}>
                  发起解析
                </Button>
              }
            />
          </CardContent>
        </Card>
      ) : null}

      {tab === "result" && selectedRun ? (
        <ResultTab
          view={view}
          onView={setView}
          terminal={terminal}
          records={records}
          loading={recordsQuery.isLoading}
          error={recordsQuery.isError ? recordsQuery.error.message : ""}
          result={result}
          review={reviewQuery.data ?? null}
          run={selectedRun}
          onFeedback={feedbackFor}
          onRetry={() => void recordsQuery.refetch()}
        />
      ) : null}

      {tab === "review" && selectedRun ? (
        reviewQuery.isLoading ? (
          <Skeleton className="h-40 w-full" />
        ) : reviewQuery.isError || !reviewQuery.data ? (
          <Card>
            <CardContent>
              <EmptyState
                title="审核结果尚未生成"
                description={
                  terminal
                    ? reviewQuery.error?.message ?? "运行未产出审核报告"
                    : "运行完成后自动生成审核报告"
                }
                action={<ShieldCheck className="mx-auto h-8 w-8 text-muted-foreground" />}
              />
            </CardContent>
          </Card>
        ) : (
          <ReviewFindings report={reviewQuery.data} />
        )
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
            <CardContent>
              <EmptyState
                title="时间线加载失败"
                description={timelineQuery.error?.message}
              />
            </CardContent>
          </Card>
        ) : (
          <RunTimelineView timeline={timelineQuery.data} />
        )
      ) : null}

      {tab === "versions" ? (
        <VersionCompare
          runs={runs}
          leftId={leftId}
          rightId={rightId}
          onLeft={setLeftId}
          onRight={setRightId}
          leftRecords={leftRecords.data?.records ?? []}
          rightRecords={rightRecords.data?.records ?? []}
          loading={leftRecords.isLoading || rightRecords.isLoading}
        />
      ) : null}

      {tab === "preview" && selectedRun ? (
        ocrQuery.isLoading ? (
          <Skeleton className="h-80 w-full" />
        ) : ocrQuery.isError || !ocrQuery.data ? (
          <Card>
            <CardContent>
              <EmptyState
                title="原文预览尚未就绪"
                description={
                  ocrReady
                    ? ocrQuery.error?.message ?? "OCR 未产出页面"
                    : "OCR 完成后可查看原文与表格"
                }
              />
            </CardContent>
          </Card>
        ) : (
          <PagePreview
            runId={selectedRun.id}
            ocr={ocrQuery.data}
            pageNo={pageNo}
            onPageChange={setPageNo}
            tall
          />
        )
      ) : null}
    </div>
  );
}

function ResultTab({
  view,
  onView,
  terminal,
  records,
  loading,
  error,
  result,
  review,
  run,
  onFeedback,
  onRetry
}: {
  view: "table" | "json";
  onView: (value: "table" | "json") => void;
  terminal: boolean;
  records: RecordItem[];
  loading: boolean;
  error: string;
  result: SandboxResult | null;
  review: ReviewReport | null;
  run: RunItem;
  onFeedback: (record: RecordItem, measure: string) => void;
  onRetry: () => void;
}) {
  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
      <Card className="min-w-0">
        <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-5 py-3">
          <div>
            <h3 className="text-sm font-semibold">结构化结果</h3>
            <p className="text-xs text-muted-foreground">
              {terminal ? `${records.length} 条记录` : "解析进行中"}
            </p>
          </div>
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
        {!terminal ? (
          <CardContent>
            <EmptyState
              title="解析进行中"
              description="运行完成后自动展示结果，无需刷新页面"
              action={<FileText className="mx-auto h-8 w-8 text-primary" />}
            />
          </CardContent>
        ) : loading ? (
          <div className="space-y-3 p-5">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-2/3" />
          </div>
        ) : error ? (
          <CardContent>
            <EmptyState
              title="结果加载失败"
              description={error}
              action={
                <Button variant="secondary" icon={<RefreshCcw className="h-4 w-4" />} onClick={onRetry}>
                  重试
                </Button>
              }
            />
          </CardContent>
        ) : view === "table" ? (
          <ResultTable records={records} onFeedback={onFeedback} />
        ) : (
          <div className="p-4">
            <ResultJson value={{ result, records }} />
          </div>
        )}
      </Card>
      <div className="space-y-4">
        <RecipeTraceCard run={run} result={result} review={review} />
        <Card>
          <CardContent className="space-y-1 text-xs text-muted-foreground">
            <p>点击结果单元格旁的图标可直接发起字段反馈。</p>
            <p>反馈处理会生成候选配方并在沙箱中定向验证。</p>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
