from __future__ import annotations

import hashlib

from hanson_contracts import (
    CodeFile,
    CodeGuardReport,
    CodePatch,
    RegressionStats,
    RepairProposal,
    VerificationPackage,
)

from services.orchestration.feedback.service import (
    build_code_asset_manifest,
    code_release_blockers,
    next_patch_version,
)


def _verification(*, passed: bool = True, new_errors: int = 0) -> VerificationPackage:
    return VerificationPackage(
        proposal_id="p1",
        before_run="run-before",
        passed=passed,
        regression=RegressionStats(new_errors=new_errors),
    )


def _proposal(**overrides) -> RepairProposal:
    base = {
        "scope": "engine",
        "code_patch": CodePatch(
            files=[
                CodeFile(path="strategies.py", content="def run():\n    return 1\n"),
                CodeFile(
                    path="test_strategies.py",
                    content="def test_run():\n    assert True\n",
                    status="added",
                ),
            ]
        ),
        "guard": CodeGuardReport(passed=True),
        "needs_human": False,
    }
    base.update(overrides)
    return RepairProposal(**base)


def test_next_patch_version() -> None:
    assert next_patch_version("1.0.22") == "1.0.23"
    assert next_patch_version("bad") == "1.0.0"


def test_release_blockers_requires_confirm() -> None:
    assert "confirm 必须为 true" in code_release_blockers(
        _proposal(), confirm=False, verification=_verification(), verification_id="fb-1"
    )
    assert (
        code_release_blockers(
            _proposal(),
            confirm=True,
            verification=_verification(),
            verification_id="fb-1",
        )
        == []
    )


def test_release_blockers_requires_verification_and_tests() -> None:
    proposal = _proposal()
    blockers = code_release_blockers(proposal, confirm=True)
    assert "缺少通过的验证包" in blockers
    assert "缺少 verification_id" in blockers

    no_tests = _proposal(
        code_patch=CodePatch(
            files=[CodeFile(path="strategies.py", content="def run():\n    return 1\n")]
        )
    )
    assert "缺少候选测试" in code_release_blockers(
        no_tests, confirm=True, verification=_verification(), verification_id="fb-1"
    )
    assert "回归引入新错误" in code_release_blockers(
        _proposal(),
        confirm=True,
        verification=_verification(new_errors=1),
        verification_id="fb-1",
    )


def test_release_blockers_reject_non_engine_or_bad_guard() -> None:
    recipe = _proposal(scope="recipe")
    assert any(
        "scope" in item
        for item in code_release_blockers(
            recipe,
            confirm=True,
            verification=_verification(),
            verification_id="fb-1",
        )
    )
    blocked = _proposal(guard=CodeGuardReport(passed=False))
    assert "安全门未通过" in code_release_blockers(
        blocked,
        confirm=True,
        verification=_verification(),
        verification_id="fb-1",
    )


def test_release_blockers_reject_empty_code_patch() -> None:
    empty = _proposal(code_patch=CodePatch(files=[]))
    assert "缺少代码文件" in code_release_blockers(
        empty,
        confirm=True,
        verification=_verification(),
        verification_id="fb-1",
    )


def test_build_code_asset_manifest_hashes_and_classifies_files() -> None:
    manifest = build_code_asset_manifest(
        _proposal().code_patch.model_dump(mode="json"), version="1.0.23"
    )
    assert manifest["kind"] == "parser"
    assert manifest["asset_id"] == "parser_core"
    assert manifest["version"] == "1.0.23"
    assert manifest["entry_modules"] == ["strategies.py"]
    assert manifest["tests"] == ["test_strategies.py"]
    digest = hashlib.sha256(b"def run():\n    return 1\n").hexdigest()
    assert manifest["files"][0] == {"path": "strategies.py", "sha256": digest}
