import type { ReviewReport, RunItem, SandboxResult } from "../../api/types";
import { Badge, Card, CardContent, CardHeader } from "../ui/primitives";
import { REVIEW_STATUS, runStatusMeta } from "../../lib/status";

export function RecipeTraceCard({
  run,
  result,
  review
}: {
  run: RunItem | null;
  result: SandboxResult | null;
  review?: ReviewReport | null;
}) {
  const recipes = result?.recipes ?? [];
  const tables = result?.tables ?? [];
  const status = review ? REVIEW_STATUS[review.status] : null;

  return (
    <Card>
      <CardHeader
        title="配方依据"
        description="命中配方、模板与审核结论"
        actions={
          status ? <Badge tone={status.tone}>{status.label}</Badge> : null
        }
      />
      <CardContent className="space-y-3">
        {recipes.length === 0 ? (
          <p className="text-sm text-muted-foreground">尚无配方命中信息。</p>
        ) : (
          recipes.map((recipe) => (
            <div
              key={`${recipe.recipe_id}-${recipe.version}`}
              className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-background-soft px-3 py-2"
            >
              <span className="text-sm font-medium">{recipe.recipe_id}</span>
              <Badge tone="success">v{recipe.version}</Badge>
              <Badge tone="info">{recipe.profile || "unknown"}</Badge>
            </div>
          ))
        )}
        <div className="grid gap-2 text-xs sm:grid-cols-2">
          <p>
            <span className="text-muted-foreground">模板：</span>
            {result?.template?.template_id
              ? `${result.template.template_id}@${result.template.version}`
              : "—"}
          </p>
          <p>
            <span className="text-muted-foreground">运行通道：</span>
            {run?.recipe_channel ?? "—"}
          </p>
          <p>
            <span className="text-muted-foreground">表数：</span>
            {result?.stats?.tables ?? tables.length}
          </p>
          <p>
            <span className="text-muted-foreground">记录数：</span>
            {result?.stats?.records ?? "—"}
          </p>
        </div>
        {run ? (
          <p className="text-[11px] text-muted-foreground">
            运行 {run.id.slice(0, 8)} · {runStatusMeta(run.status).label}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}
