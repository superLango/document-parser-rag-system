"""Deterministic table-to-recipe matching.

The scoring function mirrors the legacy ``recipes/signature.py`` so routing
parity against the old matcher stays measurable.
"""

import re

from pydantic import BaseModel

from services.ocr.contracts import TableGrid
from services.shared.text import clean_text

from .package import RecipeManifest, RecipeSignature

EXACT_THRESHOLD = 0.9
CANDIDATE_THRESHOLD = 0.6
# A recipe that shares no header tokens with the table must not win on
# profile/orientation/column-count alone (hardness_v1 vs
# mechanical_properties_v1 share the same profile).
LOW_COVERAGE_PENALTY = 0.1

_SPACE_RE = re.compile(r"\s+")
_NUMERIC_RE = re.compile(r"^[\d.~～≤≥<>\-+/%℃]+$")
_PAREN_RE = re.compile(r"[（(][^）)]*[）)]")
_SUB_TOKEN_RE = re.compile(r"[a-z]+|\d+(?:\.\d+)?|[\u4e00-\u9fff]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
# Headers usually append a unit to the symbol (``σb N/mm²``, ``δ5 %``).
_UNIT_SPLIT_RE = re.compile(r"(?:n/mm2|n/mm²|mpa|j/cm2|j/cm²|%|℃)")
_SYMBOL_ALIASES = {
    "σb": "rm",
    "σ0.2": "rp0.2",
    "σ1.0": "rp1.0",
    "δ5": "δs",
    "δs": "δs",
    "aku": "ku2",
    "psi": "ψ",
}
# English property headers (AMS/ASME/ASTM) must reach the same measure tokens
# as the Chinese signatures: "Tensile Strength MPa" -> rm.
_EN_MEASURE_ALIASES = (
    ("tensilestrength", "rm"),
    ("yieldstrength", "rp0.2"),
    ("elongation", "a"),
    ("reductionofarea", "z"),
    ("impactenergy", "kv2"),
    ("brinell", "hbw"),
    ("rockwell", "hrc"),
    ("vickers", "hv"),
)
# 中文表头常写“延伸率/持久时间/屈服强度”，配方签名用“δs/持久/时间”。
_CJK_MEASURE_ALIASES = (
    ("持久时间", ("持久时间", "持久", "时间")),
    ("持久强度", ("持久时间", "持久")),
    ("延伸率", ("a", "断后伸长率", "δs")),
    ("伸长率", ("a", "断后伸长率", "δs")),
    ("断面收缩率", ("z", "断面收缩率")),
    ("屈服强度", ("rp0.2", "σ0.2")),
    ("抗拉强度", ("rm", "σb")),
)


class MatchResult(BaseModel):
    recipe_id: str | None = None
    version: str | None = None
    digest: str | None = None
    status: str = "unknown"
    score: float = 0.0
    # top1 - top2，用于低置信/近似平局的人工复核判断。
    margin: float = 0.0
    runner_up: str | None = None


def normalize_token(value: str | None) -> str:
    text = clean_text(value).lower()
    text = _PAREN_RE.sub("", text)
    text = _SPACE_RE.sub("", text)
    text = text.replace("（", "(").replace("）", ")")
    text = text.replace("／", "/")
    return text


def _is_noise(token: str) -> bool:
    if not token or _NUMERIC_RE.match(token):
        return True
    return len(token) == 1 and token.isalpha()


def signature_tokens(table: TableGrid, limit: int = 40) -> list[str]:
    tokens: list[str] = []
    seen: set[str] = set()

    def add(token: str) -> None:
        if _is_noise(token) or token in seen:
            return
        seen.add(token)
        tokens.append(token)

    for path in table.header_paths:
        for part in path:
            token = normalize_token(part)
            add(token)
            if _CJK_RE.search(token):
                for phrase, aliases in _CJK_MEASURE_ALIASES:
                    if phrase in token:
                        for alias in aliases:
                            add(alias)
            if not _CJK_RE.search(token):
                # Latin headers: map known property phrases to the canonical
                # measure token used by Chinese signatures.
                for phrase, canonical in _EN_MEASURE_ALIASES:
                    if phrase in token:
                        add(canonical)
            for piece in _UNIT_SPLIT_RE.split(token):
                if not piece or piece == token:
                    continue
                add(_SYMBOL_ALIASES.get(piece, piece))
            if _CJK_RE.search(token) and re.search(r"[a-z0-9]", token):
                for sub in _SUB_TOKEN_RE.findall(token):
                    add(sub)
                    # "抗拉强度RmMPa" is one Latin run; split the unit tail so
                    # the measure symbol (rm) still reaches the signature.
                    for piece in _UNIT_SPLIT_RE.split(sub):
                        if piece and piece != sub:
                            add(_SYMBOL_ALIASES.get(piece, piece))
            if any(sep in token for sep in "*/,"):
                for sub in re.split(r"[*/,\s]+", token):
                    add(sub)
            if len(tokens) >= limit:
                return tokens[:limit]
    return tokens


def token_similarity(left: list[str], right: list[str]) -> float:
    if not left or not right:
        return 0.0
    left_set = set(left)
    right_set = set(right)
    union = left_set | right_set
    if not union:
        return 0.0
    return len(left_set & right_set) / len(union)


def token_overlap(left: list[str], right: list[str]) -> float:
    if not left or not right:
        return 0.0
    left_set = set(left)
    right_set = set(right)
    smaller = min(len(left_set), len(right_set))
    if smaller == 0:
        return 0.0
    return len(left_set & right_set) / smaller


def token_coverage(table_tokens: list[str], signature_tokens: list[str]) -> float:
    """Fraction of table header tokens explained by a recipe signature."""
    if not table_tokens or not signature_tokens:
        return 0.0
    table_set = set(table_tokens)
    return len(table_set & set(signature_tokens)) / len(table_set)


HARDNESS_TOKENS = (
    "hb", "hbw", "hbs", "hrc", "hrb", "hv",
    "硬度", "布氏硬度", "洛氏硬度", "维氏硬度",
)

# 一张表同时出现拉伸/冲击/硬度列时，必须交给覆盖全部列的配方
# （mechanical_properties_v1 已绑定 HB/HBW/HRC/HV），否则硬度配方会独占
# 路由并把其余列判成 MEASURE_COLUMN_MISSING。
MECHANICAL_MEASURE_TOKENS = {
    "rm", "rp0.2", "rp1.0", "reh", "rel", "σb", "σ0.2",
    "a", "z", "δs", "断后伸长率", "断面收缩率",
    "kv2", "ku2", "ku5", "akv", "冲击", "冲击吸收能量",
    "侧向膨胀值", "kic", "e", "持久时间", "持久强度",
}
HARDNESS_ONLY_MEASURES = {"hb", "hbw", "hbs", "hrc", "hrb", "hv"}


def _is_hardness_only(manifest: RecipeManifest) -> bool:
    measures = {
        normalize_token(str(name))
        for name in ((manifest.bindings or {}).get("measures") or {})
    }
    return bool(measures) and measures <= HARDNESS_ONLY_MEASURES


def signature_score(table: TableGrid, signature: RecipeSignature) -> float:
    if table.profile != signature.profile:
        return 0.0
    if table.profile == "chemical_composition" and table.orientation != signature.orientation:
        # Grade-row chemistry must not be routed to the transposed element-row
        # recipe (and vice versa): the two recipes bind different row keys and
        # produce different grades.
        return 0.0
    table_tokens = signature_tokens(table)
    if "hrc" in signature.tokens and "rm" not in signature.tokens:
        # The hardness recipe shares the mechanical profile; without a printed
        # hardness measure it must not win over the real mechanical recipe
        # (AMS fracture-toughness tables were routed to hardness_v1).
        if not any(token in table_tokens for token in HARDNESS_TOKENS):
            return 0.0
    score = 0.5
    if table.orientation == signature.orientation:
        score += 0.15
    if table.n_cols == signature.n_cols:
        score += 0.1
    elif abs(table.n_cols - signature.n_cols) <= 3:
        score += 0.05
    if len(table.blocks) == signature.blocks:
        score += 0.05
    similarity = 0.5 * token_similarity(table_tokens, signature.tokens) + 0.5 * token_overlap(
        table_tokens, signature.tokens
    )
    score += 0.2 * similarity
    # Only a complete absence of header overlap is penalized.  Partial overlap
    # (one real measure, e.g. Rm) is positive evidence and must not be pushed
    # below a profile-only competitor such as hardness_v1.
    if table_tokens and token_coverage(table_tokens, signature.tokens) == 0.0:
        score -= LOW_COVERAGE_PENALTY
    return round(max(0.0, min(score, 1.0)), 4)


def match_table(table: TableGrid, recipes: list[RecipeManifest]) -> MatchResult:
    table_tokens = signature_tokens(table)
    has_hardness = any(token in HARDNESS_TOKENS for token in table_tokens)
    has_mechanical = any(token in MECHANICAL_MEASURE_TOKENS for token in table_tokens)
    mixed = has_hardness and has_mechanical
    ranked: list[tuple[float, float, int, RecipeManifest]] = []
    for manifest in recipes:
        # 混合性能表（拉伸/冲击 + 硬度）交给覆盖全部列的配方；纯硬度表不受影响。
        if mixed and _is_hardness_only(manifest):
            continue
        score = signature_score(table, manifest.signature)
        coverage = token_coverage(table_tokens, manifest.signature.tokens)
        specificity = len((manifest.bindings or {}).get("measures") or {})
        ranked.append((score, coverage, specificity, manifest))
    if not ranked:
        return MatchResult()
    ranked.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    score, _, _, manifest = ranked[0]
    runner_up = ranked[1][3].recipe_id if len(ranked) > 1 else None
    margin = round(score - (ranked[1][0] if len(ranked) > 1 else 0.0), 4)
    if score >= EXACT_THRESHOLD:
        return _result(manifest, "exact", score, margin, runner_up)
    if score >= CANDIDATE_THRESHOLD:
        return _result(manifest, "candidate", score, margin, runner_up)
    return MatchResult(
        status="unknown", score=score, margin=margin, runner_up=runner_up
    )


def _result(
    manifest: RecipeManifest,
    status: str,
    score: float,
    margin: float = 0.0,
    runner_up: str | None = None,
) -> MatchResult:
    return MatchResult(
        recipe_id=manifest.recipe_id,
        version=manifest.version,
        digest=manifest.checksum,
        status=status,
        score=score,
        margin=margin,
        runner_up=runner_up,
    )
