"""Table signature extraction and similarity (M1.6)."""

from __future__ import annotations

import re

from ..contracts import RecipeSignature, TableGrid
from ..tablegrid.normalize import clean_text

_SPACE_RE = re.compile(r"\s+")
_NUMERIC_RE = re.compile(r"^[\d.~～≤≥<>\-+/%℃]+$")
_PAREN_RE = re.compile(r"[（(][^）)]*[）)]")
_SUB_TOKEN_RE = re.compile(r"[a-z]+|\d+(?:\.\d+)?|[\u4e00-\u9fff]+")
_CJK_RE = re.compile(r"[\u4e00-\u9fff]")


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
    # Single footnote marker such as "a" is not a signature token.
    if len(token) == 1 and token.isalpha():
        return True
    return False


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
            # Mixed Chinese/Latin headers such as "硬度HRC" are common; keep the
            # full token and also expose the semantic sub-tokens.
            if _CJK_RE.search(token) and re.search(r"[a-z0-9]", token):
                for sub in _SUB_TOKEN_RE.findall(token):
                    add(sub)
            if any(sep in token for sep in "*/,"):
                for sub in re.split(r"[*/,\s]+", token):
                    add(sub)
            if len(tokens) >= limit:
                return tokens[:limit]
    return tokens


def build_signature(table: TableGrid) -> RecipeSignature:
    units = sorted(
        {
            clean_text(unit)
            for unit in (table.units or [])
            if clean_text(unit)
        }
    )
    return RecipeSignature(
        profile=table.profile,
        orientation=table.orientation,
        n_cols=table.n_cols,
        blocks=len(table.blocks),
        tokens=signature_tokens(table),
        multi_header=int(table.header_rows) > 1,
        unit_set=units[:16],
    )


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
    """Overlap coefficient: tolerates a recipe listing more tokens than the table."""
    if not left or not right:
        return 0.0
    left_set = set(left)
    right_set = set(right)
    smaller = min(len(left_set), len(right_set))
    if smaller == 0:
        return 0.0
    return len(left_set & right_set) / smaller


def signature_score(table: TableGrid, recipe_signature: RecipeSignature) -> float:
    if table.profile != recipe_signature.profile:
        return 0.0
    score = 0.5
    if table.orientation == recipe_signature.orientation:
        score += 0.15
    if table.n_cols == recipe_signature.n_cols:
        score += 0.1
    elif abs(table.n_cols - recipe_signature.n_cols) <= 3:
        score += 0.05
    if len(table.blocks) == recipe_signature.blocks:
        score += 0.05
    table_tokens = signature_tokens(table)
    similarity = 0.5 * token_similarity(
        table_tokens, recipe_signature.tokens
    ) + 0.5 * token_overlap(table_tokens, recipe_signature.tokens)
    score += 0.2 * similarity
    return round(min(score, 1.0), 4)
