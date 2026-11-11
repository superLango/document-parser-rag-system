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

_SPACE_RE = re.compile(r"\s+")
_NUMERIC_RE = re.compile(r"^[\d.~～≤≥<>\-+/%℃]+$")
_PAREN_RE = re.compile(r"[（(][^）)]*[）)]")
_SUB_TOKEN_RE = re.compile(r"[a-z]+|\d+(?:\.\d+)?|[\u4e00-\u9fff]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


class MatchResult(BaseModel):
    recipe_id: str | None = None
    version: str | None = None
    digest: str | None = None
    status: str = "unknown"
    score: float = 0.0


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
            if _CJK_RE.search(token) and re.search(r"[a-z0-9]", token):
                for sub in _SUB_TOKEN_RE.findall(token):
                    add(sub)
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


def signature_score(table: TableGrid, signature: RecipeSignature) -> float:
    if table.profile != signature.profile:
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
    table_tokens = signature_tokens(table)
    similarity = 0.5 * token_similarity(table_tokens, signature.tokens) + 0.5 * token_overlap(
        table_tokens, signature.tokens
    )
    score += 0.2 * similarity
    return round(min(score, 1.0), 4)


def match_table(table: TableGrid, recipes: list[RecipeManifest]) -> MatchResult:
    best: tuple[RecipeManifest, float] | None = None
    for manifest in recipes:
        score = signature_score(table, manifest.signature)
        if best is None or score > best[1]:
            best = (manifest, score)
    if best is None:
        return MatchResult()
    manifest, score = best
    if score >= EXACT_THRESHOLD:
        return _result(manifest, "exact", score)
    if score >= CANDIDATE_THRESHOLD:
        return _result(manifest, "candidate", score)
    return MatchResult(status="unknown", score=score)


def _result(manifest: RecipeManifest, status: str, score: float) -> MatchResult:
    return MatchResult(
        recipe_id=manifest.recipe_id,
        version=manifest.version,
        digest=manifest.checksum,
        status=status,
        score=score,
    )
