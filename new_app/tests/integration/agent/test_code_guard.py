from __future__ import annotations

from hanson_contracts import CodeFile, CodePatch, RepairProposal

from services.agent.agents.repair import _parse_repair
from services.code_guard import (
    CodeGuardLimits,
    apply_code_gate,
    validate_code_patch,
)


def _patch(*files: CodeFile) -> CodePatch:
    return CodePatch(base_version="1.0.0", files=list(files))


def _file(
    path: str,
    content: str,
    *,
    status: str = "added",
    diff: str = "",
) -> CodeFile:
    return CodeFile(path=path, content=content, status=status, diff=diff)  # type: ignore[arg-type]


def _valid_patch() -> CodePatch:
    return _patch(
        _file("strategies.py", "VALUE = 1\n"),
        _file("test_strategies.py", "def test_value():\n    assert 1 == 1\n"),
    )


def _codes(report) -> set[str]:
    return {item.code for item in report.violations}


def test_valid_patch_passes() -> None:
    report = validate_code_patch(_valid_patch())
    assert report.passed is True
    assert report.stats["files"] == 2
    assert report.stats["test_files"] == 1


def test_file_count_limit() -> None:
    patch = _patch(
        _file("a.py", "A = 1\n"),
        _file("b.py", "B = 2\n"),
        _file("c.py", "C = 3\n"),
        _file("d.py", "D = 4\n"),
        _file("test_a.py", "def test_a():\n    assert True\n"),
    )
    report = validate_code_patch(patch)
    assert "FILE_LIMIT" in _codes(report)
    assert report.passed is False


def test_file_line_limit() -> None:
    content = "\n".join(f"X{i} = {i}" for i in range(801)) + "\n"
    report = validate_code_patch(
        _patch(
            _file("big.py", content),
            _file("test_big.py", "def test_big():\n    assert True\n"),
        )
    )
    assert "FILE_TOO_LARGE" in _codes(report)


def test_patch_line_limit() -> None:
    diff = "\n".join(f"+X{i} = {i}" for i in range(151))
    report = validate_code_patch(
        _patch(
            _file("strategies.py", "X = 1\n", status="modified", diff=diff),
            _file("test_strategies.py", "def test_x():\n    assert True\n"),
        )
    )
    assert "PATCH_TOO_LARGE" in _codes(report)


def test_modified_file_requires_diff() -> None:
    report = validate_code_patch(
        _patch(
            _file("strategies.py", "X = 1\n", status="modified"),
            _file("test_strategies.py", "def test_x():\n    assert True\n"),
        )
    )
    assert "DIFF_REQUIRED" in _codes(report)


def test_tests_required() -> None:
    report = validate_code_patch(_patch(_file("strategies.py", "X = 1\n")))
    assert "TESTS_REQUIRED" in _codes(report)


def test_test_file_must_define_test() -> None:
    report = validate_code_patch(
        _patch(
            _file("strategies.py", "X = 1\n"),
            _file("test_strategies.py", "VALUE = 1\n"),
        )
    )
    assert "TESTS_EMPTY" in _codes(report)


def test_hardcoded_document_id_rejected() -> None:
    content = 'DOC = "33fb1daa-2286-49de-80dd-f57910d880fe"\n'
    report = validate_code_patch(
        _patch(
            _file("strategies.py", content),
            _file("test_strategies.py", "def test_x():\n    assert True\n"),
        )
    )
    assert "HARDCODED_DOCUMENT" in _codes(report)


def test_hardcoded_filename_rejected() -> None:
    content = 'NAME = "AMS4108G.pdf"\n'
    report = validate_code_patch(
        _patch(
            _file("strategies.py", content),
            _file("test_strategies.py", "def test_x():\n    assert True\n"),
        )
    )
    assert "HARDCODED_DOCUMENT" in _codes(report)


def test_hardcoded_json_document_rejected() -> None:
    report = validate_code_patch(
        _patch(
            _file("rules.json", '{"name": "AMS4108G.pdf"}\n'),
            _file("test_rules.py", "def test_rules():\n    assert True\n"),
        )
    )
    assert "HARDCODED_DOCUMENT" in _codes(report)


def test_forbidden_module_rejected() -> None:
    content = "import subprocess\n"
    report = validate_code_patch(
        _patch(
            _file("strategies.py", content),
            _file("test_strategies.py", "def test_x():\n    assert True\n"),
        )
    )
    assert "MODULE_FORBIDDEN" in _codes(report)


def test_non_stdlib_import_rejected() -> None:
    content = "import numpy\n"
    report = validate_code_patch(
        _patch(
            _file("strategies.py", content),
            _file("test_strategies.py", "def test_x():\n    assert True\n"),
        )
    )
    assert "NON_STDLIB_IMPORT" in _codes(report)


