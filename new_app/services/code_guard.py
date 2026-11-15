"""L3 解析代码提案安全闸门：行数/文件限制、静态扫描与测试强制。"""

from __future__ import annotations

import ast
import json
import re
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from hanson_contracts import (
    CodeGuardReport,
    CodeGuardViolation,
    CodePatch,
    RepairProposal,
)


@dataclass(frozen=True)
class CodeGuardLimits:
    max_files: int = 3
    max_file_lines: int = 800
    max_patch_lines: int = 150
    max_bundle_bytes: int = 1024 * 1024


DEFAULT_LIMITS = CodeGuardLimits()
ALLOWED_SUFFIXES = {".py", ".json"}

FORBIDDEN_MODULES = {
    "socket",
    "ssl",
    "http",
    "urllib",
    "ftplib",
    "telnetlib",
    "smtplib",
    "subprocess",
    "multiprocessing",
    "ctypes",
    "importlib",
    "shutil",
    "requests",
    "httpx",
    "aiohttp",
    "boto3",
    "paramiko",
}
FORBIDDEN_CALLS = {
    "eval",
    "exec",
    "compile",
    "__import__",
    "open",
    "input",
    "breakpoint",
}
FORBIDDEN_ATTR_CALLS = {
    "os.system",
    "os.popen",
    "os.remove",
    "os.unlink",
    "os.rmdir",
    "os.removedirs",
    "os.rename",
    "os.chmod",
    "shutil.rmtree",
    "subprocess.run",
    "subprocess.call",
    "subprocess.Popen",
}
SENSITIVE_NAMES = {
    "document_id",
    "doc_id",
    "run_id",
    "file_name",
    "filename",
    "source_file",
}
DOC_ID_RE = re.compile(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.IGNORECASE
)
DOC_FILE_RE = re.compile(
    r"[\w\-]+\.(?:pdf|docx?|xlsx?|pptx?|png|jpe?g|tiff?)\b", re.IGNORECASE
)
# 已知的 bundle 内部模块；调用方可追加。
DEFAULT_LOCAL_MODULES = {"builtin", "strategies", "rules", "parsers", "normalize"}


def validate_code_patch(
    patch: CodePatch | dict[str, Any] | None,
    *,
    limits: CodeGuardLimits | None = None,
    local_modules: set[str] | None = None,
) -> CodeGuardReport:
    limits = limits or DEFAULT_LIMITS
    files = _files(patch)
    if not files:
        return _report([_v("PATCH_EMPTY", "code patch has no files")], {})

    violations: list[CodeGuardViolation] = []
    if len(files) > limits.max_files:
        violations.append(
            _v("FILE_LIMIT", f"{len(files)} files exceed limit {limits.max_files}")
        )
    paths = [str(item.get("path") or "") for item in files]
    if len(set(paths)) != len(paths):
        violations.append(_v("DUPLICATE_PATH", "duplicate file paths"))

    local = set(DEFAULT_LOCAL_MODULES)
    local.update(local_modules or ())
    local.update(
        PurePosixPath(path).stem for path in paths if path.endswith(".py")
    )

    patch_lines = 0
    largest_file = 0
    total_bytes = 0
    for item in files:
        path = str(item.get("path") or "")
        content = str(item.get("content") or "")
        status = str(item.get("status") or "modified")
        _check_path(path, violations)
        if not content.strip():
            violations.append(
                _v("CONTENT_REQUIRED", "file content is required", path)
            )
            continue
        lines = _line_count(content)
        largest_file = max(largest_file, lines)
        total_bytes += len(content.encode("utf-8"))
        if lines > limits.max_file_lines:
            violations.append(
                _v(
                    "FILE_TOO_LARGE",
                    f"{lines} lines exceed limit {limits.max_file_lines}",
                    path,
                )
            )
        if status == "added":
            patch_lines += lines
        else:
            diff = str(item.get("diff") or "")
            if not diff.strip():
                violations.append(
                    _v(
                        "DIFF_REQUIRED",
                        "modified files require a unified diff for line accounting",
                        path,
                    )
                )
            else:
                patch_lines += _diff_lines(diff)
        if path.endswith(".py"):
            violations.extend(
                _scan_python(
                    path,
                    content,
                    is_test=_is_test(path),
                    local_modules=local,
                )
            )
        elif path.endswith(".json"):
            violations.extend(_scan_json(path, content))

    if patch_lines > limits.max_patch_lines:
        violations.append(
            _v(
                "PATCH_TOO_LARGE",
                f"{patch_lines} changed lines exceed limit {limits.max_patch_lines}",
            )
        )
    if total_bytes > limits.max_bundle_bytes:
        violations.append(
            _v(
                "BUNDLE_TOO_LARGE",
                f"{total_bytes} bytes exceed limit {limits.max_bundle_bytes}",
            )
        )

    test_files = [item for item in files if _is_test(str(item.get("path") or ""))]
    if not test_files:
        violations.append(
            _v("TESTS_REQUIRED", "at least one test_*.py file is required")
        )
    elif not any(
        _has_test_function(str(item.get("content") or "")) for item in test_files
    ):
        violations.append(
            _v("TESTS_EMPTY", "test files must define at least one test_* function")
        )

    stats = {
        "files": len(files),
        "patch_lines": patch_lines,
        "largest_file_lines": largest_file,
        "bytes": total_bytes,
        "test_files": len(test_files),
    }
    return _report(violations, stats)


