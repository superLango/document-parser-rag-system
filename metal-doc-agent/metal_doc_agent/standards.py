"""Local standards version registry and reference resolution.

M1.5.2 keeps the version table reviewable in ``configs/standards.json``. The
runtime resolves dated references against the exact edition and undated
references against the single current edition in the local library. Anything
outside the library stays unresolved and is reported as a gap instead of being
silently guessed.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from .contracts import ReferenceGraph
from .tablegrid.normalize import clean_text

ResolutionStatus = Literal["current", "superseded", "conflict", "unknown"]


@dataclass(frozen=True)
class StandardRecord:
    standard_no: str
    edition: str | None = None
    title: str | None = None
    status: str = "unknown"
    doc_id: str | None = None
    supersedes: tuple[str, ...] = ()
    source: str | None = None
    source_file: str | None = None


@dataclass(frozen=True)
class Resolution:
    record: StandardRecord | None = None
    basis: str | None = None
    status: ResolutionStatus = "unknown"
    reason: str | None = None
    superseded_by: str | None = None


def normalize_standard_no(value: str | None) -> str:
    text = clean_text(value)
    text = text.replace("∕", "/").replace("／", "/").upper()
    return re.sub(r"\s+", "", text)


def load_registry(path: str | Path) -> "StandardRegistry":
    target = Path(path)
    if not target.exists():
        return StandardRegistry()
    data = json.loads(target.read_text(encoding="utf-8"))
    records: list[StandardRecord] = []
    for item in data.get("standards", []):
        standard_no = clean_text(item.get("standard_no"))
        if not standard_no:
            continue
        records.append(
            StandardRecord(
                standard_no=standard_no,
                edition=clean_text(item.get("edition")) or None,
                title=clean_text(item.get("title")) or None,
                status=clean_text(item.get("status")) or "unknown",
                doc_id=_plain(item.get("doc_id")),
                supersedes=tuple(
                    clean_text(value)
                    for value in item.get("supersedes", [])
                    if clean_text(value)
                ),
                source=clean_text(item.get("source")) or None,
                source_file=_plain(item.get("source_file")),
            )
        )
    return StandardRegistry(records=records, source_path=str(target))


@dataclass
class StandardRegistry:
    records: list[StandardRecord] = field(default_factory=list)
    source_path: str | None = None
    _by_base: dict[str, list[StandardRecord]] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        for record in self.records:
            self._by_base.setdefault(
                normalize_standard_no(record.standard_no), []
            ).append(record)

    def resolve(self, standard_no: str | None, edition: str | None) -> Resolution:
        base = normalize_standard_no(standard_no)
        candidates = self._by_base.get(base, [])
        if not candidates:
            return Resolution(reason="未入库")

        if edition:
            matches = [
                record
                for record in candidates
                if normalize_standard_no(record.edition)
                == normalize_standard_no(edition)
            ]
            if not matches:
                return Resolution(status="unknown", reason="版本未入库")
            if len(matches) > 1:
                return Resolution(status="conflict", reason="同版本多条记录")
            record = matches[0]
            successor = (
                self._successor(record) if record.status == "superseded" else None
            )
            return Resolution(
                record=record,
                basis="dated",
                status="superseded" if successor else _status(record),
                superseded_by=_label(successor) if successor else None,
            )

        current = [record for record in candidates if record.status == "current"]
        if len(current) == 1:
            return Resolution(record=current[0], basis="undated-current", status="current")
        if len(current) > 1:
            return Resolution(status="conflict", reason="多个现行版本")

        if len(candidates) == 1:
            record = candidates[0]
            if record.status == "superseded":
                successor = self._successor(record)
                if successor is not None and successor.status == "current":
                    return Resolution(
                        record=successor,
                        basis="undated-successor",
                        status="current",
                    )
                return Resolution(status="unknown", reason="无现行版本")
            return Resolution(
                record=record,
                basis="undated-single",
                status=_status(record),
            )

        return Resolution(status="conflict", reason="无唯一现行版本")

    def _successor(self, record: StandardRecord) -> StandardRecord | None:
        target = normalize_standard_no(_label(record))
        for other in self.records:
            if other is record:
                continue
            if any(
                normalize_standard_no(value) == target for value in other.supersedes
            ):
                return other
        return None


@dataclass
class VersionReport:
    doc_id: str
    total: int = 0
    resolved: int = 0
    unresolved: int = 0
    conflicts: int = 0
    superseded: int = 0
    undated: int = 0
    registry_source: str | None = None

    def to_markdown(self, graph: ReferenceGraph) -> str:
        relevance = {
            key: sum(1 for edge in graph.references if edge.relevance == key)
            for key in ("schema", "method", "informative", "unknown")
        }
        selected = graph.budget.get("selected_documents", 0)
        max_documents = graph.budget.get("max_documents", 8)
        max_pages = graph.budget.get("max_pages", 30)
        exceeded = graph.budget.get("exceeded", False)
        lines = [
            f"# 版本解析报告：{self.doc_id}",
            "",
            f"- 本地库：{self.registry_source or '未配置'}",
            f"- 引用边：{self.total}",
            f"- 已解析：{self.resolved}",
            f"- 未解析：{self.unresolved}",
            f"- 冲突：{self.conflicts}",
            f"- 替代版本：{self.superseded}",
            f"- 不注日期解析：{self.undated}",
            f"- 相关性：schema {relevance['schema']} / method {relevance['method']} / "
            f"informative {relevance['informative']} / unknown {relevance['unknown']}",
            f"- 展开预算：{selected}/{max_documents} 份、≤{max_pages} 页/份；"
            f"超限：{'是' if exceeded else '否'}",
            "",
            "## 明细",
            "",
            "| 标准号 | 版本 | 关系 | 页 | 条款 | 结果 | 依据/缺口 | 替代版本 | 相关性 | 展开 |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for edge in sorted(
            graph.references, key=lambda item: (item.standard_no or "", item.edition or "")
        ):
            if edge.resolved:
                result = "已解析"
                detail = edge.resolution_basis or ""
            elif edge.status == "conflict":
                result = "冲突"
                detail = edge.resolution_basis or "版本冲突"
            else:
                result = "未解析"
                detail = edge.resolution_basis or "未入库"
            lines.append(
                f"| {edge.standard_no or edge.raw} | {edge.edition or '-'} | "
                f"{edge.relation} | {edge.page_no or ''} | {edge.clause_id or ''} | "
                f"{result} | {detail} | {edge.superseded_by or ''} | "
                f"{edge.relevance or '-'} | {edge.selection_reason or '-'} |"
            )
        lines.append("")
        return "\n".join(lines)


def resolve_references(
    graph: ReferenceGraph, registry: StandardRegistry
) -> VersionReport:
    report = VersionReport(
        doc_id=graph.doc_id,
        total=len(graph.references),
        registry_source=registry.source_path,
    )
    gaps: list[str] = []
    for edge in graph.references:
        resolution = registry.resolve(edge.standard_no, edge.edition)
        edge.status = resolution.status
        edge.superseded_by = resolution.superseded_by
        if resolution.record is not None:
            edge.resolved = True
            edge.resolved_doc_id = resolution.record.doc_id
            edge.resolution_basis = resolution.basis
            if not edge.title and resolution.record.title:
                edge.title = resolution.record.title
            report.resolved += 1
            if resolution.status == "superseded":
                report.superseded += 1
            if resolution.basis and resolution.basis.startswith("undated"):
                report.undated += 1
            continue

        edge.resolved = False
        edge.resolved_doc_id = None
        edge.resolution_basis = resolution.reason
        if resolution.status == "conflict":
            report.conflicts += 1
        else:
            report.unresolved += 1
        label = (
            f"{edge.standard_no}-{edge.edition}"
            if edge.standard_no and edge.edition
            else edge.standard_no or edge.raw
        )
        gaps.append(f"{label}（{resolution.reason or '未解析'}）")

    graph.gaps = sorted(set(gaps))
    return report


def _plain(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _status(record: StandardRecord) -> ResolutionStatus:
    if record.status == "current":
        return "current"
    if record.status == "superseded":
        return "superseded"
    return "unknown"


def _label(record: StandardRecord) -> str:
    if record.edition:
        return f"{record.standard_no}-{record.edition}"
    return record.standard_no
