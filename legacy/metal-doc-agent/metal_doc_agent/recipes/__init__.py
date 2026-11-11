"""M1.6 recipes: signature, routing and column binding."""

from .authoring import (
    is_duplicate,
    promote_candidate,
    propose_recipe,
    save_candidate,
)
from .binding import AliasConfig, bind_columns, load_aliases
from .coldstart import (
    ColdCluster,
    ColdTable,
    build_report,
    cluster_long_tail,
    coldstart_metrics,
    render_markdown,
    triage_table,
)
from .lifecycle import (
    LEVEL_STATUS,
    LEVELS,
    LifecycleError,
    RecipeRegistry,
    gate_failures,
)
from .router import RecipeMatch, load_recipes, match_recipe, route_table
from .routing import RouteDecision, decide_route, doc_queue
from .shadow import (
    FieldShadowReport,
    GoldTable,
    ShadowReport,
    evaluate_field_shadow,
    evaluate_shadow,
)
from .schema import (
    load_schema,
    recipe_id_matches_stem,
    validate_recipe,
    validate_recipe_dir,
)
from .signature import build_signature, signature_tokens, token_overlap, token_similarity

__all__ = [
    "AliasConfig",
    "ColdCluster",
    "ColdTable",
    "FieldShadowReport",
    "GoldTable",
    "LEVEL_STATUS",
    "LEVELS",
    "LifecycleError",
    "RecipeMatch",
    "RecipeRegistry",
    "RouteDecision",
    "ShadowReport",
    "bind_columns",
    "build_report",
    "build_signature",
    "cluster_long_tail",
    "coldstart_metrics",
    "decide_route",
    "doc_queue",
    "evaluate_field_shadow",
    "evaluate_shadow",
    "gate_failures",
    "is_duplicate",
    "load_aliases",
    "load_recipes",
    "load_schema",
    "match_recipe",
    "promote_candidate",
    "propose_recipe",
    "recipe_id_matches_stem",
    "render_markdown",
    "route_table",
    "save_candidate",
    "signature_tokens",
    "token_overlap",
    "token_similarity",
    "triage_table",
    "validate_recipe",
    "validate_recipe_dir",
]