def apply_code_gate(
    proposal: RepairProposal,
    *,
    limits: CodeGuardLimits | None = None,
    local_modules: set[str] | None = None,
) -> RepairProposal:
    """对 L3 提案执行闸门；不通过则强制转人工。"""
    report = validate_code_patch(
        proposal.code_patch, limits=limits, local_modules=local_modules
    )
    proposal.guard = report
    if not report.passed:
        proposal.needs_human = True
        proposal.risk = "high"
    return proposal


def violation_summary(report: CodeGuardReport, limit: int = 5) -> str:
    items = [
        f"{item.code}({item.file or '-'})" for item in report.violations[:limit]
    ]
    if len(report.violations) > limit:
        items.append(f"+{len(report.violations) - limit}")
    return ", ".join(items)


def _files(patch: CodePatch | dict[str, Any] | None) -> list[dict[str, Any]]:
    if patch is None:
        return []
    if isinstance(patch, CodePatch):
        return [item.model_dump() for item in patch.files]
    if isinstance(patch, dict):
        raw = patch.get("files") or []
    elif isinstance(patch, list):
        raw = patch
    else:
        return []
    return [item for item in raw if isinstance(item, dict)]


def _report(
    violations: list[CodeGuardViolation], stats: dict[str, Any]
) -> CodeGuardReport:
    return CodeGuardReport(
        passed=not violations, violations=violations, stats=stats
    )


def _v(
    code: str, message: str, file: str = "", line: int = 0
) -> CodeGuardViolation:
    return CodeGuardViolation(code=code, message=message, file=file, line=line)


def _check_path(path: str, violations: list[CodeGuardViolation]) -> None:
    if not path:
        violations.append(_v("PATH_INVALID", "file path is required"))
        return
    if path.startswith("/") or "\\" in path or ".." in PurePosixPath(path).parts:
        violations.append(
            _v("PATH_INVALID", "absolute, windows or parent paths are not allowed", path)
        )
        return
    suffix = PurePosixPath(path).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        violations.append(
            _v("FILE_TYPE", f"only .py/.json files are allowed, got {suffix or '-'}", path)
        )


def _line_count(content: str) -> int:
    return len(content.splitlines())


def _diff_lines(diff: str) -> int:
    count = 0
    for line in diff.splitlines():
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith(("+", "-")):
            count += 1
    return count


def _is_test(path: str) -> bool:
    name = PurePosixPath(path).name
    return name.endswith(".py") and name.startswith("test_")


def _has_test_function(content: str) -> bool:
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return False
    return any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
        for node in ast.walk(tree)
    )


def _scan_python(
    path: str,
    content: str,
    *,
    is_test: bool,
    local_modules: set[str],
) -> list[CodeGuardViolation]:
    try:
        tree = ast.parse(content)
    except SyntaxError as exc:
        return [
            _v("PY_SYNTAX", f"syntax error: {exc.msg}", path, exc.lineno or 0)
        ]
    if is_test:
        # 测试文件允许使用测试框架与夹具，只做语法检查。
        return []
    violations: list[CodeGuardViolation] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                violations.extend(
                    _check_module(path, alias.name, node.lineno, local_modules)
                )
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                continue
            violations.extend(
                _check_module(
                    path, node.module or "", node.lineno, local_modules
                )
            )
        elif isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in FORBIDDEN_CALLS or name in FORBIDDEN_ATTR_CALLS:
                violations.append(
                    _v(
                        "FORBIDDEN_CALL",
                        f"call to {name} is not allowed",
                        path,
                        getattr(node, "lineno", 0),
                    )
                )
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if _looks_hardcoded(node.value):
                violations.append(
                    _v(
                        "HARDCODED_DOCUMENT",
                        "string literal looks like a hardcoded document",
                        path,
                        getattr(node, "lineno", 0),
                    )
                )
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            if (
                isinstance(value, ast.Constant)
                and isinstance(value.value, str)
                and value.value
                and any(_target_name(item) in SENSITIVE_NAMES for item in targets)
            ):
                violations.append(
                    _v(
                        "HARDCODED_DOCUMENT",
                        "document identifier is hardcoded",
                        path,
                        getattr(node, "lineno", 0),
                    )
                )
    return violations


def _scan_json(path: str, content: str) -> list[CodeGuardViolation]:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        return [_v("JSON_INVALID", f"invalid json: {exc.msg}", path, exc.lineno)]
    violations: list[CodeGuardViolation] = []
    for value in _walk_strings(payload):
        if _looks_hardcoded(value):
            violations.append(
                _v(
                    "HARDCODED_DOCUMENT",
                    "json value looks like a hardcoded document",
                    path,
                )
            )
    return violations


def _walk_strings(value: Any, depth: int = 0) -> list[str]:
    if depth > 20:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        items: list[str] = []
        for key, item in value.items():
            items.extend(_walk_strings(key, depth + 1))
            items.extend(_walk_strings(item, depth + 1))
        return items
    if isinstance(value, list):
        items = []
        for item in value:
            items.extend(_walk_strings(item, depth + 1))
        return items
    return []


def _check_module(
    path: str, module: str, line: int, local_modules: set[str]
) -> list[CodeGuardViolation]:
    root = module.split(".")[0]
    if not root:
        return []
    if root in FORBIDDEN_MODULES:
        return [
            _v(
                "MODULE_FORBIDDEN",
                f"module {root} is not allowed",
                path,
                line,
            )
        ]
    if root not in local_modules and root not in sys.stdlib_module_names:
        return [
            _v(
                "NON_STDLIB_IMPORT",
                f"module {root} is not in the standard library",
                path,
                line,
            )
        ]
    return []


def _call_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def _target_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    return ""


def _looks_hardcoded(value: str) -> bool:
    if len(value) < 4:
        return False
    return bool(DOC_ID_RE.search(value) or DOC_FILE_RE.search(value))
