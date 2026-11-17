import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Download,
  FileText,
  FolderDown,
  Plus,
  RefreshCcw,
  Search,
  ShieldCheck,
  Trash2,
  UploadCloud
} from "lucide-react";
import { useDeferredValue, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

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
import { Input, Select } from "../components/ui/form";
import { Pagination } from "../components/ui/pagination";
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
import { formatBytes, formatDateTime, formatDuration } from "../lib/utils";
import {
  buildResultCsv,
  downloadBlob,
  fileTimestamp,
  resultCsvFilename
} from "../lib/resultExport";
import { createZip, type ZipFile } from "../lib/zip";
import {
  EXTRACT_DEFAULT,
  EXTRACT_STATUSES,
  fitFileName,
  folderNumbers,
  orMissing,
  safeName,
  stemOf,
  uploadedWithin
} from "../lib/extract";

type DirectoryPicker = (options?: { mode?: "read" | "readwrite" }) => Promise<FileSystemDirectoryHandle>;

// 浏览器仅在 HTTPS（或被设为可信的地址）下提供「选择文件夹」，否则退回 ZIP 下载。
function directoryPicker(): DirectoryPicker | undefined {
  return (window as unknown as { showDirectoryPicker?: DirectoryPicker }).showDirectoryPicker;
}

async function fileExists(dir: FileSystemDirectoryHandle, name: string): Promise<boolean> {
  try {
    await dir.getFileHandle(name);
    return true;
  } catch (error) {
    if ((error as DOMException).name === "NotFoundError") return false;
    throw error;
  }
}

const MAX_SIZE = 100 * 1024 * 1024;
const ACCEPT = ".pdf,.md,.markdown,.txt";
const PAGE_SIZE = 20;
const UNPARSED = "UNPARSED";
// 这些终态已经产出结构化结果，文档库直接提供「审核」入口。
const REVIEWABLE = new Set([
  "STRUCTURED_READY",
  "REVIEW_FAILED",
  "HUMAN_REVIEW",
  "HUMAN_APPROVED",
  "HUMAN_REJECTED"
]);
const STATUS_OPTIONS = [
  "RECEIVED",
  "OCR_RUNNING",
  "ROUTING",
  "SANDBOX_RUNNING",
  "REVIEWING",
  "REPAIRING",
  "REPARSING",
  "HUMAN_REVIEW",
  "HUMAN_APPROVED",
  "HUMAN_REJECTED",
  "STRUCTURED_READY",
  "REVIEW_FAILED",
  "UNROUTED",
  "FAILED",
  "CANCELLED"
];

export default function DocumentsPage() {
  const { push } = useToast();
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [file, setFile] = useState<File | null>(null);
  const [deleteTarget, setDeleteTarget] = useState<DocumentItem | null>(null);
  const [exportOpen, setExportOpen] = useState(false);
  const [exportKeyword, setExportKeyword] = useState("");
  const [exportSelected, setExportSelected] = useState<Set<string>>(new Set());
  const [exporting, setExporting] = useState(false);
  const [exportProgress, setExportProgress] = useState("");
  const [extractOpen, setExtractOpen] = useState(false);
  const [extractFrom, setExtractFrom] = useState("");
  const [extractTo, setExtractTo] = useState("");
  const [extractStatuses, setExtractStatuses] = useState<Set<string>>(new Set(EXTRACT_DEFAULT));
  const [extracting, setExtracting] = useState(false);
  const [extractProgress, setExtractProgress] = useState("");
  const [keyword, setKeyword] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [page, setPage] = useState(1);
  const deferredKeyword = useDeferredValue(keyword);

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

  const exportCandidates = useMemo(() => {
    const search = exportKeyword.trim().toLowerCase();
    return documents.filter((document) => {
      if (!search) return true;
      return (
        document.filename.toLowerCase().includes(search) ||
        document.id.toLowerCase().includes(search)
      );
    });
  }, [documents, exportKeyword]);

  function toggleExportSelected(documentId: string) {
    setExportSelected((previous) => {
      const next = new Set(previous);
      if (next.has(documentId)) {
        next.delete(documentId);
      } else {
        next.add(documentId);
      }
      return next;
    });
  }

  function toggleAllExport() {
    const ids = exportCandidates
      .map((document) => document.id)
      .filter((documentId) => {
        const run = latestRunByDocument.get(documentId);
        return Boolean(run && RUN_TERMINAL.has(run.status));
      });
    const allSelected =
      ids.length > 0 && ids.every((documentId) => exportSelected.has(documentId));
    setExportSelected(allSelected ? new Set() : new Set(ids));
  }

  async function runBatchExport() {
    const selected = documents.filter((document) =>
      exportSelected.has(document.id)
    );
    if (selected.length === 0) {
      push("error", "请选择要导出的文档");
      return;
    }
    setExporting(true);
    const at = new Date();
    const files: { name: string; content: string }[] = [];
    let skipped = 0;
    for (let index = 0; index < selected.length; index += 1) {
      const document = selected[index];
      setExportProgress(`${index + 1}/${selected.length}`);
      const run = latestRunByDocument.get(document.id);
      if (!run || !RUN_TERMINAL.has(run.status)) {
        skipped += 1;
        continue;
      }
      try {
        const payload = await runsApi.records(run.id);
        const records = payload.records ?? [];
        if (records.length === 0) {
          skipped += 1;
          continue;
        }
        files.push({
          name: `${String(files.length + 1).padStart(3, "0")}-${resultCsvFilename(
            document.filename,
            at
          )}`,
          content: buildResultCsv(records, document.filename)
        });
      } catch {
        skipped += 1;
      }
    }
    setExportProgress("");
    setExporting(false);
    if (files.length === 0) {
      push(
        "error",
        "没有可导出的结构化结果",
        skipped ? `${skipped} 份文档无可导出记录` : undefined
      );
      return;
    }
    downloadBlob(createZip(files), `文档库导出-${fileTimestamp(at)}.zip`);
    push(
      "success",
      "批量导出完成",
      `${files.length} 份${skipped ? `，跳过 ${skipped} 份` : ""}`
    );
    setExportOpen(false);
    setExportSelected(new Set());
  }

  // 时间范围内各状态的文档数（按最近运行，与列表「最近运行」列一致）
  const extractStatusCounts = useMemo(() => {
    const counts = new Map<string, number>();
    for (const document of documents) {
      const status = latestRunByDocument.get(document.id)?.status;
      if (status && uploadedWithin(document, extractFrom, extractTo)) {
        counts.set(status, (counts.get(status) ?? 0) + 1);
      }
    }
    return counts;
  }, [documents, latestRunByDocument, extractFrom, extractTo]);
  const extractCandidates = useMemo(
    () =>
      documents.filter((document) => {
        const run = latestRunByDocument.get(document.id);
        return (
          run !== undefined &&
          extractStatuses.has(run.status) &&
          uploadedWithin(document, extractFrom, extractTo)
        );
      }),
    [documents, latestRunByDocument, extractStatuses, extractFrom, extractTo]
  );

  function toggleExtractStatus(status: string) {
    setExtractStatuses((previous) => {
      const next = new Set(previous);
      if (next.has(status)) next.delete(status);
      else next.add(status);
      return next;
    });
  }

  async function runExtract() {
    const picker = directoryPicker();
    let root: FileSystemDirectoryHandle | null = null;
    if (picker) {
      try {
        // 必须在点击后第一时间调用，浏览器才允许弹出文件夹选择
        root = await picker({ mode: "readwrite" });
      } catch {
        return; // 用户取消选择
      }
    }
    const at = new Date();
    const folders = folderNumbers(documents);
    const zipFiles: ZipFile[] = [];
    let written = 0;
    let skipped = 0;
    let missing = 0;
    let failed = 0;
    setExtracting(true);
    for (let index = 0; index < extractCandidates.length; index += 1) {
      const document = extractCandidates[index];
      const run = latestRunByDocument.get(document.id)!;
      const folder = folders.get(document.id)!;
      const stem = stemOf(document.filename);
      setExtractProgress(`${index + 1}/${extractCandidates.length}`);
      // load 返回 null 表示该运行没有这项产物（未路由/失败等），跳过不算失败
      const files: { name: string; load: () => Promise<string | Uint8Array<ArrayBuffer> | null> }[] = [
        {
          name: fitFileName(folder, safeName(document.filename)),
          load: async () => {
            const response = await fetch(documentsApi.fileUrl(document.id));
            if (!response.ok) throw new Error(`PDF ${response.status}`);
            return new Uint8Array(await response.arrayBuffer());
          }
        },
        {
          name: fitFileName(folder, `${stem}.md`),
          load: async () => (await orMissing(runsApi.ocr(run.id)))?.markdown ?? null
        },
        {
          name: fitFileName(folder, `${stem}.json`),
          // 与结果页「JSON」视图一致
          load: async () => {
            const [result, records] = await Promise.all([
              runsApi.result(run.id),
              orMissing(runsApi.records(run.id))
            ]);
            if (!result.result && !records) return null;
            return JSON.stringify(
              { result: result.result ?? null, records: records?.records ?? [] },
              null,
              2
            );
          }
        }
      ];
      try {
        const dir = root ? await root.getDirectoryHandle(folder, { create: true }) : null;
        for (const file of files) {
          if (dir && (await fileExists(dir, file.name))) {
            skipped += 1;
            continue;
          }
          const content = await file.load();
          if (content === null) {
            missing += 1;
            continue;
          }
          if (dir) {
            const writable = await (await dir.getFileHandle(file.name, { create: true })).createWritable();
            await writable.write(content);
            await writable.close();
          } else {
            zipFiles.push({ name: `${folder}/${file.name}`, content });
          }
          written += 1;
        }
      } catch {
        failed += 1;
      }
    }
    setExtractProgress("");
    setExtracting(false);
    if (!root && zipFiles.length > 0) {
      downloadBlob(createZip(zipFiles), `标准拆分提取-${fileTimestamp(at)}.zip`);
    }
    push(
      failed ? "error" : "success",
      "提取完成",
      `写入 ${written} 个文件${skipped ? `，跳过已存在 ${skipped} 个` : ""}${
        missing ? `，${missing} 个无产物（如未路由无 JSON）` : ""
      }${failed ? `，${failed} 份文档失败` : ""}`
    );
    if (!failed) setExtractOpen(false);
  }

  const filtered = useMemo(() => {
    const search = deferredKeyword.trim().toLowerCase();
    return documents.filter((document) => {
      const run = latestRunByDocument.get(document.id);
      const runStatus = run?.status ?? UNPARSED;
      if (statusFilter && runStatus !== statusFilter) return false;
      if (!search) return true;
      return (
        document.filename.toLowerCase().includes(search) ||
        document.id.toLowerCase().includes(search)
      );
    });
  }, [documents, deferredKeyword, statusFilter, latestRunByDocument]);

  useEffect(() => {
    setPage(1);
  }, [deferredKeyword, statusFilter]);

  const pageCount = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE));
  const currentPage = Math.min(page, pageCount);
  const pageItems = filtered.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE
  );

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
              icon={<FolderDown className="h-4 w-4" />}
              disabled={documents.length === 0}
              onClick={() => setExtractOpen(true)}
            >
              提取
            </Button>
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
              variant="secondary"
              icon={<Download className="h-4 w-4" />}
              disabled={documents.length === 0}
              onClick={() => {
                setExportKeyword("");
                setExportSelected(new Set());
                setExportOpen(true);
              }}
            >
              导出
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

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <div className="relative w-72">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <Input
            value={keyword}
            onChange={(event) => setKeyword(event.target.value)}
            placeholder="搜索文件名 / 文档 ID"
            className="pl-8"
          />
        </div>
        <Select
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value)}
          className="w-40"
          aria-label="按最近运行状态筛选"
        >
          <option value="">全部状态</option>
          <option value={UNPARSED}>未解析</option>
          {STATUS_OPTIONS.map((value) => (
            <option key={value} value={value}>
              {runStatusMeta(value).label}
            </option>
          ))}
        </Select>
        <span className="text-xs text-muted-foreground">
          匹配 {filtered.length} 份
        </span>
      </div>

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
        ) : filtered.length === 0 ? (
          <div className="p-5">
            <EmptyState
              title="没有匹配的文档"
              description="调整关键词或状态筛选"
              action={
                <Button
                  variant="secondary"
                  onClick={() => {
                    setKeyword("");
                    setStatusFilter("");
                  }}
                >
                  清除筛选
                </Button>
              }
            />
          </div>
        ) : (
          <>
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeaderCell>文件</TableHeaderCell>
                  <TableHeaderCell>大小</TableHeaderCell>
                  <TableHeaderCell>上传时间</TableHeaderCell>
                  <TableHeaderCell>最近运行</TableHeaderCell>
                  <TableHeaderCell>解析时长</TableHeaderCell>
                  <TableHeaderCell className="text-right">操作</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {pageItems.map((document) => {
                  const run = latestRunByDocument.get(document.id);
                  const meta = run ? runStatusMeta(run.status) : null;
                  const terminal = run ? RUN_TERMINAL.has(run.status) : false;
                  const reviewable = run ? REVIEWABLE.has(run.status) : false;
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
                      <TableCell className="text-muted-foreground">
                        {run ? (
                          run.finished_at ? (
                            <span title={`${formatDateTime(run.started_at ?? run.created_at)} 至 ${formatDateTime(run.finished_at)}`}>
                              {formatDuration(
                                new Date(run.finished_at).getTime() -
                                  new Date(run.started_at ?? run.created_at).getTime()
                              )}
                            </span>
                          ) : (
                            <span className="text-xs">解析中</span>
                          )
                        ) : (
                          "—"
                        )}
                      </TableCell>
                      <TableCell>
                        <div className="flex items-center justify-end gap-1.5">
                          {!run ? (
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
                          ) : !terminal ? (
                            <Button size="sm" variant="secondary" disabled>
                              解析中
                            </Button>
                          ) : (
                            <>
                              {reviewable ? (
                                <Button
                                  size="sm"
                                  icon={<ShieldCheck className="h-3.5 w-3.5" />}
                                  onClick={() =>
                                    navigate(`/documents/${document.id}?run=${run.id}`)
                                  }
                                >
                                  审核
                                </Button>
                              ) : null}
                              <Button
                                size="sm"
                                variant="secondary"
                                onClick={() => runMutation.mutate(document.id)}
                                loading={
                                  runMutation.isPending &&
                                  runMutation.variables === document.id
                                }
                              >
                                重新解析
                              </Button>
                            </>
                          )}
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
            <Pagination
              page={currentPage}
              pageCount={pageCount}
              total={filtered.length}
              pageSize={PAGE_SIZE}
              onPageChange={setPage}
            />
          </>
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

      <Dialog
        open={extractOpen}
        title="提取解析结果"
        description="每份文档一个文件夹（按上传先后编号 1、2、3…），内含 PDF 原件、OCR Markdown、抽取 JSON，文件保留原名；按文档最近一次运行的状态筛选，没有的产物（如未路由无 JSON）不生成"
        onClose={() => {
          if (!extracting) setExtractOpen(false);
        }}
        footer={
          <>
            <Button
              variant="secondary"
              disabled={extracting}
              onClick={() => setExtractOpen(false)}
            >
              取消
            </Button>
            <Button
              loading={extracting}
              disabled={extractCandidates.length === 0}
              onClick={() => void runExtract()}
            >
              {directoryPicker() ? "选择文件夹并提取" : "打包下载"}（{extractCandidates.length} 份）
              {extractProgress ? ` ${extractProgress}` : ""}
            </Button>
          </>
        }
      >
        <div className="space-y-3 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-muted-foreground">上传时间</span>
            <Input
              type="datetime-local"
              value={extractFrom}
              onChange={(event) => setExtractFrom(event.target.value)}
              className="w-52"
            />
            <span className="text-muted-foreground">至</span>
            <Input
              type="datetime-local"
              value={extractTo}
              onChange={(event) => setExtractTo(event.target.value)}
              className="w-52"
            />
            <span className="ml-auto text-xs text-muted-foreground">
              符合条件 {extractCandidates.length} 份（留空表示不限）
            </span>
          </div>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5">
            <span className="text-muted-foreground">运行状态</span>
            {EXTRACT_STATUSES.map((status) => (
              <label key={status} className="flex cursor-pointer items-center gap-1.5">
                <input
                  type="checkbox"
                  className="h-4 w-4 rounded border-border accent-emerald-600"
                  checked={extractStatuses.has(status)}
                  disabled={extracting}
                  onChange={() => toggleExtractStatus(status)}
                />
                {runStatusMeta(status).label}
                <span className="text-xs text-muted-foreground">
                  {extractStatusCounts.get(status) ?? 0}
                </span>
              </label>
            ))}
          </div>
          {directoryPicker() ? (
            <p className="text-xs text-muted-foreground">
              点击后选择本机文件夹，文件直接写入；文件夹内已存在的同名文件会自动跳过。
            </p>
          ) : (
            <p className="text-xs text-muted-foreground">
              当前浏览器不支持直接写入本机文件夹（仅 HTTPS 地址可用），将打包为 ZIP 下载，解压到目标文件夹时选择“跳过”重复文件。
              如需直接写入文件夹：在 Chrome/Edge 打开 chrome://flags/#unsafely-treat-insecure-origin-as-secure，
              填入 {window.location.origin} 并启用，重启浏览器后生效。
            </p>
          )}
        </div>
      </Dialog>

      <Dialog
        open={exportOpen}
        title="批量导出文档"
        description="选择文档后，每个文档生成一份独立 CSV，并打包为 ZIP 下载"
        onClose={() => {
          if (!exporting) setExportOpen(false);
        }}
        footer={
          <>
            <Button
              variant="secondary"
              disabled={exporting}
              onClick={() => setExportOpen(false)}
            >
              取消
            </Button>
            <Button
              loading={exporting}
              disabled={exportSelected.size === 0}
              onClick={() => void runBatchExport()}
            >
              导出 ZIP（{exportSelected.size} 份）
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2">
            <Input
              value={exportKeyword}
              onChange={(event) => setExportKeyword(event.target.value)}
              placeholder="搜索文件名 / 文档 ID"
              className="w-64"
            />
            <Button
              size="sm"
              variant="secondary"
              disabled={exporting}
              onClick={toggleAllExport}
            >
              全选当前
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={exporting}
              onClick={() => setExportSelected(new Set())}
            >
              清空
            </Button>
            <span className="ml-auto text-xs text-muted-foreground">
              已选 {exportSelected.size} 份
            </span>
          </div>
          <div className="max-h-80 overflow-auto rounded-lg border border-border">
            {exportCandidates.length === 0 ? (
              <p className="px-3 py-6 text-center text-xs text-muted-foreground">
                没有匹配的文档
              </p>
            ) : (
              exportCandidates.map((document) => {
                const run = latestRunByDocument.get(document.id);
                const meta = run ? runStatusMeta(run.status) : null;
                const disabled = !run || !RUN_TERMINAL.has(run.status);
                const hint = disabled
                  ? run
                    ? "解析未完成"
                    : "未解析"
                  : meta?.label ?? "";
                return (
                  <label
                    key={document.id}
                    className={`flex items-center gap-3 border-b border-border px-3 py-2 text-sm last:border-b-0 ${
                      disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer hover:bg-muted/50"
                    }`}
                  >
                    <input
                      type="checkbox"
                      className="h-4 w-4 rounded border-border accent-emerald-600"
                      checked={exportSelected.has(document.id)}
                      disabled={disabled || exporting}
                      onChange={() => toggleExportSelected(document.id)}
                    />
                    <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <span className="min-w-0 flex-1">
                      <span
                        className="block truncate font-medium"
                        title={document.filename}
                      >
                        {document.filename}
                      </span>
                      <span className="block text-[11px] text-muted-foreground">
                        {hint}
                        {disabled ? "" : " · 可导出"}
                      </span>
                    </span>
                  </label>
                );
              })
            )}
          </div>
          {exporting && exportProgress ? (
            <p className="text-xs text-muted-foreground">
              正在导出 {exportProgress}，请勿关闭页面…
            </p>
          ) : null}
        </div>
      </Dialog>
    </div>
  );
}
