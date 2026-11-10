"""Locate the extraction record a free-text feedback refers to.

Users should be able to describe a problem without picking a record. The
locator applies deterministic signals (table number, property name, grade,
condition, numeric value, inspection item) before falling back to the model.
A whole-table or whole-document problem is located at that scope instead of
being rejected for lacking a record.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..contracts import DocumentResult, Record
from ..tablegrid.normalize import canonical_property, clean_text
from .contracts import FeedbackTarget
from .planner import _parse_json

NUMBER_RE = re.compile(r"-?\d+(?:\.\d+)?")
TABLE_TOKEN_RE = re.compile(
    r"(?:表\s*([0-9A-Za-z.]+)|\b(T[0-9]+)\b)", re.IGNORECASE
)
CJK_RE = re.compile(r"[\u4e00-\u9fff]")
EXPECTED_RE = re.compile(
    r"(?:应为|应该是|应改成|应改为|改成|改为|正确值(?:应)?为|"
    r"期望(?:值)?(?:为|是)?)\s*"
    r"([<≤≥>]?\s*-?\d+(?:\.\d+)?"
    r"(?:\s*[~～至-]\s*-?\d+(?:\.\d+)?)?)"
)
MAX_CANDIDATES = 60
FEATURE_PROFILES = (
    (("拉伸", "力学", "强度", "屈服", "延伸", "收缩"), "mechanical_properties"),
    (("化学", "成分", "元素"), "chemical_composition"),
    (("硬度",), "mechanical_properties"),
    (("晶粒", "金相", "组织"), "inspection"),
    (("尺寸", "偏差", "直径"), "dimension"),
    (("超声", "探伤", "无损"), "inspection"),
)


@dataclass
class LocatedTarget:
    target: FeedbackTarget
    expected: str | None = None


def locate_target(
    result: DocumentResult,
    description: str,
    source_quote: str = "",
    *,
    model_url: str | None = None,
    model_name: str = "",
    timeout: float = 60.0,
) -> LocatedTarget | None:
    """Find the record, table or feature a description refers to."""

    text = clean_text(f"{description} {source_quote}")
    if not text:
        return None
    table_hint = _table_hint(result, text)
    numbers = [float(item) for item in NUMBER_RE.findall(text)]
    property_hints = _property_hints(result, text)
    grade_hints = _grade_hints(result, text)

    scored: list[tuple[int, Record, str]] = []
    for record in result.records:
        for name, value in record.properties.items():
            score = 0
            if name in property_hints:
                score += 4
            if table_hint and record.source_table_id == table_hint:
                score += 3
            if grade_hints and clean_text(record.grade) in grade_hints:
                score += 3
            if numbers and _value_matches(value, numbers):
                score += 2
            score += _condition_hits(record, text)
            if score:
                scored.append((score, record, name))

    if scored:
        best = max(item[0] for item in scored)
        top = [item for item in scored if item[0] == best]
        keys = {(item[1].record_id, item[2]) for item in top}
        if len(keys) == 1:
            _, record, name = top[0]
            return LocatedTarget(_target_for(record, name), expected_from_text(text))
        # Ambiguous record: let the model choose before falling back to the
        # whole table ("室温拉伸大部分内容有问题" has no field to choose).
        located = _model_locate(
            result,
            text,
            scored,
            model_url=model_url,
            model_name=model_name,
            timeout=timeout,
        )
        if located is not None:
            return located
        return _table_feature_target(result, text)

    table_target = _table_feature_target(result, text)
    if table_target is not None:
        return table_target
    return _model_locate(
        result,
        text,
        scored,
        model_url=model_url,
        model_name=model_name,
        timeout=timeout,
    )


def _table_hint(result: DocumentResult, text: str) -> str | None:
    labels: dict[str, str] = {}
    for table in result.tables:
        match = re.search(r"表\s*([0-9A-Za-z.]+)", clean_text(table.caption))
        if match:
            labels[match.group(1).lower()] = table.table_id
    for match in TABLE_TOKEN_RE.finditer(text):
        token = (match.group(1) or match.group(2) or "").lower()
        if token in labels:
            return labels[token]
        if token.startswith("t"):
            return token.upper()
    return None


def _table_feature_target(
    result: DocumentResult, text: str
) -> LocatedTarget | None:
    """Map a project-level description ("室温拉伸") to its table."""

    feature = None
    profile = None
    for keywords, candidate_profile in FEATURE_PROFILES:
        match = next((keyword for keyword in keywords if keyword in text), None)
        if match:
            feature = match
            profile = candidate_profile
            break
    if not feature:
        return None
    candidates = []
    for table in result.tables:
        haystack = clean_text(
            " ".join(
                [table.caption or ""]
                + [" ".join(path) for path in table.header_paths]
            )
        )
        if feature in haystack:
            candidates.append(table)
    if not candidates and profile:
        candidates = [table for table in result.tables if table.profile == profile]
    if not candidates:
        return None
    counts = {
        table.table_id: sum(
            1
            for record in result.records
            if record.source_table_id == table.table_id
        )
        for table in candidates
    }
    best = max(candidates, key=lambda table: counts.get(table.table_id, 0))
    return LocatedTarget(
        FeedbackTarget(table_id=best.table_id, feature=feature),
        expected_from_text(text),
    )


def _property_hints(result: DocumentResult, text: str) -> set[str]:
    names = {name for record in result.records for name in record.properties}
    hints = {name for name in names if _token_in_text(name, text)}
    # Chinese aliases ("抗拉强度" -> Rm) appear as short substrings. Only pure
    # CJK tokens are tested: "2A14" would otherwise match the single-letter
    # alias "a" inside a grade code.
    for size in range(2, 7):
        for index in range(0, max(0, len(text) - size + 1)):
            token = text[index : index + size]
            if not CJK_RE.fullmatch(token):
                continue
            mapped = canonical_property(token)
            if mapped:
                hints.add(mapped)
    return hints


def _grade_hints(result: DocumentResult, text: str) -> set[str]:
    grades = {
        clean_text(record.grade)
        for record in result.records
        if clean_text(record.grade)
    }
    return {grade for grade in grades if _token_in_text(grade, text)}


def _condition_hits(record: Record, text: str) -> int:
    condition = clean_text(record.condition)
    if not condition:
        return 0
    parts = [
        part.strip()
        for part in re.split(r"[/、,，]", condition)
        if part.strip()
    ]
    return min(4, 2 * sum(1 for part in parts if part in text))


def _token_in_text(token: str, text: str) -> bool:
    if not token:
        return False
    return bool(
        re.search(
            rf"(?<![A-Za-z0-9]){re.escape(token)}(?![A-Za-z0-9])",
            text,
            re.IGNORECASE,
        )
    )


def _value_matches(value: Any, numbers: list[float]) -> bool:
    candidates = [value.value, value.lower, value.upper]
    for candidate in candidates:
        if candidate is None:
            continue
        for number in numbers:
            if abs(float(candidate) - number) < 1e-9:
                return True
    return False


def _target_for(record: Record, name: str) -> FeedbackTarget:
    return FeedbackTarget(
        record_id=record.record_id,
        property=name,
        table_id=record.source_table_id or None,
        grade=record.grade or None,
        condition=record.condition or None,
    )


def _model_locate(
    result: DocumentResult,
    text: str,
    scored: list[tuple[int, Record, str]],
    *,
    model_url: str | None,
    model_name: str,
    timeout: float,
) -> LocatedTarget | None:
    if not model_url:
        return None
    candidates = _candidates(result, scored)
    prompt = (
        "你是金属材料抽取结果定位器。根据用户反馈，从候选记录中选出最可能"
        "出错的一条记录和一个字段。只输出 JSON："
        '{"record_id":"...","property":"...","expected":"可选，用户期望值"}；'
        '无法判断时输出 {"record_id":null}。\n'
        f"候选记录：{candidates}\n反馈：{text}"
    )
    try:
        import httpx

        with httpx.Client(timeout=timeout, trust_env=False) as client:
            response = client.post(
                f"{model_url.rstrip('/')}/chat/completions",
                json={
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": "只输出 JSON，不要解释。"},
                        {"role": "user", "content": prompt},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 256,
                    "response_format": {"type": "json_object"},
                    "stream": False,
                },
            )
            response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        payload = _parse_json(content)
    except Exception:  # noqa: BLE001 - locating is best effort
        return None
    record_id = str(payload.get("record_id") or "")
    name = str(payload.get("property") or "")
    record = next(
        (item for item in result.records if item.record_id == record_id), None
    )
    if record is None or name not in record.properties:
        return None
    expected = (
        str(payload.get("expected") or "").strip()
        or expected_from_text(text)
        or None
    )
    return LocatedTarget(_target_for(record, name), expected)


def expected_from_text(text: str) -> str | None:
    match = EXPECTED_RE.search(text)
    if match is None:
        return None
    return match.group(1).replace(" ", "") or None


def _candidates(
    result: DocumentResult, scored: list[tuple[int, Record, str]]
) -> list[dict[str, Any]]:
    if scored:
        records = [item[1] for item in scored]
    else:
        records = list(result.records)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        if record.record_id in seen:
            continue
        seen.add(record.record_id)
        rows.append(
            {
                "record_id": record.record_id,
                "table_id": record.source_table_id,
                "grade": record.grade,
                "condition": record.condition,
                "properties": {
                    name: value.raw or value.text
                    for name, value in record.properties.items()
                },
            }
        )
        if len(rows) >= MAX_CANDIDATES:
            break
    return rows
