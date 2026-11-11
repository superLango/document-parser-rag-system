import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Ban, RefreshCcw } from "lucide-react";
import { useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { documentsApi } from "../api/documents";
import { runsApi } from "../api/runs";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  PageHeader,
  Skeleton
} from "../components/ui/primitives";
import { Input, Select } from "../components/ui/form";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow
} from "../components/ui/table";
import { useToast } from "../components/ui/toast";
import { RUN_TERMINAL, runStatusMeta } from "../lib/status";
import { formatDateTime, formatDuration } from "../lib/utils";

export default function RunsPage() {
  const { push } = useToast();
  const queryClient = useQueryClient();
  const [status, setStatus] = useState("");
  const [keyword, setKeyword] = useState("");

  const runsQuery = useQuery({
    queryKey: ["runs"],
    queryFn: () => runsApi.list(),
    refetchInterval: (query) => {
      const data = query.state.data as { status: string }[] | undefined;
      return data?.some((run) => !RUN_TERMINAL.has(run.status)) ? 1500 : false;
    }
  });
  const documentsQuery = useQuery({
    queryKey: ["documents"],
    queryFn: documentsApi.list
  });

  const documentNames = useMemo(() => {
    const map = new Map<string, string>();
    for (const document of documentsQuery.data ?? []) {
      map.set(document.id, document.filename);
    }
    return map;
  }, [documentsQuery.data]);

  const runs = useMemo(() => {
    const search = keyword.trim().toLowerCase();
    return (runsQuery.data ?? []).filter((run) => {
      if (status && run.status !== status) return false;
      if (!search) return true;
      return (
        run.id.toLowerCase().includes(search) ||
        (documentNames.get(run.document_id) ?? "").toLowerCase().includes(search)
      );
    });
  }, [runsQuery.data, status, keyword, documentNames]);

  const cancelMutation = useMutation({
    mutationFn: (id: string) => runsApi.cancel(id),
    onSuccess: () => {
      push("info", "已请求取消");
      void queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
    onError: (error: Error) => push("error", "取消失败", error.message)
  });

  return (
    <div className="animate-fade-up">
      <PageHeader
        eyebrow="运行"
        title="运行记录"
        description={`${runs.length} 个运行`}
        actions={
          <Button
            variant="secondary"
            icon={<RefreshCcw className="h-4 w-4" />}
            loading={runsQuery.isFetching}
            onClick={() => void runsQuery.refetch()}
          >
            刷新
          </Button>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <Input
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          placeholder="搜索运行 ID / 文档名"
          className="w-64"
        />
        <Select value={status} onChange={(event) => setStatus(event.target.value)} className="w-40">
          <option value="">全部状态</option>
          {[
            "RECEIVED",
            "OCR_RUNNING",
            "ROUTING",
            "SANDBOX_RUNNING",
            "REVIEWING",
            "STRUCTURED_READY",
            "FAILED",
            "CANCELLED"
          ].map((value) => (
            <option key={value} value={value}>
              {runStatusMeta(value).label}
            </option>
          ))}
        </Select>
      </div>

      <Card>
        {runsQuery.isLoading ? (
          <div className="space-y-3 p-5">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-2/3" />
          </div>
        ) : runs.length === 0 ? (
          <div className="p-5">
            <EmptyState title="没有匹配的运行" description="调整筛选条件或先在文档库发起解析" />
          </div>
        ) : (
          <Table>
            <TableHead>
              <TableRow>
                <TableHeaderCell>运行</TableHeaderCell>
                <TableHeaderCell>文档</TableHeaderCell>
                <TableHeaderCell>状态</TableHeaderCell>
                <TableHeaderCell>通道</TableHeaderCell>
                <TableHeaderCell>创建时间</TableHeaderCell>
                <TableHeaderCell>耗时</TableHeaderCell>
                <TableHeaderCell className="text-right">操作</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {runs.map((run) => {
                const meta = runStatusMeta(run.status);
                const duration =
                  run.started_at && run.finished_at
                    ? new Date(run.finished_at).getTime() -
                      new Date(run.started_at).getTime()
                    : null;
                return (
                  <TableRow key={run.id}>
                    <TableCell>
                      <span className="font-mono text-xs">{run.id.slice(0, 8)}</span>
                      {run.error_code ? (
                        <Badge tone="danger" className="ml-2">
                          {run.error_code}
                        </Badge>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <Link
                        to={`/documents/${run.document_id}?run=${run.id}`}
                        className="text-sm hover:text-primary-strong"
                      >
                        {documentNames.get(run.document_id) ?? run.document_id.slice(0, 8)}
                      </Link>
                    </TableCell>
                    <TableCell>
                      <Badge tone={meta.tone} dot>
                        {meta.label}
                      </Badge>
                    </TableCell>
                    <TableCell className="text-muted-foreground">{run.recipe_channel}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDateTime(run.created_at)}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDuration(duration)}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-1.5">
                        <Link
                          to={`/documents/${run.document_id}?run=${run.id}`}
                          className="inline-flex h-8 items-center rounded-lg border border-border bg-card px-2.5 text-xs font-medium shadow-soft transition-colors hover:border-primary/40"
                        >
                          查看
                        </Link>
                        {!RUN_TERMINAL.has(run.status) ? (
                          <Button
                            size="sm"
                            variant="ghost"
                            icon={<Ban className="h-3.5 w-3.5" />}
                            loading={
                              cancelMutation.isPending && cancelMutation.variables === run.id
                            }
                            onClick={() => cancelMutation.mutate(run.id)}
                          >
                            取消
                          </Button>
                        ) : null}
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </Card>
    </div>
  );
}