def test_forbidden_call_rejected() -> None:
    content = "import os\n\n\ndef read(path):\n    return open(path).read()\n"
    report = validate_code_patch(
        _patch(
            _file("strategies.py", content),
            _file("test_strategies.py", "def test_x():\n    assert True\n"),
        )
    )
    assert "FORBIDDEN_CALL" in _codes(report)


def test_path_traversal_rejected() -> None:
    report = validate_code_patch(
        _patch(
            _file("../strategies.py", "X = 1\n"),
            _file("test_strategies.py", "def test_x():\n    assert True\n"),
        )
    )
    assert "PATH_INVALID" in _codes(report)


def test_file_type_rejected() -> None:
    report = validate_code_patch(
        _patch(
            _file("notes.txt", "hello\n"),
            _file("test_notes.py", "def test_notes():\n    assert True\n"),
        )
    )
    assert "FILE_TYPE" in _codes(report)


def test_syntax_error_rejected() -> None:
    report = validate_code_patch(
        _patch(
            _file("strategies.py", "def broken(\n"),
            _file("test_strategies.py", "def test_x():\n    assert True\n"),
        )
    )
    assert "PY_SYNTAX" in _codes(report)


def test_empty_patch_rejected() -> None:
    report = validate_code_patch(None)
    assert "PATCH_EMPTY" in _codes(report)


def test_custom_limits() -> None:
    report = validate_code_patch(
        _valid_patch(), limits=CodeGuardLimits(max_files=1)
    )
    assert "FILE_LIMIT" in _codes(report)


def test_apply_code_gate_marks_human() -> None:
    proposal = RepairProposal(
        scope="engine",
        code_patch=_patch(
            _file("strategies.py", 'DOC = "33fb1daa-2286-49de-80dd-f57910d880fe"\n'),
        ),
    )
    apply_code_gate(proposal)
    assert proposal.guard is not None and proposal.guard.passed is False
    assert proposal.needs_human is True
    assert proposal.risk == "high"


def test_repair_parse_engine_patch_passes_guard() -> None:
    proposal = _parse_repair(
        {
            "root_cause": "table_structure",
            "scope": "engine",
            "summary": "fix strategy",
            "patch": {},
            "code_patch": {
                "base_version": "1.0.0",
                "files": [
                    {
                        "path": "strategies.py",
                        "content": "X = 1\n",
                        "status": "added",
                    },
                    {
                        "path": "test_strategies.py",
                        "content": "def test_x():\n    assert True\n",
                        "status": "added",
                    },
                ],
            },
            "test_plan": ["reparse"],
            "risk": "low",
            "confidence": 0.8,
        },
        {"target": {}},
        {"repair_scope": "engine"},
        {},
    )
    assert proposal.scope == "engine"
    assert proposal.code_patch is not None
    assert proposal.guard is not None and proposal.guard.passed is True
    assert proposal.needs_human is False


def test_repair_parse_engine_patch_blocks_hardcoding() -> None:
    proposal = _parse_repair(
        {
            "root_cause": "table_structure",
            "scope": "engine",
            "summary": "fix strategy",
            "patch": {},
            "code_patch": {
                "files": [
                    {
                        "path": "strategies.py",
                        "content": 'NAME = "AMS4108G.docx"\n',
                        "status": "added",
                    },
                    {
                        "path": "test_strategies.py",
                        "content": "def test_x():\n    assert True\n",
                        "status": "added",
                    },
                ]
            },
            "test_plan": ["reparse"],
            "risk": "low",
        },
        {"target": {}},
        {"repair_scope": "engine"},
        {},
    )
    assert proposal.guard is not None and proposal.guard.passed is False
    assert proposal.needs_human is True
    assert proposal.risk == "high"
    assert "Code guard blocked" in proposal.summary


def test_repair_parse_code_patch_requires_engine_scope() -> None:
    proposal = _parse_repair(
        {
            "root_cause": "recipe_binding",
            "scope": "recipe",
            "summary": "bind",
            "patch": {
                "ops": [
                    {
                        "op": "add",
                        "path": "/bindings/measures/Z",
                        "value": {"unit": "%", "family": "tensile"},
                    }
                ]
            },
            "code_patch": {
                "files": [
                    {"path": "strategies.py", "content": "X = 1\n"},
                ]
            },
            "test_plan": ["reparse"],
        },
        {"target": {"measure": "Z"}},
        {"repair_scope": "recipe"},
        {},
    )
    assert proposal.needs_human is True
    assert "only allowed for engine scope" in proposal.summary
