"""Tool layer for the orchestration graph (M3.1-03/04).

Tools are an explicit allowlist with path guards and a wall-clock ceiling.
There is no ``eval``/``exec`` surface: the graph can only call the functions
registered here, so a model-generated payload can never execute code.
"""

from __future__ import annotations

import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from ..contracts import DocumentResult
from ..pipeline import PipelineResult, run_pipeline
from ..settings import Settings
from ..validation import validate

TOOL_ALLOWLIST = (
    "load_artifact",
    "run_extract",
    "validate",
    "retrieve_reference",
    "write_artifact",
)

ALLOWED_ARTIFACTS = {
    "result.json",
    "pages.json",
    "references.json",
    "coverage_plan.json",
    "column_bindings.json",
    "item_inventory.json",
    "trace.json",
    "manifest.json",
    "outline.json",
    "evidence.jsonl",
    "clauses.jsonl",
}


class ToolError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code
        self.message = message


class PipelineTools:
    def __init__(
        self,
        settings: Settings,
        out_dir: str | Path,
        *,
        max_seconds: float | None = None,
    ) -> None:
        self.settings = settings
        self.out_dir = Path(out_dir)
        self.max_seconds = (
            max_seconds
            if max_seconds is not None
            else float(getattr(settings, "tool_timeout_seconds", 900.0))
        )
        self.extract_calls = 0
        self.ocr_pages = 0
        self.model_tokens = 0
        self.elapsed_ms = 0.0
        self._result: PipelineResult | None = None

    def call(self, tool: str, **kwargs: Any) -> Any:
        if tool not in TOOL_ALLOWLIST:
            raise ToolError("tool_not_allowed", tool)
        method: Callable[..., Any] = getattr(self, tool)
        started = time.perf_counter()
        try:
            return method(**kwargs)
        finally:
            elapsed = (time.perf_counter() - started) * 1000
            self.elapsed_ms += elapsed
            if elapsed > self.max_seconds * 1000:
                raise ToolError("tool_timeout", f"{tool} took {elapsed:.0f}ms")

    # -- artifacts --------------------------------------------------------
    def load_artifact(self, name: str) -> Any:
        relative = self._safe_name(name)
        path = self.out_dir / relative
        if not path.exists():
            raise ToolError("artifact_missing", relative)
        if relative.endswith(".jsonl"):
            return [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        if relative.endswith(".md"):
            return path.read_text(encoding="utf-8")
        return json.loads(path.read_text(encoding="utf-8"))

    def write_artifact(self, name: str, data: Any) -> str:
        relative = self._safe_name(name)
        path = self.out_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(data, str):
            path.write_text(data, encoding="utf-8")
        else:
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        return relative

    def _safe_name(self, name: str) -> str:
        relative = str(name)
        if relative.startswith("/") or ".." in relative or "\\" in relative:
            raise ToolError("path_denied", relative)
        if not relative.startswith("m3_") and relative not in ALLOWED_ARTIFACTS:
            raise ToolError("artifact_not_allowed", relative)
        return relative

    # -- data plane -------------------------------------------------------
    def run_extract(
        self,
        doc_path: str,
        *,
        ocr: str | None = None,
        extractor: str | None = None,
        template: str | None = None,
        ocr_dpi: int | None = None,
    ) -> PipelineResult:
        settings = self.settings
        overrides: dict[str, Any] = {}
        if ocr:
            overrides["ocr_backend"] = ocr
        if extractor:
            overrides["extractor_backend"] = extractor
        if ocr_dpi:
            overrides["ocr_dpi"] = ocr_dpi
        if overrides:
            settings = replace(settings, **overrides)
        result = run_pipeline(
            doc_path,
            self.out_dir,
            settings=settings,
            coverage_template=template or "product_full",
        )
        self._result = result
        self.extract_calls += 1
        self.model_tokens += int(
            (result.trace.get("model_usage") or {}).get("total_tokens") or 0
        )
        for step in result.trace.get("steps", []):
            if step.get("name") == "ocr":
                self.ocr_pages += int(step.get("pages") or 0)
        return result

    def result(self) -> PipelineResult:
        if self._result is not None:
            return self._result
        payload = self.load_artifact("result.json")
        data = DocumentResult.model_validate(payload)
        trace = self.load_artifact("trace.json") if (self.out_dir / "trace.json").exists() else {}
        result = PipelineResult(
            result=data,
            evidence=_read_evidence(self.out_dir),
            audit_markdown="",
            trace=trace,
        )
        self._result = result
        return result

    def validate(self) -> Any:
        result = self.result()
        return validate(
            result.result.document,
            result.result.records,
            result.evidence,
            result.result.coverage,
            tables=result.result.tables,
        )

    def retrieve_reference(self, doc_id: str) -> dict[str, Any]:
        payload = self.load_artifact("references.json")
        references = payload.get("references") or []
        gaps = payload.get("gaps") or []
        return {
            "doc_id": doc_id,
            "edges": len(references),
            "gaps": gaps[:20],
            "budget": payload.get("budget") or {},
        }


def _read_evidence(root: Path) -> list:
    from ..contracts import Evidence

    path = root / "evidence.jsonl"
    if not path.exists():
        return []
    return [
        Evidence.model_validate(json.loads(line))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
