import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronRight, RefreshCcw, RotateCcw } from "lucide-react";
import { useState } from "react";

import { recipesApi } from "../api/recipes";
import type { RecipeDetail } from "../api/types";
import {
  Badge,
  Button,
  Card,
  CardContent,
  EmptyState,
  PageHeader,
  Skeleton
} from "../components/ui/primitives";
import { Dialog } from "../components/ui/dialog";
import { Field, Input, Select } from "../components/ui/form";
import { useToast } from "../components/ui/toast";
import { CHANNEL_LABELS } from "../lib/status";

const CHANNEL_TONE: Record<string, "success" | "info" | "warning" | "neutral"> = {
  stable: "success",
  candidate: "info",
  shadow: "warning",
  deprecated: "neutral"
};

export default function RecipesPage() {
  const { push } = useToast();
  const queryClient = useQueryClient();
  const [expanded, setExpanded] = useState<string | null>(null);
  const [rollbackTarget, setRollbackTarget] = useState<RecipeDetail | null>(null);
  const [reason, setReason] = useState("");
  const [channel, setChannel] = useState("stable");

  const query = useQuery({
    queryKey: ["recipes"],
    queryFn: recipesApi.list
  });

  const rollbackMutation = useMutation({
    mutationFn: () => recipesApi.rollback(rollbackTarget!.recipe_id, channel, reason),
    onSuccess: (result) => {
      push("success", "已回滚", `${result.recipe_id} → ${result.version}`);
      setRollbackTarget(null);
      setReason("");
      void queryClient.invalidateQueries({ queryKey: ["recipes"] });
    },
    onError: (error: Error) => push("error", "回滚失败", error.message)
  });

  const recipes = query.data ?? [];

  return (
    <div className="animate-fade-up">
      <PageHeader
        eyebrow="版本"
        title="配方版本"
        description={`${recipes.length} 个配方 · stable 通道为线上解析版本`}
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

      {query.isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      ) : query.isError ? (
        <EmptyState
          title="配方加载失败"
          description={query.error.message}
          action={<Button variant="secondary" onClick={() => void query.refetch()}>重试</Button>}
        />
      ) : recipes.length === 0 ? (
        <EmptyState title="暂无配方" description="配方注册中心尚未发布任何版本" />
      ) : (
        <div className="space-y-3">
          {recipes.map((recipe) => {
            const open = expanded === recipe.recipe_id;
            return (
              <Card key={recipe.recipe_id}>
                <button
                  type="button"
                  className="flex w-full flex-wrap items-center gap-3 px-5 py-4 text-left"
                  onClick={() => setExpanded(open ? null : recipe.recipe_id)}
                  aria-expanded={open}
                >
                  {open ? (
                    <ChevronDown className="h-4 w-4 text-muted-foreground" />
                  ) : (
                    <ChevronRight className="h-4 w-4 text-muted-foreground" />
                  )}
                  <span className="text-sm font-semibold">{recipe.recipe_id}</span>
                  {Object.entries(recipe.channels).map(([name, version]) => (
                    <Badge key={name} tone={CHANNEL_TONE[name] ?? "neutral"} dot>
                      {CHANNEL_LABELS[name] ?? name} @{version}
                    </Badge>
                  ))}
                  <span className="ml-auto text-xs text-muted-foreground">
                    {recipe.versions.length} 个版本
                  </span>
                </button>
                {open ? (
                  <CardContent className="border-t border-border pt-3">
                    <div className="mb-3 flex items-center justify-end">
                      <Button
                        size="sm"
                        variant="secondary"
                        icon={<RotateCcw className="h-3.5 w-3.5" />}
                        onClick={() => {
                          setRollbackTarget(recipe);
                          setChannel(recipe.channels.stable ? "stable" : "candidate");
                        }}
                      >
                        回滚
                      </Button>
                    </div>
                    <div className="divide-y divide-border rounded-lg border border-border">
                      {recipe.versions.map((version) => (
                        <div
                          key={version.version}
                          className="flex flex-wrap items-center gap-3 px-4 py-2.5 text-sm"
                        >
                          <span className="font-mono">v{version.version}</span>
                          {version.channel ? (
                            <Badge tone={CHANNEL_TONE[version.channel] ?? "neutral"}>
                              {CHANNEL_LABELS[version.channel] ?? version.channel}
                            </Badge>
                          ) : (
                            <Badge tone="neutral">历史</Badge>
                          )}
                          <span className="truncate font-mono text-[11px] text-muted-foreground">
                            {version.digest}
                          </span>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                ) : null}
              </Card>
            );
          })}
        </div>
      )}

      <Dialog
        open={rollbackTarget !== null}
        title="回滚配方"
        description="将通道指针切到该通道的上一个版本；操作写入 registry history"
        onClose={() => setRollbackTarget(null)}
        footer={
          <>
            <Button variant="secondary" onClick={() => setRollbackTarget(null)}>
              取消
            </Button>
            <Button
              variant="danger"
              loading={rollbackMutation.isPending}
              onClick={() => rollbackMutation.mutate()}
            >
              确认回滚
            </Button>
          </>
        }
      >
        <div className="space-y-3">
          <p className="text-sm">
            配方：<span className="font-medium">{rollbackTarget?.recipe_id}</span>
          </p>
          <Field label="通道">
            <Select value={channel} onChange={(event) => setChannel(event.target.value)}>
              {Object.keys(rollbackTarget?.channels ?? {}).map((name) => (
                <option key={name} value={name}>
                  {name} @ {rollbackTarget?.channels[name]}
                </option>
              ))}
              {Object.keys(rollbackTarget?.channels ?? {}).length === 0 ? (
                <option value="stable">stable</option>
              ) : null}
            </Select>
          </Field>
          <Field label="原因" hint="写入审计备注">
            <Input
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              placeholder="回滚到上一稳定版本"
            />
          </Field>
          {rollbackTarget?.channels.stable ? (
            <p className="text-[11px] text-muted-foreground">
              当前 stable：{rollbackTarget.channels.stable}
            </p>
          ) : null}
        </div>
      </Dialog>
    </div>
  );
}
