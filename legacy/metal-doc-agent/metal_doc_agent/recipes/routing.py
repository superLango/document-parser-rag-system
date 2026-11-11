"""Routing decisions for M2.5.2: production / explore / human.

Thresholds are calibrated on the 20-doc replay
(``eval/recipes/binding-coverage.json``): per-document best signature score
reaches ≥0.75 for 17/20 docs (85%), ≥0.60 for 20/20. The legacy 0.9 "exact"
threshold was unreachable because generic recipes caps out around 0.89.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

from ..contracts import Recipe, TableGrid
from .signature import signature_score, signature_tokens, token_overlap

Queue = Literal["production", "explore", "human"]

PRODUCTION_SCORE = 0.75
EXACT_SCORE = 0.85
EXPLORE_SCORE = 0.60
AMBIGUITY_DELTA = 0.05
COVERAGE_FLOOR = 0.6
COVERAGE_DELTA = 0.25
MAX_COLS = 40
MAX_BLOCKS = 2


@dataclass(frozen=True)
class RouteDecision:
    queue: Queue
    status: str
    recipe_id: str | None
    score: float
    confidence: float
    reasons: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def decide_route(
    table: TableGrid,
    recipes: list[Recipe],
    *,
    history: dict[str, float] | None = None,
    force_human: bool = False,
) -> RouteDecision:
    """Pick a queue plus an explainable reason list.

    ``history`` maps recipe_id → historical success rate (0–1) and nudges
    confidence; it never overrides an ambiguity/size veto.
    """
    if force_human:
        return RouteDecision("human", "unknown", None, 0.0, 0.0, ["forced_human"])

    ranked = _rank(table, recipes)
    if not ranked:
        return RouteDecision(
            "explore",
            "unknown",
            None,
            0.0,
            0.0,
            [f"no_recipe_for_profile:{table.profile}"],
        )

    best_recipe, best_score, best_rank, best_coverage = ranked[0]
    reasons: list[str] = [f"signature_score={best_score:.3f}"]
    confidence = best_score
    if history and best_recipe.recipe_id in history:
        success = max(0.0, min(1.0, history[best_recipe.recipe_id]))
        confidence = round(0.8 * best_score + 0.2 * success, 4)
        reasons.append(f"history_success={success:.3f}")

    if table.n_cols > MAX_COLS or len(table.blocks) > MAX_BLOCKS:
        reasons.append("risky_table_size")
        return RouteDecision(
            "human", _status(best_score), best_recipe.recipe_id, best_score, confidence, reasons
        )
    if len(ranked) > 1 and best_rank - ranked[1][2] <= AMBIGUITY_DELTA:
        # Same-family recipes often tie on signature score (mechanical vs
        # hardness). Prefer the recipe whose planted tokens match the table's
        # own headers; otherwise keep the human review.
        second_coverage = ranked[1][3]
        tokens = signature_tokens(table)
        mech_hits, hard_hits = _family_hint(tokens)
        disambiguated = ""
        if (
            best_coverage >= COVERAGE_FLOOR
            and best_coverage - second_coverage >= COVERAGE_DELTA
        ):
            disambiguated = f"coverage={best_coverage:.2f}"
        elif (
            best_recipe.recipe_id == "mechanical_properties_v1"
            and mech_hits >= 2
            and mech_hits - hard_hits >= 1
        ):
            disambiguated = f"mech_tokens={mech_hits},hardness_tokens={hard_hits}"
        if disambiguated:
            reasons.append(f"disambiguated_by_header:{best_recipe.recipe_id}({disambiguated})")
        else:
            reasons.append(
                f"ambiguous_top2:{best_recipe.recipe_id},{ranked[1][0].recipe_id}"
            )
            return RouteDecision(
                "human", _status(best_score), best_recipe.recipe_id, best_score, confidence, reasons
            )
    if confidence >= PRODUCTION_SCORE:
        return RouteDecision(
            "production", _status(best_score), best_recipe.recipe_id, best_score, confidence, reasons
        )
    if best_score >= EXPLORE_SCORE:
        reasons.append("low_confidence")
    else:
        reasons.append("below_explore_threshold")
    return RouteDecision(
        "explore", _status(best_score), best_recipe.recipe_id, best_score, confidence, reasons
    )


def _rank(table: TableGrid, recipes: list[Recipe]) -> list[tuple[Recipe, float, float, float]]:
    tokens = signature_tokens(table)
    candidates: list[tuple[Recipe, float, float, float]] = []
    for recipe in recipes:
        if recipe.status != "active" or recipe.signature.profile != table.profile:
            continue
        score = signature_score(table, recipe.signature)
        if score <= 0:
            continue
        # Overlap breaks ties between same-profile recipes (hardness vs tensile).
        rank = round(0.9 * score + 0.1 * token_overlap(tokens, recipe.signature.tokens), 4)
        coverage = _table_coverage(tokens, recipe.signature.tokens)
        candidates.append((recipe, score, rank, coverage))
    candidates.sort(key=lambda item: (-item[2], item[0].recipe_id))
    return candidates


def _table_coverage(tokens: list[str], recipe_tokens: list[str]) -> float:
    """Fraction of the table's own header tokens present in the recipe."""
    if not tokens:
        return 0.0
    recipe_set = set(recipe_tokens)
    return round(sum(1 for token in tokens if token in recipe_set) / len(tokens), 4)


MECH_HINT = (
    "rm", "rp0.2", "rel", "rcl", "ku2", "kv2", "a%", "z%", "拉伸", "屈服",
    "伸长", "收缩", "冲击", "断后",
)
HARDNESS_HINT = (
    "hrc", "hrb", "hv", "hbw", "hb", "布氏", "洛氏", "维氏", "硬度",
)


def _family_hint(tokens: list[str]) -> tuple[int, int]:
    """Count mechanical vs hardness evidence in the table's own tokens."""
    mechanical = sum(1 for token in tokens if _has_hint(token, MECH_HINT))
    hardness = sum(1 for token in tokens if _has_hint(token, HARDNESS_HINT))
    return mechanical, hardness


def _has_hint(token: str, markers: tuple[str, ...]) -> bool:
    for marker in markers:
        if marker in token:
            return True
    return False


def _status(score: float) -> str:
    if score >= EXACT_SCORE:
        return "exact"
    if score >= EXPLORE_SCORE:
        return "candidate"
    return "unknown"


def doc_queue(decisions: list[RouteDecision]) -> Queue:
    """Document-level queue: any production table wins, then human, then explore."""
    queues = {decision.queue for decision in decisions}
    if "production" in queues:
        return "production"
    if "human" in queues:
        return "human"
    return "explore"
