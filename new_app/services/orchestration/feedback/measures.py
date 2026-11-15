"""Shared measure-header normalisation for intent and context building."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

MEASURE_HEADERS: dict[str, str] = {
    "rm": "Rm", "抗拉强度": "Rm", "拉伸强度": "Rm", "tensile strength": "Rm",
    "rp0.2": "Rp0.2", "屈服强度": "Rp0.2", "规定塑性延伸强度": "Rp0.2",
    "yield strength": "Rp0.2", "proof strength": "Rp0.2",
    "rel": "ReL", "reh": "ReH",
    "a": "A", "断后伸长率": "A", "伸长率": "A", "延伸率": "A",
    "elongation": "A",
    "z": "Z", "断面收缩率": "Z", "收缩率": "Z", "reduction of area": "Z",
    "kv2": "KV2", "ku2": "KU2", "冲击吸收能量": "KV2", "冲击功": "KV2",
    "impact energy": "KV2",
    "hb": "HB", "hbw": "HBW", "布氏硬度": "HBW", "brinell": "HBW",
    "hrc": "HRC", "洛氏硬度": "HRC", "rockwell": "HRC",
    "hrb": "HRB", "hv": "HV", "维氏硬度": "HV", "vickers": "HV",
    "e": "E", "弹性模量": "E", "elastic modulus": "E",
    "c": "C", "si": "Si", "mn": "Mn", "p": "P", "s": "S", "cr": "Cr",
    "ni": "Ni", "mo": "Mo", "cu": "Cu", "al": "Al", "ti": "Ti", "v": "V",
    "nb": "Nb", "w": "W", "b": "B", "n": "N", "o": "O", "h": "H",
    "fe": "Fe", "zr": "Zr",
}

# Units / suffix noise that must not hide a measure token.
_NOISE_RE = re.compile(r"[（(].*?[)）]|[%％]|mpa|gpa|j\b|hbw?|hr[abc]|hv", re.IGNORECASE)


def normalize(text: Any) -> str:
    value = unicodedata.normalize("NFKC", str(text or "")).lower()
    return re.sub(r"\s+", "", value)


def canonical_measure(header: Any) -> str:
    """Map a printed header/cell to the canonical measure symbol, or ''."""
    text = normalize(header)
    if not text:
        return ""
    if text in MEASURE_HEADERS:
        return MEASURE_HEADERS[text]
    cleaned = _NOISE_RE.sub("", text)
    if cleaned in MEASURE_HEADERS:
        return MEASURE_HEADERS[cleaned]
    tokens = re.findall(r"[a-z0-9.]+|[\u4e00-\u9fff]+", cleaned)
    for token in tokens:
        if token in MEASURE_HEADERS:
            return MEASURE_HEADERS[token]
    return ""


def measure_tokens(headers: list[str]) -> set[str]:
    return {measure for header in headers if (measure := canonical_measure(header))}
