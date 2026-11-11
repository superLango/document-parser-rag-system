import { useQuery } from "@tanstack/react-query";
import { BookOpen, Search } from "lucide-react";
import { useDeferredValue, useState } from "react";

import { dictionaryApi } from "../api/dictionary";
import {
  Badge,
  Button,
  Card,
  CardContent,
  EmptyState,
  PageHeader,
  Skeleton
} from "../components/ui/primitives";
import { Input } from "../components/ui/form";
import { Tabs } from "../components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeaderCell,
  TableRow
} from "../components/ui/table";

const TABS = [
  { id: "items", label: "检测项目" },
  { id: "methods", label: "试验方法" },
  { id: "families", label: "分类概览" }
];

const FAMILY_LABELS: Record<string, string> = {
  chemical_composition: "化学成分",
  tensile: "拉伸",
  impact: "冲击",
  hardness: "硬度",
  hardenability: "淬透性",
  creep: "蠕变",
  stress_rupture: "持久",
  metallography: "金相",
  fracture_toughness: "断裂韧性",
  fatigue: "疲劳",
  bend: "弯曲",
  shear: "剪切",
  upset: "顶锻",
  corrosion: "腐蚀",
  ndt: "无损检测",
  dimension: "尺寸",
  surface: "表面",
  marking: "标记",
  unclassified: "未分类"
};

function familyLabel(name: string): string {
  return FAMILY_LABELS[name] ?? name;
}

export default function DictionaryPage() {
  const [tab, setTab] = useState("items");
  const [keyword, setKeyword] = useState("");
  const [family, setFamily] = useState("");
  const deferredKeyword = useDeferredValue(keyword);
  const type = tab === "items" ? "item" : tab === "methods" ? "method" : "";

  const query = useQuery({
    queryKey: ["dictionary", type, deferredKeyword, tab === "families" ? "" : family],
    queryFn: () =>
      dictionaryApi.query({
        type,
        q: deferredKeyword || undefined,
        family: tab === "families" ? undefined : family || undefined
      })
  });

  const entries = query.data?.entries ?? [];
  const families = Object.entries(query.data?.families ?? {}).sort(
    (a, b) => b[1] - a[1]
  );

  return (
    <div className="animate-fade-up">
      <PageHeader
        eyebrow="数据"
        title="业务词典"
        description={`${query.data?.version ?? "—"} · 共 ${query.data?.total ?? 0} 条`}
      />

      <Card>
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-5 py-3">
          <Tabs
            items={TABS}
            active={tab}
            onChange={(value) => {
              setTab(value);
              setFamily("");
            }}
            className="border-b-0"
          />
          <div className="relative w-64">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={keyword}
              onChange={(event) => setKeyword(event.target.value)}
              placeholder="搜索编码 / 名称 / 别名"
              className="pl-8"
            />
          </div>
        </div>

        {tab !== "families" && family ? (
          <div className="flex items-center gap-2 border-b border-border bg-background-soft px-5 py-2 text-xs">
            <span className="text-muted-foreground">分类筛选：</span>
            <Badge tone="info">{familyLabel(family)}</Badge>
            <Button size="sm" variant="ghost" onClick={() => setFamily("")}>
              清除
            </Button>
          </div>
        ) : null}

        {query.isLoading ? (
          <div className="space-y-3 p-5">
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-full" />
            <Skeleton className="h-10 w-2/3" />
          </div>
        ) : query.isError ? (
          <div className="p-5">
            <EmptyState
              title="词典加载失败"
              description={query.error.message}
              action={<Button variant="secondary" onClick={() => void query.refetch()}>重试</Button>}
            />
          </div>
        ) : tab === "families" ? (
          <CardContent className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {families.map(([name, count]) => (
              <button
                key={name}
                type="button"
                className="flex items-center justify-between rounded-xl border border-border bg-background-soft px-4 py-3 text-left transition-colors hover:border-primary/40 hover:bg-white"
                onClick={() => {
                  setFamily(name);
                  setTab("items");
                }}
              >
                <span className="text-sm font-medium">{familyLabel(name)}</span>
                <Badge tone="success">{count}</Badge>
              </button>
            ))}
            {families.length === 0 ? (
              <div className="sm:col-span-2 lg:col-span-3">
                <EmptyState title="暂无分类" />
              </div>
            ) : null}
          </CardContent>
        ) : entries.length === 0 ? (
          <div className="p-5">
            <EmptyState
              title="没有匹配的词典条目"
              description="尝试更换关键词或清除分类筛选"
              action={<BookOpen className="mx-auto h-8 w-8 text-muted-foreground" />}
            />
          </div>
        ) : (
          <Table>
            <TableHead>
              <TableRow>
                <TableHeaderCell>业务编码</TableHeaderCell>
                <TableHeaderCell>名称</TableHeaderCell>
                <TableHeaderCell>分类</TableHeaderCell>
                <TableHeaderCell>别名</TableHeaderCell>
                <TableHeaderCell>状态</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {entries.map((entry) => (
                <TableRow key={`${entry.type}-${entry.business_code}`}>
                  <TableCell className="font-mono text-xs">{entry.business_code}</TableCell>
                  <TableCell className="font-medium">{entry.business_name}</TableCell>
                  <TableCell>
                    {entry.family ? (
                      <Badge tone="info">{familyLabel(entry.family)}</Badge>
                    ) : (
                      "—"
                    )}
                  </TableCell>
                  <TableCell>
                    <div className="flex max-w-md flex-wrap gap-1">
                      {(entry.aliases ?? []).slice(0, 6).map((alias) => (
                        <span
                          key={alias}
                          className="rounded bg-muted px-1.5 py-0.5 text-[11px] text-slate-600"
                        >
                          {alias}
                        </span>
                      ))}
                      {(entry.aliases ?? []).length > 6 ? (
                        <span className="text-[11px] text-muted-foreground">
                          +{(entry.aliases ?? []).length - 6}
                        </span>
                      ) : null}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge tone={entry.status === "active" ? "success" : "neutral"}>
                      {entry.status ?? "—"}
                    </Badge>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </Card>
    </div>
  );
}
