"""Column binding: header path -> item family / property / role / facets (M1.6)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..contracts import (
    ColumnBinding,
    ColumnBindingResult,
    ItemGroup,
    Recipe,
    TableGrid,
)
from ..tablegrid.normalize import canonical_element, clean_text, is_numeric_like
from .signature import normalize_token

DEFAULT_ALIAS_PATH = (
    Path(__file__).resolve().parents[2] / "configs" / "column_aliases.json"
)
_UNIT_PAREN_RE = re.compile(r"[（(][^）)]*[）)]")
_NUMERIC_TEMP_RE = re.compile(r"([-+]?\d+(?:\.\d+)?)\s*(?:℃|°C|K)")
_STANDARD_RE = re.compile(
    r"(?:GB/T|GB|GJB|JB/T|YB/T|HB|ASTM|ISO|AMS|Q/[A-Za-z]+)\s*[0-9.\-]+",
    re.IGNORECASE,
)
PROCESS_PARAM_MARKERS = (
    "工艺参数",
    "参数偏差",
    "轧制初温",
    "轧制末温",
    "压缩比",
    "进给速度",
    "停机次数",
)


def _is_process_parameter_table(table: TableGrid, path_text: str) -> bool:
    caption = normalize_token(table.caption or "")
    if "工艺参数偏差" in caption:
        return True
    return any(marker in path_text for marker in PROCESS_PARAM_MARKERS)


@dataclass(frozen=True)
class AliasConfig:
    family_keywords: dict[str, tuple[str, ...]] = field(default_factory=dict)
    property_aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)
    role_keywords: dict[str, tuple[str, ...]] = field(default_factory=dict)
    dimension_property_aliases: dict[str, tuple[str, ...]] = field(default_factory=dict)
    hardness_scales: dict[str, str] = field(default_factory=dict)
    family_by_property: dict[str, str] = field(default_factory=dict)


def load_aliases(path: str | Path | None = None) -> AliasConfig:
    target = Path(path) if path is not None else DEFAULT_ALIAS_PATH
    if not target.exists():
        return AliasConfig()
    data = json.loads(target.read_text(encoding="utf-8"))
    return AliasConfig(
        family_keywords={
            key: tuple(value) for key, value in data.get("family_keywords", {}).items()
        },
        property_aliases={
            key: tuple(value) for key, value in data.get("property_aliases", {}).items()
        },
        role_keywords={
            key: tuple(value) for key, value in data.get("role_keywords", {}).items()
        },
        dimension_property_aliases={
            key: tuple(value)
            for key, value in data.get("dimension_property_aliases", {}).items()
        },
        hardness_scales=dict(data.get("hardness_scales", {})),
        family_by_property=dict(data.get("family_by_property", {})),
    )


def bind_columns(
    table: TableGrid,
    recipe: Recipe | None = None,
    aliases: AliasConfig | None = None,
    match_status: str = "unknown",
) -> ColumnBindingResult:
    cfg = aliases or load_aliases()
    bindings = [
        _bind_column(table, column, cfg, recipe)
        for column in range(table.n_cols)
    ]
    _attach_conditions(bindings)
    groups = _build_item_groups(bindings)
    conflicts = [
        {
            "column": item.column,
            "reason": item.reason,
            "property": item.property,
            "item_family": item.item_family,
        }
        for item in bindings
        if item.status == "conflict"
    ]
    ambiguous = [
        {
            "column": item.column,
            "header_path": item.header_path,
            "reason": item.reason,
        }
        for item in bindings
        if item.status == "ambiguous"
    ]
    unmapped = [item.column for item in bindings if item.status == "unmapped"]
    return ColumnBindingResult(
        table_id=table.table_id,
        recipe_id=recipe.recipe_id if recipe else None,
        match_status=match_status if match_status in {"exact", "candidate", "unknown"} else "unknown",
        bindings=bindings,
        item_groups=groups,
        conflicts=conflicts,
        ambiguous=ambiguous,
        unmapped_columns=unmapped,
    )


def _bind_column(
    table: TableGrid,
    column: int,
    cfg: AliasConfig,
    recipe: Recipe | None,
) -> ColumnBinding:
    path = table.header_paths[column] if column < len(table.header_paths) else []
    leaf = clean_text(path[-1]) if path else ""
    path_text = normalize_token(" ".join(path))
    header_path = [clean_text(part) for part in path if clean_text(part)]
    evidence = {
        "page_no": table.page_no,
        "table_id": table.table_id,
        "column": column,
        "header_row": max(table.header_rows - 1, 0),
    }
    if not leaf and not path_text:
        return ColumnBinding(
            column=column,
            header_path=header_path,
            status="unmapped",
            reason="空列/无表头",
            evidence=evidence,
        )
    if _is_process_parameter_table(table, path_text):
        return ColumnBinding(
            column=column,
            header_path=header_path,
            status="unmapped",
            reason="工艺参数偏差记录表，不绑定检测项目",
            evidence=evidence,
        )

    property_code = _resolve_property(path, table.profile, cfg, recipe)
    property_family = cfg.family_by_property.get(property_code or "")
    group_text = normalize_token(" ".join(path[:-1]))
    family_group = (
        None
        if property_code in {"CEV", "Pcm"}
        else _match_family(group_text, table.profile, cfg)
    )
    family_leaf = _match_family(normalize_token(leaf), table.profile, cfg)
    family = family_group or family_leaf or property_family
    if family is None:
        family = _profile_family(table.profile)

    role = _resolve_role(leaf, path_text, property_code, family, cfg)
    status = "bound"
    reason = None

    if role == "measure" and family_group and property_family and _family_conflict(
        family_group, property_family, property_code
    ):
        status = "conflict"
        reason = f"组名({family_group})与属性({property_family})冲突"
        family = family_group
    elif role == "measure" and not property_code:
        status = "ambiguous"
        reason = "无法识别属性码"
    elif role in {"unknown"}:
        status = "ambiguous"
        reason = (
            "缺少硬度标尺（HBW/HRC/HV）"
            if family == "hardness"
            else "无法判定列角色"
        )

    facets = _facets(path_text, property_code, cfg)
    unit = _resolve_unit(path, table) if role == "measure" else None
    confidence = _confidence(status, family, property_code, role)
    item_raw = _item_raw(path, family, role)

    return ColumnBinding(
        column=column,
        header_path=header_path,
        item_family=family or "unknown",
        item_raw=item_raw,
        property=property_code,
        role=role,
        unit=unit,
        facets=facets,
        confidence=confidence,
        status=status,
        reason=reason,
        evidence=evidence,
    )


def _resolve_property(
    path: list[str],
    profile: str,
    cfg: AliasConfig,
    recipe: Recipe | None,
) -> str | None:
    leaf = clean_text(path[-1]) if path else ""
    leaf_norm = normalize_token(leaf)
    leaf_plain = normalize_token(_UNIT_PAREN_RE.sub("", leaf))
    full_text = normalize_token(" ".join(path))
    if recipe and recipe.bindings:
        overrides = recipe.bindings.get("property_overrides") or {}
        for key in (leaf_norm, leaf_plain, full_text):
            if key in overrides:
                return str(overrides[key])

    if profile == "chemical_composition":
        element = _element_from_path(path)
        if element:
            return element

    if "碳当量" in full_text:
        return "CEV"
    if "焊接裂纹敏感性" in full_text:
        return "Pcm"

    if profile == "dimension":
        nearest_label = next(
            (
                normalize_token(part)
                for part in reversed(path[:-1])
                if part and not is_numeric_like(clean_text(part))
            ),
            "",
        )
        dimension_texts = [leaf_norm, leaf_plain, nearest_label, full_text]
        dimension_aliases = sorted(
            (
                (alias, property_name)
                for property_name, values in cfg.dimension_property_aliases.items()
                for alias in values
            ),
            key=lambda item: len(item[0]),
            reverse=True,
        )
        for text in dimension_texts:
            if not text:
                continue
            for alias, property_name in dimension_aliases:
                if normalize_token(alias) in text:
                    return property_name

    if "持久" in full_text:
        if "时间" in leaf_plain:
            return "持久时间"
        if "应力" in leaf_plain or "温度" in leaf_plain:
            return None
    if "蠕变" in full_text:
        if "速率" in leaf_plain:
            return "蠕变速率"
        if "变形" in leaf_plain:
            return "蠕变变形"
        if "温度" in leaf_plain or "应力" in leaf_plain:
            return None

    aliases = sorted(
        (
            (alias, property_name)
            for property_name, values in cfg.property_aliases.items()
            for alias in values
        ),
        key=lambda item: len(item[0]),
        reverse=True,
    )
    # "δ%" / "ψ%" arrive from OCR as a symbol plus a unit sign; single-letter
    # alias matching split on non-alphanumerics and produced an empty head.
    leaf_symbol = re.sub(r"[%（）()]", "", leaf_plain)
    for alias, property_name in aliases:
        alias_norm = normalize_token(alias)
        if not alias_norm:
            continue
        if len(alias_norm) == 1:
            head = re.split(r"[^a-z0-9.]+", leaf_symbol)[0]
            if leaf_symbol == alias_norm or head == alias_norm:
                return property_name
            continue
        if alias_norm in full_text:
            return property_name
    return None


def _element_from_path(path: list[str]) -> str | None:
    for part in reversed(path):
        element = canonical_element(part)
        if element:
            return element
    return None


def _match_family(text: str, profile: str, cfg: AliasConfig) -> str | None:
    if not text:
        return None
    for family, keywords in cfg.family_keywords.items():
        for keyword in keywords:
            if normalize_token(keyword) in text:
                return family
    return _profile_family(profile)


def _profile_family(profile: str) -> str | None:
    if profile == "chemical_composition":
        return "chemical_composition"
    if profile == "inspection":
        return "inspection"
    return None


def _resolve_role(
    leaf: str,
    path_text: str,
    property_code: str | None,
    family: str | None,
    cfg: AliasConfig,
) -> str:
    leaf_norm = normalize_token(leaf)
    if not leaf_norm:
        return "unknown"
    if _has_keyword(leaf_norm, cfg.role_keywords.get("row_index", ())) or _has_keyword(
        path_text, cfg.role_keywords.get("row_index", ())
    ):
        return "row_index"
    if _has_keyword(path_text, cfg.role_keywords.get("method", ())) or _STANDARD_RE.search(
        leaf
    ):
        # "取样部位及方法" describes where the sample is taken, not the test
        # method column (表13 has both). Keep it as a condition column.
        if "部位" in leaf_norm and "试验方法" not in leaf_norm:
            return "condition"
        return "method"
    if _has_keyword(leaf_norm, cfg.role_keywords.get("remark", ())):
        return "remark"
    if family == "dimension":
        if property_code == "厚度":
            return "condition"
        if property_code in {"宽度", "长度", "内径", "外径", "尺寸偏差"}:
            return "measure"
        if is_numeric_like(leaf):
            return "condition"
    if property_code in {"CEV", "Pcm"}:
        return "measure"
    if family in {"stress_rupture", "creep"} and (
        "温度" in leaf_norm or "应力" in leaf_norm
    ):
        return "condition"
    if property_code:
        return "measure"
    if _has_keyword(leaf_norm, cfg.role_keywords.get("condition", ())) or _has_keyword(
        path_text, cfg.role_keywords.get("condition", ())
    ):
        return "condition"
    if _has_keyword(leaf_norm, cfg.role_keywords.get("row_key", ())) or _has_keyword(
        path_text, cfg.role_keywords.get("row_key", ())
    ):
        return "row_key"
    return "unknown"


def _has_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(normalize_token(keyword) in text for keyword in keywords)


def _family_conflict(
    group_family: str, property_family: str, property_code: str | None
) -> bool:
    if group_family == property_family:
        return False
    if group_family in {"creep", "stress_rupture"} and property_code in {
        "持久时间",
        "持久应力",
        "蠕变速率",
        "蠕变变形",
        "A",
        "Z",
        "E",
    }:
        return False
    return True


def _facets(path_text: str, property_code: str | None, cfg: AliasConfig) -> dict[str, str]:
    facets: dict[str, str] = {}
    if "室温" in path_text:
        facets["temperature"] = "室温"
    elif "高温" in path_text:
        facets["temperature"] = "高温"
    elif "低温" in path_text:
        facets["temperature"] = "低温"
    else:
        match = _NUMERIC_TEMP_RE.search(path_text)
        if match:
            facets["temperature"] = f"{match.group(1)}℃"

    if "夏比" in path_text:
        facets["impact_type"] = "夏比"
    elif "仪器化" in path_text:
        facets["impact_type"] = "仪器化"
    elif "v型" in path_text or "v形" in path_text:
        facets["impact_type"] = "夏比"
    if property_code in {"KV2", "KU2"} or property_code == "侧向膨胀值":
        facets.setdefault("impact_type", "夏比")

    if property_code in cfg.hardness_scales:
        facets["hardness_scale"] = cfg.hardness_scales[property_code]
    match = _STANDARD_RE.search(path_text)
    if match:
        facets["method_standard"] = match.group(0)
    return facets


def _resolve_unit(path: list[str], table: TableGrid) -> str | None:
    from ..tablegrid.normalize import parse_unit

    unit = parse_unit(" ".join(path))
    if unit:
        return unit
    if table.units:
        return table.units[0]
    return None


def _confidence(
    status: str,
    family: str | None,
    property_code: str | None,
    role: str,
) -> float:
    if status != "bound":
        return 0.3
    score = 0.5
    if family and family not in {"unknown", "inspection"}:
        score += 0.2
    if property_code:
        score += 0.2
    if role in {"measure", "row_key", "condition", "method"}:
        score += 0.1
    return round(min(score, 1.0), 2)


def _item_raw(path: list[str], family: str | None, role: str) -> str | None:
    if role not in {"measure", "condition"}:
        return None
    for part in path[:-1] if path else []:
        text = clean_text(part)
        if text and text not in {"力学性能", "化学成分"}:
            return text
    if family:
        return {
            "tensile": "拉伸",
            "impact": "冲击",
            "stress_rupture": "持久",
            "creep": "蠕变",
            "hardness": "硬度",
            "chemical_composition": "化学成分",
        }.get(family, family)
    return None


def _attach_conditions(bindings: list[ColumnBinding]) -> None:
    condition_labels: dict[str, list[str]] = {}
    for item in bindings:
        if item.role == "condition":
            leaf = clean_text(item.header_path[-1]) if item.header_path else ""
            label = item.item_raw if is_numeric_like(leaf) and item.item_raw else leaf
            if not label:
                label = item.item_family
            condition_labels.setdefault(item.item_family, [])
            if label and label not in condition_labels[item.item_family]:
                condition_labels[item.item_family].append(label)
    for item in bindings:
        if item.role == "measure":
            labels = condition_labels.get(item.item_family, [])
            if labels:
                item.facets["conditions"] = "、".join(labels)


def _build_item_groups(bindings: list[ColumnBinding]) -> list[ItemGroup]:
    grouped: dict[tuple[str, str], list[ColumnBinding]] = {}
    for item in bindings:
        if item.role not in {"measure", "condition"}:
            continue
        if item.item_family in {"unknown", "inspection", "identity", "method", "remark"}:
            continue
        key = (item.item_family, item.item_raw or item.item_family)
        grouped.setdefault(key, []).append(item)

    groups: list[ItemGroup] = []
    group_index = 0
    for (family, item_raw), items in grouped.items():
        if not any(item.role == "measure" for item in items):
            continue
        group_index += 1
        facets: dict[str, str] = {}
        for item in items:
            facets.update(item.facets)
        group_status = "conflict" if any(item.status == "conflict" for item in items) else "bound"
        groups.append(
            ItemGroup(
                group_id=f"G{group_index}",
                item_family=family,
                item_raw=item_raw,
                columns=sorted(item.column for item in items),
                facets=facets,
                status=group_status,
            )
        )
    return groups
