"""Automatic audit: packet building, deterministic checks, model review.

The audit reads an existing job directory (``result.json`` + ``evidence.jsonl``)
and never writes into it. Deterministic rules run first; the model only reviews
a trimmed packet and its findings must point at a real record/field, otherwise
they are dropped before they can become repair proposals.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from ..contracts import DocumentResult, Evidence, ExtractedValue, Record, TableGrid
from .config import SelfHealSettings
from .contracts import (
    AuditRun,
    EvidenceRef,
    FeedbackTarget,
    Finding,
    FindingSource,
    FindingVerdict,
)
from .storage import SelfHealStore

UNIT_PROPERTIES = {
    "Rm": "MPa",
    "Rp0.2": "MPa",
    "ReH": "MPa",
    "A": "%",
    "A50mm": "%",
    "Z": "%",
    "KV2": "J",
    "KU2": "J",
    "HB": "HBW",
    "HRC": "HRC",
    "HV": "HV",
    "E": "GPa",
}
VERDICT_BY_TYPE = {
    "wrong_value": FindingVerdict.wrong,
    "wrong_unit": FindingVerdict.wrong,
    "wrong_requirement": FindingVerdict.wrong,
    "missing_value": FindingVerdict.missing,
    "extra_value": FindingVerdict.extra,
}
SYSTEM_PROMPT = "你是金属材料标准的抽取结果审查员。只输出 JSON，不要解释。"
USER_TEMPLATE = """审查下面的抽取记录是否与原文表格一致。

只报告以下五类问题：wrong_value（数值不符）、missing_value（原文有值但记录缺失）、
wrong_unit（单位不符）、wrong_requirement（比较符不符）、extra_value（记录出现原文没有的值）。
记录约定：condition 合并多个条件列是正常的；字段使用 Rm/Rp0.2/A/Z/HB 等规范名；
原文为 "-"、"/"、"—" 或空时记录缺失不算 missing_value；同一错误只报一条。
没有问题时输出 {{"findings":[]}}。
输出格式：{{"findings":[{{"record_id":"...","field":"...","type":"wrong_value|missing_value|wrong_unit|wrong_requirement|extra_value","reason":"..."}}]}}

