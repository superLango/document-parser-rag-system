from __future__ import annotations

import asyncio

from services.agent.tools.builtin import get_records, get_table


def _context() -> dict:
    return {
        "tables": [
            {
                "table_id": "T1",
                "page_no": 3,
                "caption": "表1 力学性能",
                "profile": "mechanical_properties",
                "orientation": "grade_rows",
                "header_paths": [["牌号", "Rm", "Rp0.2"]],
                "rows": [["牌号", "Rm", "Rp0.2"], ["Q355B", "470", "355"], ["Q355C", "480", "365"]],
            }
        ],
        "records": [
            {
                "record_id": "T1-R1",
                "table_id": "T1",
                "grade": "Q355B",
                "condition_key": "room",
                "properties": {"Rm": {"raw": "470", "unit": "MPa", "value": 470.0}},
                "source": {"table_id": "T1"},
            },
            {
                "record_id": "T1-R2",
                "table_id": "T1",
                "grade": "Q355C",
                "condition_key": "room",
                "properties": {"Rm": {"raw": "480", "unit": "MPa", "value": 480.0}},
            },
        ],
    }


def test_get_table_returns_bounded_row_range() -> None:
    result = asyncio.run(get_table({"table_id": "T1", "offset": 1, "limit": 1}, _context()))
    assert result["table_id"] == "T1"
    assert result["headers"] == ["牌号", "Rm", "Rp0.2"]
    assert result["n_rows"] == 3
    assert result["rows"] == [["Q355B", "470", "355"]]
    assert result["has_more"] is True


def test_get_table_reports_available_ids() -> None:
    result = asyncio.run(get_table({"table_id": "T9"}, _context()))
    assert result["error"] == "table_not_found"
    assert "T1" in result["available_tables"]


def test_get_records_filters_and_compacts() -> None:
    result = asyncio.run(
        get_records({"table_id": "T1", "record_id": "T1-R1"}, _context())
    )
    assert result["count"] == 1
    assert result["records"][0]["record_id"] == "T1-R1"
    assert result["records"][0]["properties"]["Rm"]["unit"] == "MPa"
    assert "source" not in result["records"][0]
