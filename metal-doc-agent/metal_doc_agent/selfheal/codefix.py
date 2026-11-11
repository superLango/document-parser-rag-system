"""Generate a rule-level code patch, then guard, test and optionally merge it."""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from .compat import check_compat
from .config import SelfHealSettings
from .l3 import check_policy, diff_files
from .patch_guard import case_literals, check_patch

CODE_PROMPT = """你是金属标准解析引擎的修复智能体。根据诊断结果修改“规则”，禁止针对单个文档/记录/值写死。
只输出 unified diff 纯文本，以 --- a/ 开头；不要 JSON，不要解释，不要 Markdown 代码块，不要思考过程。
要求：
1) 只改通用识别/解析/绑定规则，不得出现本次反馈里的具体值、牌号、标准号、表号、记录号、文档 ID；
2) 不得按 doc_id/record_id/table_id 特判；
3) 必须包含回归测试：正例（本案例）、变体（不同值/表头）、反例（不应误改）；
4) 兼容式修改：不改既有函数签名、不删字段、不新增必填契约字段、不改配置默认行为；
5) 不得修改 configs/dictionaries/、business_dictionary.*.json；
6) diff 使用 --- a/... +++ b/... 格式；只改最小必要行，单文件改动不超过 60 行。
诊断：{diagnosis}
反馈：{feedback}
相关源码：
{context}
上次补丁被拒原因（首次生成时为空）：{retry}
"""
MAX_FILE_CHARS = 4500
MAX_CONTEXT_FILES = 2
# Output budget must leave room for the prompt inside the 16K context window
# used by the production model.
MAX_OUTPUT_TOKENS = 9000
# Root-cause -> the rule modules that implement it.
ROOT_CAUSE_FILES = {
    "header_mapping": (
        "metal_doc_agent/tablegrid/parser.py",
        "metal_doc_agent/tablegrid/ir.py",
        "metal_doc_agent/tablegrid/profile.py",
    ),
    "table_structure": (
        "metal_doc_agent/tablegrid/parser.py",
        "metal_doc_agent/tablegrid/ir.py",
    ),
    "value_parsing": (
        "metal_doc_agent/tablegrid/normalize.py",
        "metal_doc_agent/extraction/matrix.py",
    ),
    "extraction_rule": (
        "metal_doc_agent/extraction/matrix.py",
        "metal_doc_agent/tablegrid/normalize.py",
    ),
    "schema_dictionary": (
        "metal_doc_agent/canonicalize/dictionary.py",
        "metal_doc_agent/schema_projection.py",
    ),
    "document_meta": ("metal_doc_agent/ingest.py",),
    "ocr": ("metal_doc_agent/ocr.py",),
    "layout": ("metal_doc_agent/tablegrid/parser.py",),
}
# Never send these to the model: they never contain an extraction rule.
CONTEXT_SKIP = (
    "metal_doc_agent/tests/",
    "metal_doc_agent/goldset",
    "metal_doc_agent/eval",
    "metal_doc_agent/acceptance.py",
    "metal_doc_agent/cli.py",
    "metal_doc_agent/api.py",
)


