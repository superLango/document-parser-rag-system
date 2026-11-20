import { useQuery } from "@tanstack/react-query";
import { Download, FileWarning, MessageSquareWarning, RefreshCcw } from "lucide-react";
import { useMemo } from "react";
import { Link } from "react-router-dom";

import { documentsApi } from "../api/documents";
import { issuesApi } from "../api/issues";
import type { AbnormalDocument, IssueFeedback } from "../api/types";
import {
  Badge,
  Button,
  Card,
  EmptyState,
  PageHeader,
  Skeleton
} from "../components/ui/primitives";
import { Input } from "../components/ui/form";
import { Pagination } from "../components/ui/pagination";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow
} from "../components/ui/table";
import { Tabs } from "../components/ui/tabs";
import { folderOf } from "../lib/extract";
import { FEEDBACK_STATUS, runStatusMeta } from "../lib/status";
import { formatDateTime } from "../lib/utils";
import { useSessionState } from "../lib/useSessionState";

const PAGE_SIZE = 10;
const TABS = [
  { id: "feedback", label: "问题反馈" },
  { id: "abnormal", label: "异常文档" }
];

type TabId = "feedback" | "abnormal";

function csvCell(value: unknown): string {
  return `"${String(value ?? "").replace(/"/g, '""')}"`;
}

