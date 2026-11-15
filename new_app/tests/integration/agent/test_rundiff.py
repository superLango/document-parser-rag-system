from __future__ import annotations

from services.orchestration.rundiff import diff_runs


def _record(record_id: str, table: str = "T3", **props) -> dict:
    return {
        "record_id": record_id,
        "table_id": table,
        "grade": "Q355B",
        "properties": {
            key: {"value": value, "unit": "MPa", "operator": ">="}
            for key, value in props.items()
        },
    }


def _diag(code: str, table: str = "T3", block: str = "T3-B1") -> dict:
    return {"code": code, "detail": {"table_id": table, "block_id": block, "page_no": 4}}


def test_identical_runs_have_zero_diff() -> None:
    before = [_record("R1", Rm=470), _record("R2", Rm=485)]
    diff = diff_runs(before, before, [_diag("A")], [_diag("A")])
    assert diff["summary"] == {
        "records_before": 2,
        "records_after": 2,
        "records_added": 0,
        "records_removed": 0,
        "records_changed": 0,
        "fields_changed": 0,
        "diagnostics_before": 1,
        "diagnostics_after": 1,
        "diagnostics_added": 0,
        "diagnostics_removed": 0,
        "tables_before": 1,
        "tables_after": 1,
        "tables_added": 0,
        "tables_removed": 0,
    }


def test_added_and_removed_records() -> None:
    before = [_record("R1", Rm=470), _record("R2", Rm=485)]
    after = [_record("R2", Rm=485), _record("R3", Rm=500)]
    diff = diff_runs(before, after)
    assert diff["records_added"] == ["R3"]
    assert diff["records_removed"] == ["R1"]
    assert diff["summary"]["records_added"] == 1
    assert diff["summary"]["records_removed"] == 1


def test_changed_field_reports_before_and_after() -> None:
    before = [_record("R1", Rm=470, A=22)]
    after = [_record("R1", Rm=480, A=22)]
    diff = diff_runs(before, after)
    assert diff["summary"]["records_changed"] == 1
    assert diff["summary"]["fields_changed"] == 1
    field = diff["fields"][0]
    assert field["record_id"] == "R1"
    assert field["measure"] == "Rm"
    assert field["before"]["value"] == 470
    assert field["after"]["value"] == 480


def test_unit_change_is_a_field_change() -> None:
    before = [_record("R1", Rm=470)]
    after = [_record("R1", Rm=470)]
    after[0]["properties"]["Rm"]["unit"] = "ksi"
    diff = diff_runs(before, after)
    assert diff["summary"]["fields_changed"] == 1
    assert diff["fields"][0]["before"]["unit"] == "MPa"


def test_diagnostics_added_and_removed() -> None:
    before = [_diag("A"), _diag("B", table="T4")]
    after = [_diag("A"), _diag("C", table="T4")]
    diff = diff_runs([], [], before, after)
    assert diff["summary"]["diagnostics_added"] == 1
    assert diff["summary"]["diagnostics_removed"] == 1
    assert diff["diagnostics_added"][0][0] == "C"
    assert diff["diagnostics_removed"][0][0] == "B"


def test_table_added_and_removed() -> None:
    before = [_record("R1", table="T3")]
    after = [_record("R1", table="T4")]
    diff = diff_runs(before, after)
    assert diff["summary"]["tables_added"] == 1
    assert diff["summary"]["tables_removed"] == 1
    assert diff["tables"]["after"] == ["T4"]
