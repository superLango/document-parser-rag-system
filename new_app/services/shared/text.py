import re

_FULLWIDTH_DIGITS = str.maketrans("０１２３４５６７８９", "0123456789")


def clean_text(raw: str | None) -> str:
    """Deterministic text normalization shared by OCR and recipe matching."""
    if raw is None:
        return ""
    text = str(raw).translate(_FULLWIDTH_DIGITS)
    replacements = {
        "％": "%",
        "．": ".",
        "～": "~",
        "≦": "≤",
        "≧": "≥",
        "＜": "<",
        "＞": ">",
        "—": "-",
        "–": "-",
        "－": "-",
        "＋": "+",
        "\u00a0": " ",
        "\u3000": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = text.replace("$", "")
    text = re.sub(r"\\mathrm\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\\sigma\s*_?\{?([^{}\s]*)\}?", r"σ\1", text)
    text = re.sub(r"\\delta\s*_?\{?([^{}\s]*)\}?", r"δ\1", text)
    text = re.sub(r"\\psi\s*_?\{?([^{}\s]*)\}?", r"ψ\1", text)
    text = re.sub(r"\\phi\s*_?\{?([^{}\s]*)\}?", r"φ\1", text)
    text = text.replace("\\geqslant", "≥").replace("\\leqslant", "≤")
    text = re.sub(r"\\geq(?![a-zA-Z])", "≥", text)
    text = re.sub(r"\\leq(?![a-zA-Z])", "≤", text)
    text = text.replace("{", "").replace("}", "").replace("^", "").replace("_", "")
    text = text.replace("\\", "")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"(\d+\.\d+)\s+(\d+)", r"\1\2", text)
    return text