function downloadCsv(filename: string, headers: string[], rows: unknown[][]) {
  const lines = [
    headers.map(csvCell).join(","),
    ...rows.map((row) => row.map(csvCell).join(","))
  ];
  const blob = new Blob([`\ufeff${lines.join("\n")}`], {
    type: "text/csv;charset=utf-8"
  });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function inRange(value: string, start: string, end: string): boolean {
  if (!start && !end) return true;
  if (!value) return false;
  const time = new Date(value).getTime();
  if (Number.isNaN(time)) return false;
  if (start) {
    const from = new Date(`${start}T00:00:00`).getTime();
    if (time < from) return false;
  }
  if (end) {
    const to = new Date(`${end}T23:59:59.999`).getTime();
    if (time > to) return false;
  }
  return true;
}

function rangeLabel(start: string, end: string): string {
  if (!start && !end) return "全部";
  return `${start || "开始"}至${end || "至今"}`;
}

export default function IssuesPage() {
  const [tab, setTab] = useSessionState<TabId>("issues.tab", "feedback");
  const [feedbackPage, setFeedbackPage] = useSessionState("issues.feedbackPage", 1);
  const [abnormalPage, setAbnormalPage] = useSessionState("issues.abnormalPage", 1);
  const [feedbackStart, setFeedbackStart] = useSessionState("issues.feedbackStart", "");
  const [feedbackEnd, setFeedbackEnd] = useSessionState("issues.feedbackEnd", "");
  const [abnormalStart, setAbnormalStart] = useSessionState("issues.abnormalStart", "");
  const [abnormalEnd, setAbnormalEnd] = useSessionState("issues.abnormalEnd", "");
  const query = useQuery({
    queryKey: ["issues", "ledger"],
    queryFn: issuesApi.ledger
  });

  const documentsQuery = useQuery({
    queryKey: ["documents"],
    queryFn: documentsApi.list
  });
  // 与文档库「提取」的文件夹名同一规则（最新 LIMS task_id，手动上传为文档 ID），导出可直接对上文件夹
  const taskIdOf = useMemo(() => {
    const byId = new Map((documentsQuery.data ?? []).map((document) => [document.id, folderOf(document)]));
    return (documentId: string) => byId.get(documentId) ?? documentId;
  }, [documentsQuery.data]);

  const feedback = query.data?.feedback ?? [];
  const abnormal = query.data?.abnormal_documents ?? [];

  const filteredFeedback = useMemo(
    () =>
      feedback.filter((item) =>
        inRange(item.created_at, feedbackStart, feedbackEnd)
      ),
    [feedback, feedbackStart, feedbackEnd]
  );
  const filteredAbnormal = useMemo(
    () =>
      abnormal.filter((item) =>
        inRange(item.parsed_at, abnormalStart, abnormalEnd)
      ),
    [abnormal, abnormalStart, abnormalEnd]
  );


  const feedbackPageCount = Math.max(
    1,
    Math.ceil(filteredFeedback.length / PAGE_SIZE)
  );
  const abnormalPageCount = Math.max(
    1,
    Math.ceil(filteredAbnormal.length / PAGE_SIZE)
  );
  const feedbackItems = useMemo(() => {
    const page = Math.min(feedbackPage, feedbackPageCount);
    return filteredFeedback.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  }, [filteredFeedback, feedbackPage, feedbackPageCount]);
  const abnormalItems = useMemo(() => {
    const page = Math.min(abnormalPage, abnormalPageCount);
    return filteredAbnormal.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  }, [filteredAbnormal, abnormalPage, abnormalPageCount]);

  function exportFeedback() {
    downloadCsv(
      `问题反馈-${rangeLabel(feedbackStart, feedbackEnd)}.csv`,
      ["反馈时间", "反馈文档", "反馈内容", "问题类型", "状态", "字段", "任务ID"],
      filteredFeedback.map((item) => [
        item.created_at,
        item.document,
        item.description,
        item.category,
        item.status,
        item.measure,
        taskIdOf(item.document_id)
      ])
    );
  }

  function exportAbnormal() {
    downloadCsv(
      `异常文档-${rangeLabel(abnormalStart, abnormalEnd)}.csv`,
      ["解析时间", "文档", "状态", "错误码", "阶段", "解析版本", "任务ID"],
      filteredAbnormal.map((item) => [
        item.parsed_at,
        item.document,
        item.status,
        item.error_code,
        item.stage,
        item.parser_version,
        taskIdOf(item.document_id)
      ])
    );
  }

  return (
    <div className="animate-fade-up">
      <PageHeader
        eyebrow="质量"
        title="问题台账"
        description={`${feedback.length} 条问题反馈 · ${abnormal.length} 份异常文档`}
        actions={
          <Button
            variant="secondary"
            icon={<RefreshCcw className="h-4 w-4" />}
            loading={query.isFetching}
            onClick={() => void query.refetch()}
          >
            刷新
          </Button>
        }
      />

      <Tabs
        items={TABS.map((item) => ({
          ...item,
          badge: (
            <Badge tone={item.id === "feedback" ? "warning" : "danger"}>
              {item.id === "feedback" ? feedback.length : abnormal.length}
            </Badge>
          )
        }))}
        active={tab}
        onChange={(id) => setTab(id as TabId)}
        className="mb-4"
      />

      {query.isLoading ? (
        <Skeleton className="h-40 w-full" />
      ) : query.isError ? (
        <Card>
          <div className="p-5">
            <EmptyState title="问题台账加载失败" description={query.error.message} />
          </div>
        </Card>
      ) : tab === "feedback" ? (
        <Card>
          <div className="flex flex-wrap items-center gap-2 border-b border-border px-5 py-3">
            <MessageSquareWarning className="h-4 w-4 text-amber-600" />
            <h3 className="text-sm font-semibold">问题反馈</h3>
            <Badge tone="warning">{filteredFeedback.length} 条</Badge>
            <div className="ml-auto flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span>时间段</span>
              <Input
                type="date"
                value={feedbackStart}
                onChange={(event) => {
                  setFeedbackStart(event.target.value);
                  setFeedbackPage(1);
                }}
                className="h-8 w-36"
                aria-label="反馈开始日期"
              />
              <span>至</span>
              <Input
                type="date"
                value={feedbackEnd}
                onChange={(event) => {
                  setFeedbackEnd(event.target.value);
                  setFeedbackPage(1);
                }}
                className="h-8 w-36"
                aria-label="反馈结束日期"
              />
              <Button
                size="sm"
                icon={<Download className="h-3.5 w-3.5" />}
                disabled={filteredFeedback.length === 0 || !documentsQuery.data}
                onClick={exportFeedback}
              >
                导出
              </Button>
            </div>
          </div>
          {filteredFeedback.length === 0 ? (
            <div className="p-5">
              <EmptyState
                title={feedback.length === 0 ? "暂无问题反馈" : "该时间段没有问题反馈"}
                description={
                  feedback.length === 0
                    ? "在解析详情页点击字段或新建反馈后，会登记到这里"
                    : "调整开始/结束日期后重试"
                }
              />
            </div>
          ) : (
            <>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableHeaderCell>反馈时间</TableHeaderCell>
                    <TableHeaderCell>反馈文档</TableHeaderCell>
                    <TableHeaderCell>反馈内容</TableHeaderCell>
                    <TableHeaderCell>类型</TableHeaderCell>
                    <TableHeaderCell>状态</TableHeaderCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {feedbackItems.map((item: IssueFeedback) => {
                    const meta = FEEDBACK_STATUS[item.status] ?? {
                      label: item.status,
                      tone: "neutral" as const
                    };
                    return (
                      <TableRow key={item.id}>
                        <TableCell className="whitespace-nowrap text-muted-foreground">
                          {formatDateTime(item.created_at)}
                        </TableCell>
                        <TableCell>
                          <Link
                            to={`/documents/${item.document_id}${
                              item.run_id ? `?run=${item.run_id}` : ""
                            }`}
                            className="block max-w-[260px] truncate font-medium hover:text-primary-strong"
                            title={item.document}
                          >
                            {item.document}
                          </Link>
                        </TableCell>
                        <TableCell>
                          <span className="block max-w-[520px] whitespace-pre-wrap break-words">
                            {item.description}
                          </span>
                          {item.measure ? (
                            <span className="mt-0.5 block text-[11px] text-muted-foreground">
                              字段：{item.measure}
                            </span>
                          ) : null}
                        </TableCell>
                        <TableCell className="text-muted-foreground">
                          {item.category}
                        </TableCell>
                        <TableCell>
                          <Badge tone={meta.tone} dot>
                            {meta.label}
                          </Badge>
                        </TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
              <Pagination
                page={Math.min(feedbackPage, feedbackPageCount)}
                pageCount={feedbackPageCount}
                total={filteredFeedback.length}
                pageSize={PAGE_SIZE}
                onPageChange={setFeedbackPage}
              />
            </>
          )}
        </Card>
      ) : (
        <Card>
          <div className="flex flex-wrap items-center gap-2 border-b border-border px-5 py-3">
            <FileWarning className="h-4 w-4 text-rose-600" />
            <h3 className="text-sm font-semibold">异常文档</h3>
            <Badge tone="danger">{filteredAbnormal.length} 份</Badge>
            <div className="ml-auto flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <span>时间段</span>
              <Input
                type="date"
                value={abnormalStart}
                onChange={(event) => {
                  setAbnormalStart(event.target.value);
                  setAbnormalPage(1);
                }}
                className="h-8 w-36"
                aria-label="异常文档开始日期"
              />
              <span>至</span>
              <Input
                type="date"
                value={abnormalEnd}
                onChange={(event) => {
                  setAbnormalEnd(event.target.value);
                  setAbnormalPage(1);
                }}
                className="h-8 w-36"
                aria-label="异常文档结束日期"
              />
              <Button
                size="sm"
                icon={<Download className="h-3.5 w-3.5" />}
                disabled={filteredAbnormal.length === 0 || !documentsQuery.data}
                onClick={exportAbnormal}
              >
                导出
              </Button>
            </div>
          </div>
          {filteredAbnormal.length === 0 ? (
            <div className="p-5">
              <EmptyState
                title={abnormal.length === 0 ? "暂无异常文档" : "该时间段没有异常文档"}
                description={
                  abnormal.length === 0
                    ? "解析失败、审核未通过等文档会登记到这里"
                    : "调整开始/结束日期后重试"
                }
              />
            </div>
          ) : (
            <>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableHeaderCell>解析时间</TableHeaderCell>
                    <TableHeaderCell>文档</TableHeaderCell>
                    <TableHeaderCell>状态</TableHeaderCell>
                    <TableHeaderCell>错误码</TableHeaderCell>
                    <TableHeaderCell>阶段</TableHeaderCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {abnormalItems.map((item: AbnormalDocument) => {
                    const meta = runStatusMeta(item.status);
                    return (
                      <TableRow key={`${item.run_id}-${item.document_id}`}>
                        <TableCell className="whitespace-nowrap text-muted-foreground">
                          {item.parsed_at ? formatDateTime(item.parsed_at) : "—"}
                        </TableCell>
                        <TableCell>
                          <Link
                            to={`/documents/${item.document_id}?run=${item.run_id}`}
                            className="block max-w-[320px] truncate font-medium hover:text-primary-strong"
                            title={item.document}
                          >
                            {item.document}
                          </Link>
                        </TableCell>
                        <TableCell>
                          <Badge tone={meta.tone} dot>
                            {meta.label}
                          </Badge>
                        </TableCell>
                        <TableCell className="font-mono text-xs text-rose-700">
                          {item.error_code || "—"}
                        </TableCell>
                        <TableCell className="text-muted-foreground">{item.stage}</TableCell>
                      </TableRow>
                    );
                  })}
                </TableBody>
              </Table>
              <Pagination
                page={Math.min(abnormalPage, abnormalPageCount)}
                pageCount={abnormalPageCount}
                total={filteredAbnormal.length}
                pageSize={PAGE_SIZE}
                onPageChange={setAbnormalPage}
              />
            </>
          )}
        </Card>
      )}
    </div>
  );
}
