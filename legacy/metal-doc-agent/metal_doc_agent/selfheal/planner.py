"""Repair planning: map a finding to a whitelisted L2 operator.

The planner is intentionally conservative. A local heuristic handles the few
deterministic cases; when a model endpoint is configured it may propose a
whitelisted operator, and anything outside the registry is rejected.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from .config import SelfHealSettings
from .contracts import Finding
from .l2 import OPERATORS, validate_operator

PLANNER_PROMPT = """你是金属材料抽取配置的修复规划器。只能在下列算子中选择一个来修复问题，
不能修改代码、不能改生产配置、不能发明算子。若无法用算子修复，输出 {"operator": null}。

算子与参数：
- column_alias.add: {"alias": "表头别名", "property": "规范属性名"}
- table_repair.add: {"document_key": "标准号去符号大写", "table_id": "T1", "spec": {...}}
- recipe.binding_override: {"recipe_id": "配方id", "bindings": {...}}
- unit_normalize.add: {"pattern": "原单位", "unit": "目标单位"}
- property_map.add: {"alias": "别名", "property": "规范名"}
- extractor.enable: {"extractor": "bound_matrix|property_matrix|element_matrix|hardness_minmax|nonrecord"}
- coverage_template.hint: {"doc_type": "文档类型", "template": "模板名"}

输出 JSON：{"operator": "...", "params": {...}, "reason": "..."}
问题：{finding}
表头：{header}
记录：{record}
"""


class Planner(Protocol):
    def plan(self, finding: Finding, context: dict[str, Any]) -> dict[str, Any] | None:
        ...


class HeuristicPlanner:
    """Deterministic fallback: only proposes when the mapping is obvious."""

    def plan(self, finding: Finding, context: dict[str, Any]) -> dict[str, Any] | None:
        if finding.rule_code == "evidence_quote_mismatch" and finding.evidence:
            evidence = finding.evidence[0]
            if (
                evidence.table_id
                and evidence.row is not None
                and evidence.col is not None
                and evidence.quote
            ):
                return {
                    "operator": "table_repair.add",
                    "params": {
                        "document_key": context.get("document_key") or "",
                        "table_id": evidence.table_id,
                        "spec": {
                            "patch_cells": {
                                str(evidence.row): {str(evidence.col): evidence.quote}
                            }
                        },
                    },
                    "reason": "证据引文与单元格不一致，按证据修正该单元格",
                }
        return None


class ModelPlanner:
    def __init__(self, settings: SelfHealSettings) -> None:
        if not settings.model_base_url:
            raise ValueError("未配置模型端点")
        import httpx

        self.settings = settings
        self._client = httpx.Client(timeout=settings.model_timeout, trust_env=False)

    def close(self) -> None:
        self._client.close()

    def plan(self, finding: Finding, context: dict[str, Any]) -> dict[str, Any] | None:
        prompt = _render_prompt(finding, context)
        response = self._client.post(
            f"{self.settings.model_base_url.rstrip('/')}/chat/completions",
            json={
                "model": self.settings.model_name,
                "messages": [
                    {"role": "system", "content": "只输出 JSON，不要解释。"},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.0,
                "max_tokens": 512,
                "response_format": {"type": "json_object"},
                "stream": False,
            },
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        payload = _parse_json(content)
        operator = payload.get("operator")
        params = payload.get("params") or {}
        if not operator or operator not in OPERATORS:
            return None
        if validate_operator(operator, params):
            return None
        return {"operator": operator, "params": params, "reason": payload.get("reason")}


def _render_prompt(finding: Finding, context: dict[str, Any]) -> str:
    """Substitute the finding into the prompt without touching JSON examples.

    ``str.format`` treats ``{"operator": ...}`` in the example as a field name
    and raises ``KeyError: '"operator"'``, which made every L2 plan fail.
    """

    return (
        PLANNER_PROMPT.replace(
            "{finding}",
            json.dumps(finding.model_dump(mode="json"), ensure_ascii=False),
        )
        .replace("{header}", json.dumps(context.get("header"), ensure_ascii=False))
        .replace("{record}", json.dumps(context.get("record"), ensure_ascii=False))
    )


def _parse_json(text: str) -> dict:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        payload = json.loads(raw[start : end + 1])
    except ValueError:
        return {}
    return payload if isinstance(payload, dict) else {}
