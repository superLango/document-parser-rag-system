"""L3 code-repair proposals: policy validation and optional git application.

Default posture: proposal only. A patch is applied only when
``SELFHEAL_AUTO_MERGE=1``, the workspace is a git repository, and the patch
passes the diff policy. The self-heal route never edits files by itself.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .config import SelfHealSettings
from .contracts import CodePatchProposal, Finding, ProposalStatus

ALLOWED_PREFIXES = (
    "metal_doc_agent/tablegrid/",
    "metal_doc_agent/extraction/",
    "metal_doc_agent/recipes/",
    "metal_doc_agent/validation/",
    "metal_doc_agent/selfheal/",
    "configs/",
    "tests/selfheal/",
)
ALLOWED_FILES = {"metal_doc_agent/schema_projection.py"}
FORBIDDEN_PREFIXES = ("apps/api/", "infra/", "deploy/", ".github/")
MAX_FILES = 5
MAX_LINES = 200
FILE_HEADER_RE = re.compile(r"^\+\+\+ b/(.+)$", re.MULTILINE)


@dataclass
class PatchPolicy:
    passed: bool
    detail: str
    files: list[str]


def diff_files(diff: str) -> list[str]:
    return [match.strip() for match in FILE_HEADER_RE.findall(diff)]


def diff_line_count(diff: str) -> int:
    return sum(
        1
        for line in diff.splitlines()
        if (line.startswith("+") and not line.startswith("+++"))
        or (line.startswith("-") and not line.startswith("---"))
    )


def check_policy(diff: str, files: list[str] | None = None) -> PatchPolicy:
    declared = files or diff_files(diff)
    problems: list[str] = []
    if not declared:
        problems.append("diff 未声明任何文件")
    if len(declared) > MAX_FILES:
        problems.append(f"文件数 {len(declared)} 超过 {MAX_FILES}")
    for name in declared:
        normalized = name.replace("\\", "/").lstrip("./")
        if normalized.startswith("/") or ".." in normalized.split("/"):
            problems.append(f"非法路径：{name}")
            continue
        if any(normalized.startswith(prefix) for prefix in FORBIDDEN_PREFIXES):
            problems.append(f"禁止修改：{name}")
            continue
        if normalized not in ALLOWED_FILES and not any(
            normalized.startswith(prefix) for prefix in ALLOWED_PREFIXES
        ):
            problems.append(f"不在白名单：{name}")
    lines = diff_line_count(diff)
    if lines > MAX_LINES:
        problems.append(f"变更行数 {lines} 超过 {MAX_LINES}")
    if not any(
        name.replace("\\", "/").startswith(("tests/", "metal_doc_agent/selfheal/tests"))
        for name in declared
    ):
        problems.append("补丁必须包含回归测试")
    if problems:
        return PatchPolicy(False, "；".join(problems), declared)
    return PatchPolicy(True, f"{len(declared)} files, {lines} lines", declared)


class CodePatchService:
    def __init__(self, settings: SelfHealSettings) -> None:
        self.settings = settings

    def propose(
        self,
        finding: Finding,
        proposal_id: str,
        diff: str,
        files: list[str] | None = None,
    ) -> CodePatchProposal | None:
        if not self.settings.code_agent:
            return None
        policy = check_policy(diff, files)
        patch_dir = self.settings.patches_root / proposal_id
        patch_dir.mkdir(parents=True, exist_ok=True)
        (patch_dir / "patch.diff").write_text(diff, encoding="utf-8")
        status = ProposalStatus.propose_only
        reason = policy.detail
        if policy.passed and self.settings.auto_merge:
            applied, detail = self._try_apply(diff)
            reason = detail
            if applied:
                status = ProposalStatus.applied
        elif policy.passed:
            reason = "auto_merge 关闭，仅生成提案"
        return CodePatchProposal(
            proposal_id=proposal_id,
            files=policy.files,
            diff=diff,
            status=status,
            reason=reason,
        )

    def _try_apply(self, diff: str) -> tuple[bool, str]:
        repo = self.settings.project_root
        if not (repo / ".git").exists():
            return False, "工作区无 .git，无法自动合并（需先补版本控制）"
        check = subprocess.run(
            ["git", "apply", "--check", "-"],
            cwd=str(repo),
            input=diff,
            text=True,
            capture_output=True,
            check=False,
        )
        if check.returncode != 0:
            return False, f"git apply --check 失败：{check.stderr.strip()[:200]}"
        apply = subprocess.run(
            ["git", "apply", "-"],
            cwd=str(repo),
            input=diff,
            text=True,
            capture_output=True,
            check=False,
        )
        if apply.returncode != 0:
            return False, f"git apply 失败：{apply.stderr.strip()[:200]}"
        return True, "已应用补丁（git apply）"
