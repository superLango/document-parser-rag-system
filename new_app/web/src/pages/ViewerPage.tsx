import { useQuery } from "@tanstack/react-query";
import { ArrowLeft } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";

import { documentsApi } from "../api/documents";
import { runsApi } from "../api/runs";
import { PagePreview } from "../components/preview/PagePreview";
import { Card, CardContent, EmptyState, PageHeader, Skeleton } from "../components/ui/primitives";
import { Select } from "../components/ui/form";
import { RUN_TERMINAL, runStatusMeta } from "../lib/status";
import { formatDateTime } from "../lib/utils";

export default function ViewerPage() {
  const { documentId = "" } = useParams();
  const [searchParams, setSearchParams] = useSearchParams();
  const [selectedRunId, setSelectedRunId] = useState(searchParams.get("run") ?? "");
  const [pageNo, setPageNo] = useState(1);

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
    enabled: Boolean(documentId)
  });

  const runs = useMemo(() => runsQuery.data ?? [], [runsQuery.data]);

  useEffect(() => {
    if (runs.length === 0) return;
    if (!selectedRunId || !runs.some((run) => run.id === selectedRunId)) {
      setSelectedRunId(runs[0].id);
    }
  }, [runs, selectedRunId]);

  const selectedRun = runs.find((run) => run.id === selectedRunId) ?? null;
  const ocrReady =
    selectedRun !== null &&
    selectedRun.status !== "RECEIVED" &&
    selectedRun.status !== "OCR_RUNNING";

  const ocrQuery = useQuery({
    queryKey: ["ocr", selectedRun?.id ?? ""],
    queryFn: () => runsApi.ocr(selectedRun!.id),
    enabled: Boolean(selectedRun) && ocrReady,
    retry: false
  });

  return (
    <div className="animate-fade-up">
      <PageHeader
        eyebrow="标准拆分"
        title="原文预览"
        description={documentQuery.data?.filename}
        actions={
          <>
            <Link
              to={`/documents/${documentId}${selectedRunId ? `?run=${selectedRunId}` : ""}`}
              className="inline-flex h-9 items-center gap-2 rounded-lg border border-border bg-card px-3.5 text-sm font-medium shadow-soft transition-colors hover:border-primary/40"
            >
              <ArrowLeft className="h-4 w-4" />
              返回详情
            </Link>
            <Select
              value={selectedRunId}
              onChange={(event) => {
                setSelectedRunId(event.target.value);
                setSearchParams({ run: event.target.value }, { replace: true });
              }}
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
          </>
        }
      />

      {!selectedRun ? (
        <Card>
          <CardContent>
            <EmptyState title="没有可预览的运行" description="先在文档库发起解析" />
          </CardContent>
        </Card>
      ) : ocrQuery.isLoading ? (
        <Skeleton className="h-[70vh] w-full" />
      ) : ocrQuery.isError || !ocrQuery.data ? (
        <Card>
          <CardContent>
            <EmptyState
              title="预览尚未就绪"
              description={
                ocrReady
                  ? ocrQuery.error?.message ?? "OCR 未产出页面"
                  : `运行状态：${runStatusMeta(selectedRun.status).label}`
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
      )}

      {selectedRun && RUN_TERMINAL.has(selectedRun.status) ? (
        <p className="mt-3 text-[11px] text-muted-foreground">
          运行完成于 {formatDateTime(selectedRun.finished_at)}
        </p>
      ) : null}
    </div>
  );
}
