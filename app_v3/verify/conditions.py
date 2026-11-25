"""条件完整性验证。"""
from __future__ import annotations

from typing import Any

from app_v3.normalize.conditions import classify_temperature

TEMP_REQUIRED = {"室温拉伸", "高温拉伸", "冲击试验", "硬度试验", "持久试验", "蠕变试验", "弯曲试验", "高倍"}
UNIT_REQUIRED = {"冲击试验", "硬度试验"}


def validate_conditions(record: dict[str, Any]) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    category = str(record.get("category") or "")
    conditions = record.get("conditions") or {}
    enrichment = record.get("enrichment") or {}
    temperature = str(conditions.get("试验温度") or enrichment.get("temperature") or "")
    unit = str(record.get("unit") or "")
    if category in TEMP_REQUIRED:
        if not temperature:
            diagnostics.append({"code": "missing_temperature", "field": "conditions.试验温度", "severity": "warn",
                                "message": "缺少试验温度"})
        else:
            kind = classify_temperature(temperature)
            if category == "高温拉伸" and kind == "room":
                diagnostics.append({"code": "temperature_category_conflict", "field": "conditions.试验温度",
                                    "severity": "error",
                                    "message": f"高温拉伸记录的试验温度为室温: {temperature}"})
            elif category == "室温拉伸" and kind in {"high", "low"}:
                diagnostics.append({"code": "temperature_category_conflict", "field": "conditions.试验温度",
                                    "severity": "error",
                                    "message": f"室温拉伸记录的试验温度非室温: {temperature}"})
    if category in UNIT_REQUIRED and not unit:
        diagnostics.append({"code": "missing_unit", "field": "unit", "severity": "warn",
                            "message": "缺少单位"})
    return diagnostics
