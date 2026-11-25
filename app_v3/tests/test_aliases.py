from __future__ import annotations

from app_v3.normalize.aliases import extract_document_aliases, extract_state_aliases


def test_extract_state_aliases_basic():
    aliases = extract_state_aliases("软态(M)、热加工态(R)、冷加工态(Y)、半硬态(Y2)、固溶退火态(ST)")
    assert aliases["M"] == "软态(M)"
    assert aliases["R"] == "热加工态(R)"
    assert aliases["Y"] == "冷加工态(Y)"
    assert aliases["Y2"] == "半硬态(Y2)"
    assert aliases["ST"] == "固溶退火态(ST)"


def test_clean_prefixes():
    aliases = extract_state_aliases("及半硬态(Y2)；状态为软态(M)")
    assert aliases["Y2"] == "半硬态(Y2)"
    assert aliases["M"] == "软态(M)"


def test_document_aliases_merge():
    aliases = extract_document_aliases(["及半硬态(Y2)", "固溶退火态(ST)"])
    assert aliases["Y2"] == "半硬态(Y2)"
    assert aliases["ST"] == "固溶退火态(ST)"