class CodeFixAgent:
    def __init__(self, settings: SelfHealSettings) -> None:
        self.settings = settings

    def propose(
        self,
        finding: Any,
        result: Any,
        diagnosis: dict[str, Any] | None = None,
        feedback_id: str = "",
    ) -> tuple[str | None, dict[str, Any]]:
        if not self.settings.code_agent:
            return None, {"reason": "L3 未启用（SELFHEAL_CODE_AGENT=0）"}
        context = self._source_context(diagnosis)
        literals = case_literals(diagnosis, finding)
        retry_note = ""
        last_reason = ""
        for attempt in range(2):
            prompt = (
                CODE_PROMPT.replace(
                    "{diagnosis}",
                    json.dumps(diagnosis or {}, ensure_ascii=False, default=str),
                )
                .replace("{feedback}", _finding_text(finding, result))
                .replace("{context}", context)
                .replace("{retry}", retry_note or "无")
            )
            diff, detail = self._model_diff(prompt)
            if not diff:
                last_reason = detail
                retry_note = f"上一版未产出 diff：{detail}。请直接输出完整 unified diff。"
                continue
            files = diff_files(diff)
            policy = check_policy(diff, files)
            if not policy.passed:
                last_reason = f"补丁策略未通过：{policy.detail}"
                retry_note = (
                    f"{last_reason}。必须在同一个 diff 里包含 tests/selfheal/ 下的回归测试，"
                    f"单文件不超过 60 行。上一版 diff：\n{diff[:2500]}"
                )
                continue
            guard_ok, guard_detail = check_patch(
                diff, files, literals, self.settings.project_root
            )
            if not guard_ok:
                last_reason = f"反硬编码门禁：{guard_detail}"
                retry_note = (
                    f"{last_reason}。不得写入本次案例的值/牌号/表号/文档 ID。"
                    f"上一版 diff：\n{diff[:2500]}"
                )
                continue
            compat_ok, compat_detail = check_compat(diff, files)
            if not compat_ok:
                last_reason = f"兼容性门禁：{compat_detail}"
                retry_note = (
                    f"{last_reason}。只能增量修改，不得删除既有定义。"
                    f"上一版 diff：\n{diff[:2500]}"
                )
                continue

            report: dict[str, Any] = {
                "reason": "补丁通过策略、反硬编码与兼容性门禁",
                "files": files,
                "literals_checked": literals,
                "guard": guard_detail,
                "compat": compat_detail,
                "attempts": attempt + 1,
                "applied": False,
                "tests": None,
            }
            if self.settings.auto_merge:
                applied, apply_detail, tests = self._apply_and_test(diff, files)
                report["applied"] = applied
                report["apply_detail"] = apply_detail
                report["tests"] = tests
                if not applied:
                    last_reason = apply_detail
                    retry_note = (
                        f"{apply_detail}。请检查引用的函数/变量是否真实存在，"
                        f"并确保补丁能通过测试。上一版 diff：\n{diff[:2500]}"
                    )
                    continue
            return diff, report
        return None, {"reason": last_reason or "模型未生成有效 diff"}

    def _model_diff(self, prompt: str) -> tuple[str | None, str]:
        if not self.settings.model_base_url:
            return None, "模型地址未配置，无法生成补丁"
        body = {
            "model": self.settings.model_name,
            "messages": [
                {
                    "role": "system",
                    "content": "直接输出 unified diff，不要思考过程，不要解释。",
                },
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.0,
            "max_tokens": MAX_OUTPUT_TOKENS,
            "stream": False,
        }
        try:
            import httpx

            with httpx.Client(
                timeout=self.settings.model_timeout, trust_env=False
            ) as client:
                response = client.post(
                    f"{self.settings.model_base_url.rstrip('/')}/chat/completions",
                    json={**body, "chat_template_kwargs": {"enable_thinking": False}},
                )
                if response.status_code in {400, 422}:
                    # Older servers reject chat_template_kwargs; retry plainly.
                    response = client.post(
                        f"{self.settings.model_base_url.rstrip('/')}/chat/completions",
                        json=body,
                    )
                if response.status_code >= 400:
                    return None, (
                        f"模型返回 {response.status_code}：{response.text[:300]}"
                    )
                response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
        except Exception as exc:  # noqa: BLE001 - report why generation failed
            return None, f"模型调用失败：{type(exc).__name__}: {str(exc)[:200]}"

        diff = ""
        try:
            from .planner import _parse_json

            payload = _parse_json(content)
            diff = str(payload.get("diff") or "")
        except Exception:  # noqa: BLE001 - fall back to a raw unified diff
            diff = ""
        if "--- a/" not in diff and "diff --git" not in diff:
            # The model often answers with a bare diff; _parse_json returns an
            # empty object for it, and using that would silently drop a valid
            # patch (this is what made L3 report "no diff").
            diff = content
        extracted = _extract_diff(diff)
        if extracted:
            return extracted, "ok"
        return None, f"模型未输出可用 diff：{str(content)[:300]}"

    def _source_context(self, diagnosis: dict[str, Any] | None) -> str:
        """Pick the parsing files that can actually contain the defect.

        Keyword search over the whole package kept returning unrelated modules
        (acceptance.py, cli.py), so the model never saw the rule it had to
        change. Files are now chosen by root cause first, then by text match.
        """

        root = Path(self.settings.project_root)
        diagnosis = diagnosis or {}
        rationale = " ".join(
            [
                str(diagnosis.get("mechanism") or ""),
                str(diagnosis.get("first_divergence") or ""),
                str((diagnosis.get("rule_change") or {}).get("rule_id") or ""),
                str(diagnosis.get("root_cause") or ""),
            ]
        )

        candidates: list[Path] = []
        hint_file = (diagnosis.get("code_hint") or {}).get("file")
        if hint_file:
            candidates.append(root / str(hint_file))
        for name in ROOT_CAUSE_FILES.get(
            str(diagnosis.get("root_cause") or ""), ()
        ):
            candidates.append(root / name)
        tokens = [
            token
            for token in re.split(r"[^\w\u4e00-\u9fff]+", rationale)
            if len(token) >= 2
        ]
        scored: list[tuple[int, Path]] = []
        for base in (root / "metal_doc_agent",):
            for path in base.rglob("*.py"):
                normalized = path.relative_to(root).as_posix()
                if any(
                    normalized.startswith(prefix) for prefix in CONTEXT_SKIP
                ):
                    continue
                if path in candidates:
                    continue
                try:
                    text = path.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
                score = sum(text.count(token) for token in tokens)
                if score:
                    scored.append((score, path))
        scored.sort(key=lambda item: -item[0])
        for _, path in scored:
            if len(candidates) >= MAX_CONTEXT_FILES:
                break
            candidates.append(path)

        chunks: list[str] = []
        for path in candidates[:MAX_CONTEXT_FILES]:
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            relative = path.relative_to(root).as_posix()
            chunks.append(f"### {relative}\n{text[:MAX_FILE_CHARS]}")
        return "\n\n".join(chunks) or "（未检索到相关源码）"

    def _apply_and_test(
        self, diff: str, files: list[str]
    ) -> tuple[bool, str, dict[str, Any] | None]:
        repo = Path(self.settings.repo_root)
        project = Path(self.settings.project_root)
        if not (repo / ".git").exists():
            return False, "工作区无 .git，保留提案", None
        prefix = self._directory_argument(repo, project)
        check = subprocess.run(
            ["git", "apply", "--check", *prefix, "-"],
            cwd=str(repo),
            input=diff,
            text=True,
            capture_output=True,
            check=False,
        )
        if check.returncode != 0:
            return False, f"git apply --check 失败：{check.stderr.strip()[:200]}", None
        apply = subprocess.run(
            ["git", "apply", *prefix, "-"],
            cwd=str(repo),
            input=diff,
            text=True,
            capture_output=True,
            check=False,
        )
        if apply.returncode != 0:
            return False, f"git apply 失败：{apply.stderr.strip()[:200]}", None
        smoke_ok, smoke_detail = self._smoke_import(files, project)
        if not smoke_ok:
            self._revert(diff, repo, prefix)
            return False, f"补丁导入验证失败，已回滚：{smoke_detail}", None
        tests = self._run_tests(project)
        if not tests.get("passed"):
            self._revert(diff, repo, prefix)
            return False, "测试未通过，已回滚补丁", tests
        return (
            True,
            "测试通过，补丁已写入源码；下一个任务会由沙箱进程加载新规则",
            tests,
        )

    def _revert(self, diff: str, repo: Path, prefix: list[str]) -> None:
        subprocess.run(
            ["git", "apply", "-R", *prefix, "-"],
            cwd=str(repo),
            input=diff,
            text=True,
            capture_output=True,
            check=False,
        )

    def _smoke_import(self, files: list[str], project: Path) -> tuple[bool, str]:
        """Import every patched module in a fresh interpreter."""

        modules = [
            name.replace("\\", "/")[: -len(".py")].replace("/", ".")
            for name in files
            if name.replace("\\", "/").endswith(".py")
            and not name.replace("\\", "/").startswith("tests/")
        ]
        if not modules:
            return True, "无 Python 模块需要导入验证"
        code = (
            "import importlib, sys\n"
            "for name in sys.argv[1:]:\n"
            "    importlib.import_module(name)\n"
        )
        try:
            completed = subprocess.run(
                [sys.executable, "-c", code, *modules],
                cwd=str(project),
                capture_output=True,
                text=True,
                timeout=300,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False, "导入验证超时"
        if completed.returncode == 0:
            return True, "导入验证通过"
        detail = (completed.stderr or completed.stdout or "").strip()
        return False, detail[-400:]

    def _directory_argument(self, repo: Path, project: Path) -> list[str]:
        try:
            relative = project.relative_to(repo).as_posix()
        except ValueError:
            return []
        if relative in {"", "."}:
            return []
        return [f"--directory={relative}"]

    def _run_tests(self, repo: Path) -> dict[str, Any]:
        command = self.settings.test_command
        if not command:
            return {"passed": True, "detail": "未配置测试命令，跳过"}
        try:
            completed = subprocess.run(
                command,
                cwd=str(repo),
                shell=True,
                capture_output=True,
                text=True,
                timeout=600,
                check=False,
            )
        except Exception as exc:  # noqa: BLE001 - report the failure
            return {"passed": False, "detail": str(exc)[:300]}
        return {
            "passed": completed.returncode == 0,
            "returncode": completed.returncode,
            "detail": (completed.stdout or completed.stderr or "")[-800:],
        }


def _extract_diff(text: str) -> str | None:
    if not text:
        return None
    fenced = re.search(r"```(?:diff)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start = text.find("--- a/")
    if start < 0:
        start = text.find("diff --git")
    if start < 0:
        return None
    return text[start:].strip() + "\n"


def _finding_text(finding: Any, result: Any) -> str:
    target = getattr(finding, "target", None)
    payload = {
        "rule_code": getattr(finding, "rule_code", None),
        "verdict": getattr(getattr(finding, "verdict", None), "value", None),
        "target": target.model_dump(mode="json") if target is not None else {},
        "expected": getattr(finding, "expected", None),
        "observed": getattr(finding, "observed", None),
        "document": {
            "standard_no": getattr(result.document, "standard_no", None),
            "title": getattr(result.document, "title", None),
        }
        if result is not None
        else {},
    }
    return json.dumps(payload, ensure_ascii=False, default=str)
