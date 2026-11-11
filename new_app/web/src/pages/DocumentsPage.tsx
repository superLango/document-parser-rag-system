import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, Plus, RefreshCcw, Trash2, UploadCloud } from "lucide-react";
import { useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";

import { documentsApi } from "../api/documents";
import { runsApi } from "../api/runs";
import type { DocumentItem, RunItem } from "../api/types";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  PageHeader,
  Skeleton
} from "../components/ui/primitives";
import { Dialog } from "../components/ui/dialog";
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
import { formatBytes, formatDateTime } from "../lib/utils";

const MAX_SIZE = 100 * 1024 * 1024;
const ACCEPT = ".pdf,.md,.markdown,.txt";

export default function DocumentsPage() {
  const { push } = useToast();
  const queryClient = useQueryClient();
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DocumentItem | null>(null);

  const documentsQuery = useQuery({
    queryKey: ["documents"],
    queryFn: documentsApi.list
  });
  const runsQuery = useQuery({
    queryKey: ["runs"],
    queryFn: () => runsApi.list(),
    refetchInterval: (query) => {
      const data = query.state.data as RunItem[] | undefined;
      return data?.some((run) => !RUN_TERMINAL.has(run.status)) ? 1500 : false;
    }
  });

  const latestRunByDocument = useMemo(() => {
    const map = new Map<string, RunItem>();
    for (const run of runsQuery.data ?? []) {
      const current = map.get(run.document_id);
      if (!current || new Date(run.created_at) > new Date(current.created_at)) {
        map.set(run.document_id, run);
      }
    }
    return map;
  }, [runsQuery.data]);

  const uploadMutation = useMutation({
    mutationFn: (target: File) => documentsApi.upload(target),
    onSuccess: (document) => {
      push("success", "文档已上传", document.filename);
      setUploadOpen(false);
      setFile(null);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
    },
    onError: (error: Error) => push("error", "上传失败", error.message)
  });

  const runMutation = useMutation({
    mutationFn: (documentId: string) => documentsApi.createRun(documentId),
    onSuccess: (run) => {
      push("success", "解析已开始", `运行 ${run.id.slice(0, 8)}`);
      void queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
    onError: (error: Error) => push("error", "发起解析失败", error.message)
  });

  const deleteMutation = useMutation({
    mutationFn: (documentId: string) => documentsApi.remove(documentId),
    onSuccess: () => {
      push("success", "文档已删除");
      setDeleteTarget(null);
      void queryClient.invalidateQueries({ queryKey: ["documents"] });
      void queryClient.invalidateQueries({ queryKey: ["runs"] });
    },
    onError: (error: Error) => push("error", "删除失败", error.message)
  });

  const documents = documentsQuery.data ?? [];
  const activeCount =
    runsQuery.data?.filter((run) => !RUN_TERMINAL.has(run.status)).length ?? 0;

  function chooseFile(next: File | null | undefined) {
    if (!next) return;
    if (next.size > MAX_SIZE) {
      push("error", "文件过大", "单个文件不能超过 100MB");
      return;
    }
    setFile(next);
  }

  return (
    <div className="animate-fade-up">
      <PageHeader
        eyebrow="标准拆分"
        title="文档库"
        description={`共 ${documents.length} 份文档${activeCount ? ` · ${activeCount} 个运行进行中` : ""}`}
        actions={
          <>
            <Button
              variant="secondary"
              icon={<RefreshCcw className="h-4 w-4" />}
              onClick={() => {
                void documentsQuery.refetch();
                void runsQuery.refetch();
              }}
              loading={documentsQuery.isFetching || runsQuery.isFetching}
            >
              刷新
            </Button>
            <Button
              icon={<Plus className="h-4 w-4" />}
              onClick={() => {
                setFile(null);
                setUploadOpen(true);
              }}
            >
              上传文档
            </Button>
          </>
        }
      />

      <Card>
        {documentsQuery.isLoading ? (
          <div className="space-y-3 p-5">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-2/3" />
          </div>
        ) : documentsQuery.isError ? (
          <div className="p-5">
            <EmptyState
              title="文档列表加载失败"
              description={documentsQuery.error.message}
              action={
                <Button variant="secondary" onClick={() => void documentsQuery.refetch()}>
                  重试
                </Button>
              }
            />
          </div>
        ) : documents.length === 0 ? (
          <div className="p-5">
            <EmptyState
              title="还没有文档"
              description="上传 PDF、Markdown 或文本文件开始标准拆分"
              action={
                <Button onClick={() => setUploadOpen(true)} icon={<UploadCloud className="h-4 w-4" />}>
                  上传文档
                </Button>
              }
            />
          </div>
        ) : (
          <Table>
            <TableHead>
              <TableRow>
                <TableHeaderCell>文件</TableHeaderCell>
                <TableHeaderCell>大小</TableHeaderCell>
                <TableHeaderCell>上传时间</TableHeaderCell>
                <TableHeaderCell>最近运行</TableHeaderCell>
                <TableHeaderCell className="text-right">操作</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {documents.map((document) => {
                const run = latestRunByDocument.get(document.id);
                const meta = run ? runStatusMeta(run.status) : null;
                return (
                  <TableRow key={document.id}>
                    <TableCell>
                      <div className="flex items-center gap-3">
                        <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-emerald-50 text-emerald-700">
                          <FileText className="h-4 w-4" />
                        </span>
                        <div className="min-w-0">
                          <Link
                            to={`/documents/${document.id}${run ? `?run=${run.id}` : ""}`}
                            className="block max-w-md truncate font-medium text-foreground hover:text-primary-strong"
                          >
                            {document.filename}
                          </Link>
                          <p className="text-[11px] text-muted-foreground">
                            {document.content_type || "application/octet-stream"}
                          </p>
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatBytes(document.size)}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {formatDateTime(document.created_at)}
                    </TableCell>
                    <TableCell>
                      {run && meta ? (
                        <div className="flex flex-col gap-1">
                          <Badge tone={meta.tone} dot>
                            {meta.label}
                          </Badge>
                          <span className="text-[11px] text-muted-foreground">
                            {formatDateTime(run.created_at)}
                          </span>
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground">未解析</span>
                      )}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center justify-end gap-1.5">
                        <Button
                          size="sm"
                          variant="secondary"
                          onClick={() => runMutation.mutate(document.id)}
                          loading={
                            runMutation.isPending &&
                            runMutation.variables === document.id
                          }
                        >
                          发起解析
                        </Button>
                        <Button
                          size="sm"
                          variant="ghost"
                          onClick={() => setDeleteTarget(document)}
                          icon={<Trash2 className="h-3.5 w-3.5" />}
                          aria-label={`删除 ${document.filename}`}
                        />
                      </div>
                    </TableCell>
                  </TableRow>
                );
              })}
            </TableBody>
          </Table>
        )}
      </Card>

      <Dialog
        open={uploadOpen}
        title="上传文档"
        description="支持 PDF、Markdown、TXT；同一内容会按 sha256 去重"
        onClose={() => setUploadOpen(false)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setUploadOpen(false)}>
              取消
            </Button>
            <Button
              disabled={!file}
              loading={uploadMutation.isPending}
              onClick={() => file && uploadMutation.mutate(file)}
            >
              上传
            </Button>
          </>
        }
      >
        <input
          ref={inputRef}
          type="file"
          accept={ACCEPT}
          className="hidden"
          onChange={(event) => chooseFile(event.target.files?.[0])}
        />
        <div
          className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border border-dashed border-border bg-background-soft px-6 py-10 text-center transition-colors hover:border-primary/50"
          onClick={() => inputRef.current?.click()}
          onDragOver={(event) => event.preventDefault()}
          onDrop={(event) => {
            event.preventDefault();
            chooseFile(event.dataTransfer.files?.[0]);
          }}
        >
          <UploadCloud className="h-8 w-8 text-primary" />
          <p className="text-sm font-medium">
            {file ? file.name : "点击选择或拖拽文件到这里"}
          </p>
          <p className="text-xs text-muted-foreground">
            {file ? formatBytes(file.size) : "PDF / Markdown / TXT，最大 100MB"}
          </p>
        </div>
      </Dialog>

      <Dialog
        open={deleteTarget !== null}
        title="删除文档"
        description="将同时删除该文档的运行、产物与反馈，且不可恢复"
        onClose={() => setDeleteTarget(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setDeleteTarget(null)}>
              取消
            </Button>
            <Button
              variant="danger"
              loading={deleteMutation.isPending}
              onClick={() => deleteTarget && deleteMutation.mutate(deleteTarget.id)}
            >
              确认删除
            </Button>
          </>
        }
      >
        <p className="text-sm text-muted-foreground">
          确认删除「{deleteTarget?.filename}」？
        </p>
      </Dialog>
    </div>
  );
}
