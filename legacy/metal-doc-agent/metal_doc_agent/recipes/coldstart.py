"""Cold-start operations: long-tail clustering, T1/T2/T3 triage, dashboard (M2.5.4).

Tables that do not reach the production queue are grouped by signature
similarity so each long-tail family has one representative table to author
against. Tiers follow the plan:

* T1 — an active recipe already matches; production.
* T2 — same profile as an active recipe with enough header overlap; parameterise
  bindings/headers instead of writing a new recipe.
* T3 — no structurally close recipe; offline authoring + human review.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from ..contracts import Recipe, TableGrid
from .routing import RouteDecision, decide_route
from .signature import build_signature, signature_tokens, token_overlap, token_similarity

Tier = Literal["T1", "T2", "T3"]

CLUSTER_THRESHOLD = 0.6
G2_TARGETS = {"hit_rate": 0.80, "novelty_rate": 0.20, "t3_ratio": 0.05}


@dataclass(frozen=True)
class ColdTable:
    doc_id: str
    table_id: str
    profile: str
    tier: Tier
    queue: str
    recipe_id: str | None
    overlap: float
    tokens: list[str]
    n_cols: int
    orientation: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class ColdCluster:
    cluster_id: str
    profile: str
    tier: Tier
    documents: int
    tables: int
    representative_doc: str
    representative_table: str
    suggested_recipe: str | None
    tokens: list[str]
    members: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)


def triage_table(
    doc_id: str, table: TableGrid, recipes: list[Recipe]
) -> ColdTable:
    decision = decide_route(table, recipes)
    profile_recipes = [
        item for item in recipes if item.status == "active" and item.signature.profile == table.profile
    ]
    tokens = signature_tokens(table)
    best_recipe: Recipe | None = None
    best_overlap = 0.0
    if profile_recipes:
        best_recipe = max(
            profile_recipes,
            key=lambda recipe: (
                token_overlap(tokens, recipe.signature.tokens),
                recipe.recipe_id,
            ),
        )
        best_overlap = token_overlap(tokens, best_recipe.signature.tokens)
    if decision.queue == "production" and decision.recipe_id:
        tier: Tier = "T1"
    elif best_recipe is not None:
        # The profile has an active recipe family: parameterise it instead of
        # authoring from scratch. ``overlap`` ranks which recipe to extend.
        tier = "T2"
    else:
        tier = "T3"
    return ColdTable(
        doc_id=doc_id,
        table_id=table.table_id,
        profile=table.profile,
        tier=tier,
        queue=decision.queue,
        recipe_id=decision.recipe_id or (best_recipe.recipe_id if best_recipe else None),
        overlap=round(best_overlap, 4),
        tokens=tokens,
        n_cols=table.n_cols,
        orientation=table.orientation,
    )


def cluster_similarity(left: ColdTable, right: ColdTable) -> float:
    if left.profile != right.profile:
        return 0.0
    jaccard = token_similarity(left.tokens, right.tokens)
    if left.n_cols == right.n_cols:
        cols = 1.0
    else:
        cols = max(0.0, 1.0 - abs(left.n_cols - right.n_cols) / max(left.n_cols, right.n_cols, 1))
    orientation = 1.0 if left.orientation == right.orientation else 0.0
    return round(0.7 * jaccard + 0.2 * cols + 0.1 * orientation, 4)


def cluster_long_tail(
    items: list[ColdTable], *, threshold: float = CLUSTER_THRESHOLD
) -> list[ColdCluster]:
    """Greedy leader clustering over non-T1 tables; deterministic by sorted ids."""
    pending = sorted(
        (item for item in items if item.tier != "T1"),
        key=lambda item: (item.profile, item.doc_id, item.table_id),
    )
    groups: list[list[ColdTable]] = []
    for item in pending:
        best_index = -1
        best_score = 0.0
        for index, group in enumerate(groups):
            if group[0].profile != item.profile:
                continue
            score = cluster_similarity(item, group[0])
            if score >= threshold and score > best_score:
                best_index, best_score = index, score
        if best_index >= 0:
            groups[best_index].append(item)
        else:
            groups.append([item])

    clusters: list[ColdCluster] = []
    ordered = sorted(groups, key=lambda group: (group[0].profile, -len(group), group[0].doc_id))
    for index, group in enumerate(ordered, start=1):
        tier = "T2" if any(item.tier == "T2" for item in group) else "T3"
        representative = max(
            group,
            key=lambda item: (len(item.tokens), -item.n_cols, item.doc_id),
        )
        clusters.append(
            ColdCluster(
                cluster_id=f"cluster_{group[0].profile}_{index:02d}",
                profile=group[0].profile,
                tier=tier,
                documents=len({item.doc_id for item in group}),
                tables=len(group),
                representative_doc=representative.doc_id,
                representative_table=representative.table_id,
                suggested_recipe=representative.recipe_id,
                tokens=representative.tokens[:20],
                members=[
                    {"doc_id": item.doc_id, "table_id": item.table_id, "tier": item.tier}
                    for item in group
                ],
            )
        )
    return clusters


def coldstart_metrics(
    documents: int,
    items: list[ColdTable],
    clusters: list[ColdCluster],
    *,
    queue_stats: dict[str, int] | None = None,
    candidate_files: int = 0,
    promoted_candidates: int = 0,
    admin_tables: int = 0,
) -> dict:
    total = len(items)
    production = [item for item in items if item.queue == "production"]
    novel = [item for item in items if item.recipe_id is None or item.tier == "T3"]
    tiers = {
        "T1": sum(1 for item in items if item.tier == "T1"),
        "T2": sum(1 for item in items if item.tier == "T2"),
        "T3": sum(1 for item in items if item.tier == "T3"),
    }
    production_docs = len({item.doc_id for item in production})
    metrics = {
        "documents": documents,
        "tables": total,
        "tables_total": total + admin_tables,
        "admin_tables": admin_tables,
        "production_tables": len(production),
        "explore_tables": sum(1 for item in items if item.queue == "explore"),
        "human_tables": sum(1 for item in items if item.queue == "human"),
        "hit_rate": round(production_docs / documents, 4) if documents else 0.0,
        "novelty_rate": round(len(novel) / total, 4) if total else 0.0,
        "t3_ratio": round(tiers["T3"] / total, 4) if total else 0.0,
        "tiers": tiers,
        "clusters": len(clusters),
        "t3_clusters": sum(1 for cluster in clusters if cluster.tier == "T3"),
        "backlog": dict(queue_stats or {}),
        "conversion": {
            "candidates": candidate_files,
            "promoted": promoted_candidates,
            "rate": round(promoted_candidates / candidate_files, 4) if candidate_files else 0.0,
        },
        "targets": dict(G2_TARGETS),
    }
    metrics["gaps"] = _target_gaps(metrics)
    return metrics


def _target_gaps(metrics: dict) -> list[str]:
    gaps: list[str] = []
    if metrics["hit_rate"] < G2_TARGETS["hit_rate"]:
        gaps.append(
            f"hit_rate {metrics['hit_rate']:.4f} < target {G2_TARGETS['hit_rate']}"
        )
    if metrics["novelty_rate"] > G2_TARGETS["novelty_rate"]:
        gaps.append(
            f"novelty_rate {metrics['novelty_rate']:.4f} > target {G2_TARGETS['novelty_rate']}"
        )
    if metrics["t3_ratio"] > G2_TARGETS["t3_ratio"]:
        gaps.append(
            f"t3_ratio {metrics['t3_ratio']:.4f} > target {G2_TARGETS['t3_ratio']}"
        )
    return gaps


def build_report(
    tables: list[tuple[str, TableGrid]],
    recipes: list[Recipe],
    *,
    documents: int | None = None,
    queue_stats: dict[str, int] | None = None,
    candidate_files: int = 0,
    promoted_candidates: int = 0,
) -> dict:
    triaged = [triage_table(doc_id, table, recipes) for doc_id, table in tables]
    # ``admin`` covers signature blocks, revision history, document/product lists:
    # they are not extraction targets, so they must not inflate novelty/T3.
    items = [item for item in triaged if item.profile != "admin"]
    admin_tables = len(triaged) - len(items)
    clusters = cluster_long_tail(items)
    in_scope_docs = len({item.doc_id for item in items}) or (
        documents if documents is not None else len({doc for doc, _ in tables})
    )
    metrics = coldstart_metrics(
        in_scope_docs,
        items,
        clusters,
        queue_stats=queue_stats,
        candidate_files=candidate_files,
        promoted_candidates=promoted_candidates,
        admin_tables=admin_tables,
    )
    by_profile: dict[str, dict[str, int]] = {}
    for item in triaged:
        stats = by_profile.setdefault(
            item.profile, {"tables": 0, "T1": 0, "T2": 0, "T3": 0}
        )
        stats["tables"] += 1
        stats[item.tier] += 1
    return {
        "metrics": metrics,
        "by_profile": by_profile,
        "clusters": [cluster.to_dict() for cluster in clusters],
        "tables": [item.to_dict() for item in items],
    }


def render_markdown(report: dict, *, top: int = 20) -> str:
    metrics = report["metrics"]
    lines = [
        "# 冷启动运营报告（M2.5.4）",
        "",
        "| 指标 | 值 | 目标 | 状态 |",
        "|---|---|---|---|",
    ]
    for key, target in (
        ("hit_rate", "≥0.80"),
        ("novelty_rate", "<0.20"),
        ("t3_ratio", "<0.05"),
    ):
        value = metrics[key]
        ok = (
            value >= G2_TARGETS[key]
            if key in {"hit_rate"}
            else value <= G2_TARGETS[key]
        )
        lines.append(f"| {key} | {value:.4f} | {target} | {'OK' if ok else 'GAP'} |")
    lines.extend(
        [
            f"| tables | {metrics['tables']} | - | production {metrics['production_tables']} / "
            f"explore {metrics['explore_tables']} / human {metrics['human_tables']} |",
            f"| clusters | {metrics['clusters']} | - | T3 clusters {metrics['t3_clusters']} |",
            f"| tiers | T1 {metrics['tiers']['T1']} / T2 {metrics['tiers']['T2']} / "
            f"T3 {metrics['tiers']['T3']} | - | - |",
            f"| backlog | {json_backlog(metrics['backlog'])} | 有界 | - |",
            f"| conversion | {metrics['conversion']['promoted']}/{metrics['conversion']['candidates']} "
            f"({metrics['conversion']['rate']:.4f}) | 持续 > 新格式率 | - |",
            "",
            "## 表型分布",
            "",
            "| 表型 | 表 | T1 | T2 | T3 |",
            "|---|---|---|---|---|",
        ]
    )
    for profile, stats in sorted(report["by_profile"].items()):
        lines.append(
            f"| {profile} | {stats['tables']} | {stats['T1']} | {stats['T2']} | {stats['T3']} |"
        )
    lines.extend(
        [
            "",
            "## 长尾聚类（前 {}）".format(top),
            "",
            "| 聚类 | 表型 | 层 | 文档 | 表 | 代表 | 建议配方 |",
            "|---|---|---|---|---|---|---|",
        ]
    )
    for cluster in report["clusters"][:top]:
        lines.append(
            f"| {cluster['cluster_id']} | {cluster['profile']} | {cluster['tier']} | "
            f"{cluster['documents']} | {cluster['tables']} | "
            f"{cluster['representative_doc']}/{cluster['representative_table']} | "
            f"{cluster['suggested_recipe'] or '-'} |"
        )
    lines.append("")
    return "\n".join(lines)


def json_backlog(backlog: dict) -> str:
    if not backlog:
        return "0/0/0"
    return "/".join(str(backlog.get(lane, 0)) for lane in ("production", "explore", "human"))
