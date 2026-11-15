"""P1-12 edition profile, drift analysis and adaptation levels."""

import pytest

from services.adaptation import (
    AdaptationController,
    AdaptationLevel,
    DriftAnalyzer,
    EditionStore,
)
from services.adaptation.candidate import (
    build_code_candidate,
    build_recipe_candidate,
    list_candidates,
    load_candidate,
    save_candidate,
)
from services.adaptation.models import DriftItem, DriftKind, DriftReport
from services.adaptation.profile import resolve_standard


def _table(caption: str, profile: str, headers: list[str]) -> dict:
    return {
        "caption": caption,
        "profile": profile,
        "header_paths": [[header] for header in headers],
        "n_cols": len(headers),
    }


def _ocr(tables: list[dict]) -> dict:
    return {"pages": [{"page_no": 1}], "tables": tables}


MECHANICAL = _table(
    "表1 力学性能", "mechanical_properties", ["牌号", "抗拉强度 Rm/MPa", "断后伸长率 A/%"]
)
CHEMICAL = _table(
    "表2 化学成分", "chemical_composition", ["牌号", "C", "Si", "Mn"]
)


def _profile(store: EditionStore):
    return store.build(
        "GB/T 1591",
        "2018",
        _ocr([MECHANICAL, CHEMICAL]),
        document_sha256="abc",
        page_count=22,
        sample_doc_id="gbt-1591-2018",
        recipe_pins={"mechanical_properties_v1": "1.6.51"},
    )


def test_profile_roundtrip(tmp_path) -> None:
    store = EditionStore(tmp_path)
    profile = _profile(store)
    store.save(profile)
    loaded = store.get("GB/T 1591", "2018")
    assert loaded is not None
    assert loaded.recipe_pins == {"mechanical_properties_v1": "1.6.51"}
    assert loaded.tables[0].header_signature[1] == "抗拉强度rm/mpa"
    assert loaded.tables[0].measures == ["抗拉强度", "rm", "断后伸长率", "a"]
    assert [item["edition"] for item in store.list()] == ["2018"]


def test_identical_edition_has_no_drift(tmp_path) -> None:
    store = EditionStore(tmp_path)
    profile = _profile(store)
    report = DriftAnalyzer().compare(profile, _ocr([MECHANICAL, CHEMICAL]))
    assert report.drifts == []
    assert report.score == 1.0
    assert AdaptationController(store).plan(report).level == AdaptationLevel.L0_NONE


def test_header_only_change_is_l1(tmp_path) -> None:
    store = EditionStore(tmp_path)
    profile = _profile(store)
    renamed = _table(
        "表1 力学性能",
        "mechanical_properties",
        ["牌号", "抗拉强度 Rm/MPa（修订）", "断后伸长率 A/%"],
    )
    report = DriftAnalyzer().compare(profile, _ocr([renamed, CHEMICAL]))
    kinds = {item.kind.value for item in report.drifts}
    assert kinds == {"header_changed"}
    plan = AdaptationController(store).plan(report)
    assert plan.level == AdaptationLevel.L1_PROFILE_PATCH
    assert not plan.requires_human


def test_measure_loss_needs_sandbox_and_human(tmp_path) -> None:
    store = EditionStore(tmp_path)
    profile = _profile(store)
    reduced = _table(
        "表1 力学性能", "mechanical_properties", ["牌号", "抗拉强度 Rm/MPa"]
    )
    report = DriftAnalyzer().compare(profile, _ocr([reduced, CHEMICAL]))
    assert any(item.kind.value == "measure_lost" for item in report.drifts)
    plan = AdaptationController(store).plan(report)
    assert plan.level == AdaptationLevel.L2_RECIPE_CANDIDATE
    assert plan.requires_sandbox and plan.requires_human


def test_missing_table_escalates_to_l3(tmp_path) -> None:
    store = EditionStore(tmp_path)
    profile = _profile(store)
    report = DriftAnalyzer().compare(profile, _ocr([MECHANICAL]))
    assert any(item.kind.value == "missing_table" for item in report.drifts)
    assert report.score == 0.5
    plan = AdaptationController(store).plan(report)
    assert plan.level == AdaptationLevel.L3_CODE_CANDIDATE
    assert plan.requires_sandbox and plan.requires_human


