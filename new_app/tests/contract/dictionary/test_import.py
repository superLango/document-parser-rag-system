from __future__ import annotations

import json

import pytest

from services.orchestration.dictionary import api as dictionary_api


@pytest.fixture()
def data_file(tmp_path, monkeypatch):
    path = tmp_path / "business_dictionary.json"
    path.write_text(
        json.dumps(
            {
                "version": "test-v1",
                "source": "test",
                "stats": {"entries": 1},
                "entries": [
                    {
                        "business_code": "ITEM:1",
                        "business_name": "抗拉强度",
                        "type": "item",
                        "family": "tensile",
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(dictionary_api, "DATA_FILE", path)
    return path


def test_import_merges_and_skips_invalid(data_file):
    result = dictionary_api.import_entries(
        dictionary_api.DictionaryImport(
            entries=[
                {
                    "business_code": "ITEM:1",
                    "business_name": "抗拉强度（更新）",
                    "type": "item",
                },
                {"business_code": "ITEM:2", "business_name": "屈服强度", "type": "item"},
                {"business_code": "", "business_name": "缺编码", "type": "item"},
            ]
        )
    )

    assert result["created"] == 1
    assert result["updated"] == 1
    assert result["skipped"] == 1
    assert result["total"] == 2

    payload = json.loads(data_file.read_text(encoding="utf-8"))
    names = {item["business_code"]: item["business_name"] for item in payload["entries"]}
    assert names["ITEM:1"] == "抗拉强度（更新）"
    assert names["ITEM:2"] == "屈服强度"


def test_import_replace_keeps_only_uploaded_entries(data_file):
    result = dictionary_api.import_entries(
        dictionary_api.DictionaryImport(
            entries=[
                {"business_code": "ITEM:9", "business_name": "硬度", "type": "item"}
            ],
            replace=True,
        )
    )

    assert result["total"] == 1
    payload = json.loads(data_file.read_text(encoding="utf-8"))
    assert [item["business_code"] for item in payload["entries"]] == ["ITEM:9"]


def test_import_rejects_empty_payload(data_file):
    with pytest.raises(dictionary_api.HTTPException) as exc:
        dictionary_api.import_entries(dictionary_api.DictionaryImport(entries=[]))
    assert exc.value.status_code == 400