表号：{table_id}  表题：{caption}  表型：{profile}
原文表头：{header}
原文数据行：
{rows}
抽取记录：
{records}
"""


@dataclass
class TablePacket:
    table_id: str
    page_no: int
    caption: str | None
    profile: str
    header: list[list[str]]
    header_rows: int
    rows: list[list[str]]
    records: list[dict[str, Any]] = field(default_factory=list)
    evidence: dict[str, Evidence] = field(default_factory=dict)

    def render_rows(self) -> str:
        return "\n".join(
            f"{index}. " + " | ".join(str(cell) for cell in row)
            for index, row in enumerate(self.rows, start=1)
        )

    def record_payload(self, record: Record) -> dict[str, Any]:
        properties: dict[str, Any] = {}
        for name, value in record.properties.items():
            item: dict[str, Any] = {
                "raw": value.raw,
                "value": value.value,
                "unit": value.unit,
                "comparator": value.comparator,
            }
            if value.lower is not None:
                item["lower"] = value.lower
            if value.upper is not None:
                item["upper"] = value.upper
            properties[name] = item
        return {
            "record_id": record.record_id,
            "grade": record.grade or record.grade_level,
            "condition": record.condition,
            "properties": properties,
        }


@dataclass
class AuditPacket:
    doc_id: str
    job_id: str
    standard_no: str | None
    title: str | None
    tables: list[TablePacket] = field(default_factory=list)
    result: DocumentResult | None = None
    evidence_by_id: dict[str, Evidence] = field(default_factory=dict)

    @property
    def record_count(self) -> int:
        return sum(len(table.records) for table in self.tables)


class Reviewer(Protocol):
    name: str

    def review(self, packet: TablePacket, doc: AuditPacket) -> list[dict[str, Any]]:
        ...


class HttpReviewer:
    """OpenAI-compatible reviewer (Qwen3.6-35B-A3B by default)."""

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout: float = 300.0,
        max_tokens: int = 1024,
    ) -> None:
        import httpx

        self.base_url = base_url.rstrip("/")
        self.name = model
        self.timeout = timeout
        self.max_tokens = max_tokens
        self._client = httpx.Client(timeout=timeout, trust_env=False)

    def close(self) -> None:
        self._client.close()

    def review(self, packet: TablePacket, doc: AuditPacket) -> list[dict[str, Any]]:
        prompt = USER_TEMPLATE.format(
            table_id=packet.table_id,
            caption=packet.caption or "",
            profile=packet.profile,
            header=json.dumps(packet.header, ensure_ascii=False),
            rows=packet.render_rows(),
            records=json.dumps(packet.records, ensure_ascii=False, indent=1),
        )
        response = self._client.post(
            f"{self.base_url}/chat/completions",
            json={
                "model": self.name,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.0,
                "max_tokens": self.max_tokens,
                "response_format": {"type": "json_object"},
                "stream": False,
            },
        )
        response.raise_for_status()
        data = response.json()
        content = str(data["choices"][0]["message"]["content"])
        return _parse_findings(content)


def _parse_findings(text: str) -> list[dict[str, Any]]:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        payload = json.loads(raw[start : end + 1])
    except ValueError:
        return []
    findings = payload.get("findings")
    return findings if isinstance(findings, list) else []


def load_job(job_dir: str | Path) -> tuple[DocumentResult, dict[str, Evidence]]:
    base = Path(job_dir)
    result = DocumentResult.model_validate(
        json.loads((base / "result.json").read_text(encoding="utf-8"))
    )
    evidence: dict[str, Evidence] = {}
    evidence_path = base / "evidence.jsonl"
    if evidence_path.exists():
        for line in evidence_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            item = Evidence.model_validate(json.loads(line))
            evidence[item.evidence_id] = item
    return result, evidence


def build_packet(
    job_dir: str | Path,
    *,
    max_tables: int = 20,
    max_records: int = 200,
) -> AuditPacket:
    result, evidence = load_job(job_dir)
    job_id = Path(job_dir).name
    table_map: dict[str, TableGrid] = {table.table_id: table for table in result.tables}
    packets: list[TablePacket] = []
    total_records = 0
    for table in result.tables:
        records = [r for r in result.records if r.source_table_id == table.table_id]
        if not records or len(packets) >= max_tables:
            continue
        packet = TablePacket(
            table_id=table.table_id,
            page_no=table.page_no,
            caption=table.caption,
            profile=table.profile,
            header=table.header_paths,
            header_rows=table.header_rows,
            rows=table.rows,
        )
        for record in records:
            if total_records >= max_records:
                break
            packet.records.append(packet.record_payload(record))
            for value in record.properties.values():
                item = evidence.get(value.evidence_id)
                if item is not None:
                    packet.evidence[value.evidence_id] = item
            total_records += 1
        if packet.records:
            packets.append(packet)
    return AuditPacket(
        doc_id=result.document.doc_id,
        job_id=job_id,
        standard_no=result.document.standard_no,
        title=result.document.title,
        tables=packets,
        result=result,
        evidence_by_id=evidence,
    )


def _normalize(text: str | None) -> str:
    return re.sub(r"\s+", "", str(text or "")).replace("—", "-").replace("–", "-")


def _row_cells(table: TableGrid, row_index: int | None) -> list[str]:
    if row_index is None or row_index < 0 or row_index >= len(table.rows):
        return []
    return [str(cell) for cell in table.rows[row_index]]


def _value_evidence(
    table: TableGrid, value: ExtractedValue, evidence: dict[str, Evidence]
) -> Evidence | None:
    item = evidence.get(value.evidence_id)
    if item is None:
        return None
    return item


def deterministic_findings(
    packet: AuditPacket, job_dir: str | Path
) -> list[Finding]:
    """Rules that need no model: evidence grounding, duplicates, units."""

    if packet.result is None:
        return []
    result = packet.result
    table_map = {table.table_id: table for table in result.tables}
    findings: list[Finding] = []
    for table in result.tables:
        records = [r for r in result.records if r.source_table_id == table.table_id]
        seen: dict[tuple[str, str], str] = {}
        for record in records:
            grade = record.grade or record.grade_level or ""
            key = (grade, record.condition or "")
            if grade and key in seen:
                findings.append(
                    Finding(
                        doc_id=packet.doc_id,
                        job_id=packet.job_id,
                        source=FindingSource.audit,
                        verdict=FindingVerdict.ambiguous,
                        target=FeedbackTarget(
                            record_id=record.record_id,
                            table_id=table.table_id,
                            grade=record.grade,
                            condition=record.condition,
                        ),
                        expected=seen[key],
                        observed=record.record_id,
                        rule_code="duplicate_record",
                        confidence=0.9,
                    )
                )
            elif grade:
                seen[key] = record.record_id
            for name, value in record.properties.items():
                evidence_item = _value_evidence(table, value, packet.evidence_by_id)
                if value.evidence_id and evidence_item is None:
                    findings.append(
                        _finding(
                            packet,
                            record,
                            table,
                            name,
                            FindingVerdict.unverifiable,
                            rule_code="evidence_missing",
                            observed=value.raw,
                            confidence=0.95,
                        )
                    )
                if evidence_item is not None:
                    cells = _row_cells(table, evidence_item.row)
                    quote = _normalize(evidence_item.quote)
                    if quote and cells and not any(quote in _normalize(cell) for cell in cells):
                        findings.append(
                            _finding(
                                packet,
                                record,
                                table,
                                name,
                                FindingVerdict.wrong,
                                rule_code="evidence_quote_mismatch",
                                expected=evidence_item.quote,
                                observed=value.raw,
                                confidence=0.9,
                                evidence=evidence_item,
                            )
                        )
                if (
                    isinstance(value.value, (int, float))
                    and not (value.unit or "").strip()
                    and name in UNIT_PROPERTIES
                ):
                    findings.append(
                        _finding(
                            packet,
                            record,
                            table,
                            name,
                            FindingVerdict.ambiguous,
                            rule_code="unit_missing",
                            expected=UNIT_PROPERTIES[name],
                            observed="",
                            confidence=0.7,
                            evidence=evidence_item,
                        )
                    )
    return findings


def _finding(
    packet: AuditPacket,
    record: Record,
    table: TableGrid,
    name: str,
    verdict: FindingVerdict,
    *,
    rule_code: str,
    expected: str | None = None,
    observed: str | None = None,
    confidence: float = 0.6,
    evidence: Evidence | None = None,
) -> Finding:
    refs: list[EvidenceRef] = []
    if evidence is not None:
        refs.append(
            EvidenceRef(
                page_no=evidence.page_no,
                table_id=evidence.table_id or table.table_id,
                row=evidence.row,
                col=evidence.col,
                quote=evidence.quote,
            )
        )
    return Finding(
        doc_id=packet.doc_id,
        job_id=packet.job_id,
        source=FindingSource.audit,
        verdict=verdict,
        target=FeedbackTarget(
            record_id=record.record_id,
            property=name,
            table_id=table.table_id,
            grade=record.grade,
            condition=record.condition,
        ),
        expected=expected,
        observed=observed,
        evidence=refs,
        rule_code=rule_code,
        confidence=confidence,
    )


def model_findings(
    packet: AuditPacket, reviewer: Reviewer
) -> list[Finding]:
    """Validate model output against the packet; drop anything ungrounded."""

    result: list[Finding] = []
    if packet.result is None:
        return result
    records = {record.record_id: record for record in packet.result.records}
    tables = {table.table_id: table for table in packet.result.tables}
    for table_packet in packet.tables:
        try:
            raw_findings = reviewer.review(table_packet, packet)
        except Exception:  # noqa: BLE001 - one table failure must not stop the audit
            continue
        table = tables.get(table_packet.table_id)
        for item in raw_findings:
            if not isinstance(item, dict):
                continue
            record_id = str(item.get("record_id") or "")
            field_name = str(item.get("field") or "").strip()
            error_type = str(item.get("type") or "")
            record = records.get(record_id)
            if record is None or error_type not in VERDICT_BY_TYPE:
                continue
            property_name = _match_property(field_name, record)
            if property_name is None:
                continue
            value = record.properties.get(property_name)
            evidence = (
                packet.evidence_by_id.get(value.evidence_id) if value else None
            )
            refs: list[EvidenceRef] = []
            if evidence is not None:
                refs.append(
                    EvidenceRef(
                        page_no=evidence.page_no,
                        table_id=evidence.table_id or table_packet.table_id,
                        row=evidence.row,
                        col=evidence.col,
                        quote=evidence.quote,
                    )
                )
            result.append(
                Finding(
                    doc_id=packet.doc_id,
                    job_id=packet.job_id,
                    source=FindingSource.audit,
                    verdict=VERDICT_BY_TYPE[error_type],
                    target=FeedbackTarget(
                        record_id=record.record_id,
                        property=property_name,
                        table_id=record.source_table_id,
                        grade=record.grade,
                        condition=record.condition,
                    ),
                    expected=item.get("reason") or None,
                    observed=value.raw if value else None,
                    evidence=refs,
                    rule_code=f"model_{error_type}",
                    confidence=0.6,
                )
            )
    return result


FIELD_PREFIXES = ("properties.", "property.", "record.", "fields.")


def normalize_field(field: str) -> str:
    text = str(field or "").strip()
    for prefix in FIELD_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix) :]
    for suffix in (".unit", ".value", ".raw", ".comparator"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    if "." in text:
        text = text.split(".")[-1]
    return text


def _match_property(field: str, record: Record) -> str | None:
    name = normalize_field(field)
    if name in record.properties:
        return name
    lowered = name.lower()
    for key in record.properties:
        if key.lower() == lowered:
            return key
    return None


def audit_job(
    job_dir: str | Path,
    out_dir: str | Path,
    *,
    settings: SelfHealSettings | None = None,
    store: SelfHealStore | None = None,
    reviewer: Reviewer | None = None,
    use_model: bool = True,
) -> list[Finding]:
    settings = settings or SelfHealSettings.from_env()
    packet = build_packet(
        job_dir,
        max_tables=settings.max_audit_tables,
        max_records=settings.max_audit_records,
    )
    findings = deterministic_findings(packet, job_dir)
    model_findings_list: list[Finding] = []
    status = "deterministic_only"
    detail = "no reviewer configured"
    owned_reviewer = None
    if use_model and reviewer is None and settings.model_base_url:
        reviewer = HttpReviewer(
            settings.model_base_url,
            settings.model_name,
            timeout=settings.model_timeout,
        )
        owned_reviewer = reviewer
    if use_model and reviewer is not None:
        model_findings_list = model_findings(packet, reviewer)
        findings.extend(model_findings_list)
        status = "completed"
        detail = f"model={getattr(reviewer, 'name', 'unknown')}"
    if owned_reviewer is not None:
        owned_reviewer.close()

    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    payload = [item.model_dump(mode="json") for item in findings]
    (out_path / "findings.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (out_path / "audit_packet.json").write_text(
        json.dumps(
            {
                "doc_id": packet.doc_id,
                "job_id": packet.job_id,
                "tables": [
                    {
                        "table_id": table.table_id,
                        "page_no": table.page_no,
                        "caption": table.caption,
                        "profile": table.profile,
                        "records": len(table.records),
                    }
                    for table in packet.tables
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    if store is not None:
        for finding in findings:
            store.add_finding(finding)
        store.add_audit_run(
            AuditRun(
                doc_id=packet.doc_id,
                job_id=packet.job_id,
                model=getattr(reviewer, "name", "deterministic"),
                packet_tables=len(packet.tables),
                packet_records=packet.record_count,
                findings=len(findings),
                status=status,
                detail=detail,
            )
        )
    return findings
