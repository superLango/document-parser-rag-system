"""Item matching against the business dictionary.

Two levels are supported:

* ``category`` entries (项目大类) match the item group produced by M1.7
  (``ItemInventoryEntry``: family + facets + canonical name);
* ``item`` entries (检测项目) match the individual properties of a group.

Dictionaries without categories keep the flat item behaviour used by the
curated test fixture.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from ..contracts import (
    CanonicalMatch,
    ItemInventoryEntry,
    PropertyMatch,
)
from ..tablegrid.normalize import ELEMENTS
from .dictionary import DictionaryIndex
from .normalize import normalize_item_name, similarity

IDENTITY_DIMS = ("temperature", "impact_type", "hardness_scale")
ALIAS_PATH = Path(__file__).resolve().parents[2] / "configs" / "column_aliases.json"
PAREN_RE = re.compile(r"[（(]([^）)]+)[）)]")
TRAILING_SYMBOL_RE = re.compile(r"([A-Za-z][A-Za-z0-9.]*)$")
COATING_PERFORMANCE_RE = re.compile(
    r"膜层|涂层|耐冲击性|耐盐雾|耐沸水|耐湿热|耐盐酸|耐硝酸|耐碱性|耐酸性|"
    r"耐洗涤剂|耐砂浆|耐候性|耐紫外光|耐溶剂|抗杯突|抗弯曲|抗变形破裂|抗热裂"
)
_PROPERTY_ALIASES: dict[str, tuple[str, ...]] | None = None


@dataclass
class _Candidate:
    entry: object
    score: float
    kind: str
    facet_state: str


def match_item(
    item: ItemInventoryEntry,
    index: DictionaryIndex,
    *,
    semantic: Callable[[str, str], float] | None = None,
    semantic_threshold: float = 0.90,
    edit_threshold: float = 0.85,
) -> CanonicalMatch:
    if index.has_categories:
        return _match_category(
            item,
            index,
            semantic=semantic,
            semantic_threshold=semantic_threshold,
        )
    return _match_item_entry(
        item,
        index,
        semantic=semantic,
        semantic_threshold=semantic_threshold,
        edit_threshold=edit_threshold,
    )


def _match_item_entry(
    item: ItemInventoryEntry,
    index: DictionaryIndex,
    *,
    semantic: Callable[[str, str], float] | None,
    semantic_threshold: float,
    edit_threshold: float,
) -> CanonicalMatch:
    version = index.dictionary.version
    raw = item.item_raw or item.item_canonical or ""
    names = _unique(
        [item.item_raw, item.item_canonical, item.item_raw or ""]
    )
    evidence = list(item.evidence)

    exact = _lookup(index.name_index, "item", names)
    if exact:
        chosen, state = _choose_by_facets(exact, item.facets)
        if chosen is None:
            return _ambiguous(raw, exact, version, evidence, "多个同名业务项目")
        if state == "conflict":
            return _ambiguous(raw, exact, version, evidence, "业务项目粒度冲突")
        return _match(raw, chosen, "exact", 1.0, version, evidence)

    aliases = _lookup(index.alias_index, "item", names)
    if aliases:
        chosen, state = _choose_by_facets(aliases, item.facets)
        if chosen is None:
            return _ambiguous(raw, aliases, version, evidence, "多个别名命中，需人工确认")
        if state == "conflict":
            return _ambiguous(raw, aliases, version, evidence, "别名命中但粒度冲突")
        return _match(raw, chosen, "alias", 0.98, version, evidence)

    family_entries = index.family_index.get(item.item_family, [])
    compatible = [
        (entry, _facet_state(item.facets, entry.facets))
        for entry in family_entries
    ]
    compatible = [(entry, state) for entry, state in compatible if state != "conflict"]
    if len(compatible) == 1:
        entry, state = compatible[0]
        if state == "ok":
            return _match(raw, entry, "granularity", 0.90, version, evidence)
        return _ambiguous(
            raw, [entry], version, evidence, "业务条目缺少粒度，需人工确认"
        )

    if semantic is not None:
        scored = [
            _Candidate(
                entry=entry,
                score=semantic(raw, entry.business_name),
                kind="semantic",
                facet_state=state,
            )
            for entry, state in compatible
            if state == "ok"
        ]
        scored.sort(key=lambda candidate: candidate.score, reverse=True)
        if scored and scored[0].score >= semantic_threshold:
            best = scored[0]
            if len(scored) > 1 and abs(scored[1].score - best.score) < 0.01:
                return _ambiguous(
                    raw,
                    [best.entry, scored[1].entry],
                    version,
                    evidence,
                    "语义分数接近，需人工确认",
                    score=best.score,
                )
            return _match(
                raw, best.entry, "semantic", best.score, version, evidence
            )

    if len(compatible) > 1:
        return _ambiguous(
            raw,
            [entry for entry, _ in compatible],
            version,
            evidence,
            "多个同 family 业务项目，需人工确认",
        )

    scored = [
        _Candidate(
            entry=entry,
            score=max(
                similarity(raw, entry.business_name),
                *[similarity(raw, alias) for alias in entry.aliases],
            ),
            kind="edit_distance",
            facet_state=state,
        )
        for entry, state in compatible
        if state == "ok"
    ]
    scored.sort(key=lambda candidate: candidate.score, reverse=True)
    if scored and scored[0].score >= edit_threshold:
        best = scored[0]
        return _ambiguous(
            raw,
            [best.entry],
            version,
            evidence,
            f"编辑距离 {best.score:.3f}，需人工确认",
            score=best.score,
        )

    return CanonicalMatch(
        raw=raw,
        match_type="new",
        score=0.0,
        dictionary_version=version,
        evidence=evidence,
        status="new",
        reason="业务词典无匹配",
    )


def _match_category(
    item: ItemInventoryEntry,
    index: DictionaryIndex,
    *,
    semantic: Callable[[str, str], float] | None,
    semantic_threshold: float,
) -> CanonicalMatch:
    version = index.dictionary.version
    raw = item.item_raw or item.item_canonical or ""
    names = _unique([item.item_raw, item.item_canonical])
    evidence = list(item.evidence)

    exact = _lookup_flat(index.category_name_index, names)
    if exact:
        chosen, state = _choose_by_facets(exact, item.facets)
        if chosen is None:
            return _ambiguous(raw, exact, version, evidence, "多个同名项目大类")
        if state == "conflict":
            return _ambiguous(raw, exact, version, evidence, "项目大类粒度冲突")
        return _match_category_entry(raw, chosen, "exact", 1.0, version, evidence)

    aliases = _lookup_flat(index.category_alias_index, names)
    if aliases:
        chosen, state = _choose_by_facets(aliases, item.facets)
        if chosen is None:
            return _ambiguous(raw, aliases, version, evidence, "多个项目大类别名命中")
        if state == "conflict":
            return _ambiguous(raw, aliases, version, evidence, "别名命中但粒度冲突")
        return _match_category_entry(raw, chosen, "alias", 0.98, version, evidence)

    if COATING_PERFORMANCE_RE.search(raw):
        # 膜层/涂层性能（耐盐雾腐蚀性、耐冲击性、抗弯曲性…）不是金属材料
        # 的晶间腐蚀、夏比冲击或弯曲大类；宁可保持未匹配，也不能改名。
        return CanonicalMatch(
            raw=raw,
            match_type="new",
            score=0.0,
            dictionary_version=version,
            evidence=evidence,
            status="new",
            reason="膜层性能项，无对应金属材料大类",
        )

    normalized_names = [normalize_item_name(name) for name in names]
    contained: list = []
    for entry in _category_entries(index):
        if _facet_state(item.facets, entry.facets) == "conflict":
            continue
        if _category_contained(entry, normalized_names):
            contained.append(entry)
    if len(contained) == 1:
        state = _facet_state(item.facets, contained[0].facets)
        reason = (
            None
            if state == "ok"
            else "业务大类未细分该粒度，按大类归并"
        )
        return _match_category_entry(
            raw,
            contained[0],
            "granularity",
            0.92 if state == "ok" else 0.86,
            version,
            evidence,
            reason=reason,
        )
    family_match = _match_by_family(item, index, raw, version, evidence)
    if family_match is not None:
        return family_match

    if len(contained) > 1:
        if semantic is None:
            return _ambiguous(
                raw, contained, version, evidence, "多个项目大类包含该名称，需人工确认"
            )
        pool = contained
    else:
        pool = _category_entries(index)

    if semantic is not None:
        scored = [
            _Candidate(
                entry=entry,
                score=semantic(raw, entry.business_name),
                kind="semantic",
                facet_state=_facet_state(item.facets, entry.facets),
            )
            for entry in pool
            if _facet_state(item.facets, entry.facets) != "conflict"
        ]
        scored.sort(key=lambda candidate: candidate.score, reverse=True)
        if scored and scored[0].score >= semantic_threshold:
            best = scored[0]
            if len(scored) > 1 and abs(scored[1].score - best.score) < 0.01:
                return _ambiguous(
                    raw,
                    [best.entry, scored[1].entry],
                    version,
                    evidence,
                    "语义分数接近，需人工确认",
                    score=best.score,
                )
            return _match_category_entry(
                raw, best.entry, "semantic", best.score, version, evidence
            )

    return CanonicalMatch(
        raw=raw,
        match_type="new",
        score=0.0,
        dictionary_version=version,
        evidence=evidence,
        status="new",
        reason="业务词典无匹配项目大类",
    )


def _family_category_names(item: ItemInventoryEntry) -> list[str]:
    """Map a detected family to the business category that owns it.

    Inspection checklists often split one big category (尺寸/表面质量/…) into
    many row-level items. Those rows must inherit the big category instead of
    becoming new categories under strict mode.
    """

    family = item.item_family
    label = f"{item.item_raw} {item.item_canonical or ''}"
    facets = item.facets or {}
    temperature = str(facets.get("temperature") or "")
    names: list[str] = []
    if family == "tensile":
        hot = "高温" in label or "高温" in temperature
        low = "低温" in label or "低温" in temperature
        if "缺口" in label:
            names.append("高温缺口拉伸" if hot else "室温缺口拉伸")
        elif hot:
            names.append("高温拉伸")
        elif low:
            names.append("低温拉伸")
        else:
            names.append("室温拉伸")
    elif family == "impact":
        if "耐冲击" not in label:
            # 膜层性能的"耐冲击性"是涂层指标，不是金属材料夏比冲击。
            names.append("夏比冲击")
    elif family == "hardness":
        scale = facets.get("hardness_scale")
        scaled = {
            "brinell": "布氏硬度",
            "rockwell": "洛氏硬度",
            "vickers": "维氏硬度",
        }.get(str(scale or ""))
        if scaled:
            names.append(scaled)
        for key in ("布氏", "洛氏", "维氏"):
            if key in label:
                names.append(f"{key}硬度")
    elif family == "chemical_composition":
        names.append("化学成分")
    elif family == "dimension":
        names.append("尺寸")
    elif family == "surface":
        names.append("表面质量")
    elif family == "bend":
        names.append("弯曲")
    elif family == "ndt":
        if "渗透" in label or "荧光" in label:
            names.append("渗透检测")
        elif "射线" in label:
            names.append("射线检测")
        else:
            names.append("超声波检测")
    elif family == "metallography":
        for key, name in (
            ("低倍", "低倍"),
            ("高倍", "高倍组织"),
            ("显微", "高倍组织"),
            ("晶粒度", "晶粒度"),
            ("夹杂", "非金属夹杂"),
            ("脱碳", "脱碳层"),
            ("断口", "断口"),
            ("塔形", "塔形"),
            ("α", "α层"),
        ):
            if key in label:
                names.append(name)
    elif family == "stress_rupture":
        if "蠕变" in label:
            names.append("蠕变")
        elif "缺口" in label:
            names.append("缺口持久")
        elif "高温" in label or "高温" in temperature:
            names.append("高温光滑持久")
        else:
            names.append("室温持久")
    elif family == "fatigue":
        if "裂纹扩展" in label:
            names.append("裂纹扩展速率")
        elif "低周" in label or "低循环" in label:
            names.append("低周疲劳")
        elif "高周" in label:
            names.append("高周疲劳")
        else:
            names.append("应力疲劳")
    elif family == "corrosion":
        # Only an intergranular item may borrow the 晶间腐蚀 category; 剥落/
        # 应力/盐雾等机理各有自己的大类或应保持未匹配，不能被改名。
        if "晶间" in label:
            names.append("晶间腐蚀")
    elif family == "hardenability":
        names.append("淬透性")
    elif family == "creep":
        names.append("蠕变")
    elif family == "marking":
        names.append("产品标识")
    elif family == "shear":
        names.append("剪切")
    return [name for name in names if name]


def _keyword_category_names(item: ItemInventoryEntry) -> list[str]:
    """Map checklist rows with unknown family by business keywords."""

    label = f"{item.item_raw} {item.item_canonical or ''}"
    names: list[str] = []
    if "持久" in label:
        if "高温" in label:
            names.append("高温光滑持久")
        elif "缺口" in label:
            names.append("缺口持久")
        elif "蠕变" in label:
            names.append("蠕变")
        else:
            names.append("室温持久")
    if "硬度" in label:
        properties = " ".join(item.properties or [])
        if any(key in properties for key in ("HBW", "HB", "布氏")):
            names.append("布氏硬度")
        elif any(key in properties for key in ("HRC", "HRB", "洛氏")):
            names.append("洛氏硬度")
        elif any(key in properties for key in ("HV", "维氏")):
            names.append("维氏硬度")
    if any(
        key in label
        for key in (
            "划伤", "粗糙度", "表面", "外观", "锐边", "磕碰", "锈蚀",
            "清洁", "清洗", "毛刺", "压痕", "裂纹", "折叠", "结疤",
        )
    ):
        names.append("表面质量")
    if any(
        key in label
        for key in (
            "尺寸", "直径", "宽度", "深度", "高度", "长度", "厚度",
            "圆角", "倒角", "跳动", "止口", "法兰", "退刀槽", "轴颈",
            "中心孔", "外圆", "内径", "外径", "同轴", "圆度", "平面度",
            "平行度", "垂直度", "位置度", "角度", "轮廓", "间距", "间隙",
            "偏心", "直线度",
        )
    ):
        names.append("尺寸")
    if any(key in label for key in ("标识", "标记", "钢印", "打字")):
        names.append("产品标识")
    if any(key in label for key in ("渗透", "荧光")):
        names.append("渗透检测")
    elif any(key in label for key in ("射线",)):
        names.append("射线检测")
    elif "超声" in label:
        names.append("超声波检测")
    return names


def _match_by_family(
    item: ItemInventoryEntry,
    index: DictionaryIndex,
    raw: str,
    version: str,
    evidence: list[str],
) -> CanonicalMatch | None:
    candidates = [*_family_category_names(item), *_keyword_category_names(item)]
    for name in candidates:
        entries: dict[str, object] = {}
        for entry in index.category_name_index.get(
            normalize_item_name(name), []
        ):
            entries[entry.business_code] = entry
        for entry in index.category_alias_index.get(
            normalize_item_name(name), []
        ):
            entries[entry.business_code] = entry
        if not entries:
            continue
        pool = list(entries.values())
        chosen, state = _choose_by_facets(pool, item.facets)
        if chosen is None or state == "conflict":
            continue
        return _match_category_entry(
            raw,
            chosen,
            "granularity",
            0.9,
            version,
            evidence,
            reason="按检测族/关键词归并到业务大类",
        )
    return None


def match_property(
    prop: str,
    index: DictionaryIndex,
    *,
    category_code: str | None = None,
    category_name: str | None = None,
    evidence: list[str] | None = None,
) -> PropertyMatch:
    """Match one detected property against the 检测项目 dictionary."""

    version = index.dictionary.version
    evidence = evidence or []
    raw = prop or ""
    scoped = _category_items(index, category_code, category_name)

    variants = _unique([raw, *property_aliases(raw)])
    ranked: dict[str, tuple[object, float]] = {}
    for variant in variants:
        key = normalize_item_name(variant)
        for entry in index.name_index.get(("item", key), []):
            _rank_property(
                ranked,
                entry,
                1.0
                if normalize_item_name(entry.business_name) == normalize_item_name(raw)
                else 0.95,
            )
        for entry in index.alias_index.get(("item", key), []):
            if variant == raw and normalize_item_name(raw) in _symbols(
                entry.business_name
            ):
                score = 0.99
            elif variant == raw and _trailing_symbol(entry.business_name) == (
                normalize_item_name(raw)
            ):
                score = 0.985
            else:
                score = 0.98 if variant == raw else 0.93
            _rank_property(ranked, entry, score)

    all_candidates = list(ranked.values())
    if raw.strip() in ELEMENTS:
        # Single element symbols belong to 化学成分 whatever table they were
        # bound to (a stray "N" in a tensile block is nitrogen, not cycles).
        candidates = [
            item
            for item in all_candidates
            if item[0].family == "chemical_composition"
        ]
    elif scoped is not None:
        allowed = {entry.business_code for entry in scoped}
        candidates = [
            item for item in all_candidates if item[0].business_code in allowed
        ]
    else:
        candidates = all_candidates

    if not candidates:
        # Deterministic semantic fallback: stay inside the matched category
        # when a category is known, otherwise search all active items.
        pool = (
            scoped
            if scoped is not None
            else [
                entry
                for entry in index.dictionary.entries
                if entry.type == "item" and entry.status == "active"
            ]
        )
        for entry in pool or []:
            scores = [similarity(raw, entry.business_name)] + [
                similarity(raw, alias) for alias in entry.aliases
            ]
            score = max(scores)
            if score >= 0.88:
                _rank_property(ranked, entry, round(score, 4))
        candidates = list(ranked.values())

    if not candidates:
        return PropertyMatch(
            raw=raw,
            match_type="new",
            dictionary_version=version,
            category_code=category_code,
            category_name=category_name,
            status="new",
            reason="业务词典无匹配检测项目",
        )

    candidates.sort(
        key=lambda item: (-item[1], *_entry_tie_key(item[0]))
    )
    best_entry, best_score = candidates[0]
    ties = [
        item for item in candidates if abs(item[1] - best_score) < 1e-9
    ]
    if len(ties) > 1:
        names = {normalize_item_name(entry.business_name) for entry, _ in ties}
        if len(names) == 1:
            return PropertyMatch(
                raw=raw,
                canonical_id=best_entry.business_code,
                canonical_name=best_entry.business_name,
                match_type="exact" if best_score >= 1.0 else "alias",
                score=best_score,
                category_code=best_entry.category_code or category_code,
                category_name=best_entry.category_name or category_name,
                dictionary_version=version,
                status="matched",
                reason=f"同名多条（{len(ties)}），按编码排序取首条",
            )
        return PropertyMatch(
            raw=raw,
            canonical_id=best_entry.business_code,
            canonical_name=best_entry.business_name,
            match_type="ambiguous",
            score=best_score,
            category_code=best_entry.category_code or category_code,
            category_name=best_entry.category_name or category_name,
            dictionary_version=version,
            status="ambiguous",
            reason="多个检测项目同名/同符号，需人工确认",
        )

    second = candidates[1] if len(candidates) > 1 else None
    if second is not None and abs(best_score - second[1]) < 0.004:
        return PropertyMatch(
            raw=raw,
            canonical_id=best_entry.business_code,
            canonical_name=best_entry.business_name,
            match_type="ambiguous",
            score=best_score,
            category_code=best_entry.category_code or category_code,
            category_name=best_entry.category_name or category_name,
            dictionary_version=version,
            status="ambiguous",
            reason="多个检测项目分数接近，需人工确认",
        )
    return PropertyMatch(
        raw=raw,
        canonical_id=best_entry.business_code,
        canonical_name=best_entry.business_name,
        match_type="exact" if best_score >= 1.0 else "alias",
        score=round(best_score, 4),
        category_code=best_entry.category_code or category_code,
        category_name=best_entry.category_name or category_name,
        dictionary_version=version,
        status="matched",
    )


def _lookup(index: dict, entry_type: str, names: list[str]) -> list:
    found = []
    seen = set()
    for name in names:
        key = (entry_type, normalize_item_name(name))
        for entry in index.get(key, []):
            if entry.business_code in seen:
                continue
            seen.add(entry.business_code)
            found.append(entry)
    return found


def _choose_by_facets(entries: list, item_facets: dict) -> tuple:
    if len(entries) == 1:
        state = _facet_state(item_facets, entries[0].facets)
        return entries[0], state
    ranked = [
        (entry, _facet_state(item_facets, entry.facets)) for entry in entries
    ]
    ranked = [(entry, state) for entry, state in ranked if state != "conflict"]
    if len(ranked) == 1:
        return ranked[0]
    if not ranked:
        return None, "conflict"
    return None, "ambiguous"


def _facet_state(item_facets: dict, entry_facets: dict) -> str:
    missing = False
    for dim in IDENTITY_DIMS:
        value = item_facets.get(dim)
        if not value:
            continue
        allowed = entry_facets.get(dim)
        if not allowed:
            missing = True
            continue
        normalized = {normalize_item_name(candidate) for candidate in allowed}
        if normalize_item_name(value) not in normalized:
            return "conflict"
    return "missing" if missing else "ok"


def _match(raw: str, entry, kind: str, score: float, version: str, evidence: list) -> CanonicalMatch:
    return CanonicalMatch(
        raw=raw,
        canonical_id=entry.business_code,
        canonical_name=entry.business_name,
        match_type=kind,
        score=round(score, 4),
        dictionary_version=version,
        evidence=evidence,
        status="matched",
    )


def _ambiguous(
    raw: str,
    entries: list,
    version: str,
    evidence: list,
    reason: str,
    score: float = 0.0,
) -> CanonicalMatch:
    first = entries[0] if entries else None
    return CanonicalMatch(
        raw=raw,
        canonical_id=first.business_code if first else None,
        canonical_name=first.business_name if first else None,
        match_type="ambiguous",
        score=round(score, 4),
        dictionary_version=version,
        evidence=evidence,
        status="ambiguous",
        reason=reason,
    )


def _unique(values: list) -> list[str]:
    result: list[str] = []
    for value in values:
        text = value or ""
        if text and text not in result:
            result.append(text)
    return result


def _lookup_flat(index: dict, names: list[str]) -> list:
    found = []
    seen = set()
    for name in names:
        for entry in index.get(normalize_item_name(name), []):
            if entry.business_code in seen:
                continue
            seen.add(entry.business_code)
            found.append(entry)
    return found


def _category_entries(index: DictionaryIndex) -> list:
    seen: set[str] = set()
    entries = []
    for group in (
        *index.category_name_index.values(),
        *index.category_alias_index.values(),
    ):
        for entry in group:
            if entry.business_code in seen:
                continue
            seen.add(entry.business_code)
            entries.append(entry)
    return entries


def _category_contained(entry, raw_names: list[str]) -> bool:
    candidates = [entry.business_name, *entry.aliases]
    for index, candidate in enumerate(candidates):
        entry_name = normalize_item_name(candidate)
        if len(entry_name) < 2:
            continue
        for raw_name in raw_names:
            if not _contains(entry_name, raw_name):
                continue
            if index == 0 and len(entry_name) < 3 and similarity(raw_name, entry_name) < 0.6:
                # Short category names ("弯曲", "硬度") appear inside unrelated
                # words ("弯曲度"); require a closer match for those.
                continue
            return True
    return False


def _contains(entry_name: str, raw_name: str) -> bool:
    if len(entry_name) < 2 or len(raw_name) < 2:
        return False
    return entry_name in raw_name or raw_name in entry_name


def _match_category_entry(
    raw: str,
    entry,
    kind: str,
    score: float,
    version: str,
    evidence: list,
    reason: str | None = None,
) -> CanonicalMatch:
    return CanonicalMatch(
        raw=raw,
        canonical_id=entry.business_code,
        canonical_name=entry.business_name,
        match_type=kind,
        score=round(score, 4),
        dictionary_version=version,
        evidence=evidence,
        status="matched",
        reason=reason,
        category_code=entry.business_code,
        category_name=entry.business_name,
    )


def property_aliases(prop: str) -> tuple[str, ...]:
    global _PROPERTY_ALIASES
    if _PROPERTY_ALIASES is None:
        try:
            data = json.loads(ALIAS_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
        _PROPERTY_ALIASES = {
            key: tuple(value)
            for key, value in data.get("property_aliases", {}).items()
        }
    return _PROPERTY_ALIASES.get(prop, ())


def _rank_property(ranked: dict, entry, score: float) -> None:
    current = ranked.get(entry.business_code)
    if current is None or score > current[1]:
        ranked[entry.business_code] = (entry, score)


def _symbols(name: str) -> set[str]:
    return {
        normalize_item_name(match.group(1))
        for match in PAREN_RE.finditer(name or "")
    }


def _trailing_symbol(name: str) -> str | None:
    base = (name or "").split("/")[0].strip()
    match = TRAILING_SYMBOL_RE.search(base)
    if not match:
        return None
    if match.start() > 0 and base[match.start() - 1].isspace():
        # "裂纹长度 a" is a name plus a separate label, not a trailing symbol.
        return None
    if not re.search(r"[\u4e00-\u9fff]", base[: match.start()]):
        return None
    return normalize_item_name(match.group(1))


def _category_items(
    index: DictionaryIndex,
    category_code: str | None,
    category_name: str | None,
) -> list | None:
    if category_code:
        entries = index.item_by_category.get(category_code)
        if entries:
            return entries
    if not category_name:
        return None
    entries = [
        entry
        for entry in index.dictionary.entries
        if entry.status == "active"
        and entry.type == "item"
        and entry.category_name == category_name
    ]
    return entries or None


def _code_order(code: str) -> tuple:
    match = re.search(r"(\d+)$", code or "")
    return (int(match.group(1)) if match else 10**9, code)


def _entry_tie_key(entry) -> tuple:
    """Prefer room-temperature categories when a measure names both RT/HT."""

    category = entry.category_name or ""
    if "室温" in category:
        temperature = 0
    elif "高温" in category or "低温" in category:
        temperature = 2
    else:
        temperature = 1
    return (temperature, *_code_order(entry.business_code))