def test_apply_l1_refreshes_signatures_and_keeps_pins(tmp_path) -> None:
    store = EditionStore(tmp_path)
    profile = _profile(store)
    store.save(profile)
    renamed = _table(
        "表1 力学性能",
        "mechanical_properties",
        ["牌号", "抗拉强度 Rm/MPa（修订）", "断后伸长率 A/%"],
    )
    ocr = _ocr([renamed, CHEMICAL])
    report = DriftAnalyzer().compare(profile, ocr)
    updated = AdaptationController(store).apply_l1(profile, report, ocr)
    assert "抗拉强度rm/mpa(修订)" in updated.tables[0].header_signature
    assert updated.recipe_pins == profile.recipe_pins
    assert store.get("GB/T 1591", "2018") is not None


def test_apply_l1_rejects_higher_levels(tmp_path) -> None:
    store = EditionStore(tmp_path)
    profile = _profile(store)
    report = DriftAnalyzer().compare(profile, _ocr([MECHANICAL]))
    with pytest.raises(ValueError):
        AdaptationController(store).apply_l1(profile, report, _ocr([MECHANICAL]))


def test_recipe_candidate_adds_aliases_and_conditions(tmp_path) -> None:
    base = {
        "recipe_id": "mechanical_properties_v1",
        "version": "1.6.53",
        "profile": "mechanical_properties",
        "bindings": {
            "measures": {"Rm": {"unit": "MPa"}, "A": {"unit": "%"}},
            "conditions": ["牌号"],
        },
        "rules": {},
        "tests": ["tests/contract/recipes/test_recipe_contract.py"],
    }
    report = DriftReport(
        standard_id="GB/T 1591",
        edition="2025",
        expected_tables=1,
        matched_tables=1,
        drifts=[
            DriftItem(
                kind=DriftKind.MEASURE_LOST,
                table="表1",
                detail="抗拉强度, a, 未知量",
                severity="error",
            ),
            DriftItem(
                kind=DriftKind.HEADER_CHANGED,
                table="表1",
                detail="新表头",
                severity="warning",
            ),
        ],
    )
    candidate = build_recipe_candidate("GB/T 1591", "2025", base, report)
    assert candidate.candidate_version == "1.6.54"
    assert "抗拉强度" in candidate.manifest["bindings"]["measures"]["Rm"]["aliases"]
    assert "a" in candidate.manifest["bindings"]["measures"]["A"]["aliases"]
    assert "新表头" in candidate.manifest["bindings"]["conditions"]
    assert candidate.unresolved == ["未知量"]
    assert candidate.manifest["tests"]
    path = save_candidate(candidate, tmp_path)
    loaded = load_candidate(path)
    assert loaded.candidate_id == candidate.candidate_id
    assert [item["candidate_id"] for item in list_candidates(tmp_path)] == [
        candidate.candidate_id
    ]


def test_code_candidate_records_missing_tables() -> None:
    report = DriftReport(
        standard_id="GB/T 1591",
        edition="2025",
        expected_tables=2,
        matched_tables=0,
        drifts=[
            DriftItem(kind=DriftKind.MISSING_TABLE, table="表1", severity="error"),
            DriftItem(kind=DriftKind.NEW_TABLE, table="表9", severity="info"),
        ],
    )
    candidate = build_code_candidate("GB/T 1591", "2025", report)
    assert candidate.level == AdaptationLevel.L3_CODE_CANDIDATE
    assert candidate.diff["missing_tables"] == ["表1"]
    assert candidate.requires_sandbox and candidate.requires_human
    assert len(candidate.verification) >= 3


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("GBT 1591-2018.pdf", ("GB/T 1591", "2018")),
        ("GBT-24627-2023.pdf", ("GB/T 24627", "2023")),
        ("v43-gbt-24627-2023.pdf", ("GB/T 24627", "2023")),
        ("GB 24627-2023.pdf", ("GB 24627", "2023")),
        ("ASTM B861-24.pdf", ("ASTM B861", "24")),
        ("AMS 4050K.pdf", ("AMS 4050", "K")),
        ("ASME SB265-2025.pdf", ("ASME SB265", "2025")),
        ("ISO 5832-3-2021.pdf", ("ISO 5832-3", "2021")),
        ("扫描件-无标准号.pdf", None),
    ],
)
def test_resolve_standard_from_filename(filename, expected) -> None:
    assert resolve_standard(filename) == expected
