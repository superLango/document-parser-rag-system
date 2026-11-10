"""User feedback intake: validation, finding creation, conversation messages."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..contracts import DocumentResult, Evidence
from .config import SelfHealSettings
from .contracts import (
    EvidenceRef,
    FeedbackCategory,
    FeedbackCreate,
    FeedbackItem,
    FeedbackMessage,
    FeedbackStatus,
    FeedbackTarget,
    Finding,
    FindingSource,
    FindingVerdict,
    new_id,
)
from .locate import load_result, locate_job_dir
from .storage import SelfHealStore
from .triage import FeedbackAnalysis, analyze_feedback

CATEGORY_VERDICT = {
    FeedbackCategory.wrong_value: FindingVerdict.wrong,
    FeedbackCategory.missing_value: FindingVerdict.missing,
    FeedbackCategory.extra_value: FindingVerdict.extra,
    FeedbackCategory.wrong_unit: FindingVerdict.wrong,
    FeedbackCategory.wrong_requirement: FindingVerdict.wrong,
    FeedbackCategory.wrong_table: FindingVerdict.ambiguous,
    FeedbackCategory.duplicate: FindingVerdict.extra,
    FeedbackCategory.other: FindingVerdict.ambiguous,
}


def _has_target(target: FeedbackTarget) -> bool:
    return bool(target.record_id or target.table_id or target.feature)


def _analysis_note(analysis: FeedbackAnalysis) -> str:
    target = analysis.target
    if analysis.scope == "field":
        return f"已定位到记录 {target.record_id} 的 {target.property or '整条记录'}。"
    if analysis.scope == "table":
        return f"已定位到表 {target.table_id}（{target.feature or '相关检验项目'}）。"
    if analysis.scope == "clause":
        return f"已定位到{target.feature}。"
    if analysis.scope == "document":
        return "已按整篇文档处理。"
    return ""


def _load_evidence(job_dir: Path) -> dict[str, Evidence]:
    path = job_dir / "evidence.jsonl"
    items: dict[str, Evidence] = {}
    if not path.exists():
        return items
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            item = Evidence.model_validate(json.loads(line))
        except ValueError:
            continue
        items[item.evidence_id] = item
    return items


class FeedbackService:
    def __init__(self, store: SelfHealStore, settings: SelfHealSettings) -> None:
        self.store = store
        self.settings = settings

    def create(self, payload: FeedbackCreate) -> dict[str, Any]:
        problems: list[str] = []
        job_dir = locate_job_dir(self.settings, payload.job_id)
        result = load_result(job_dir) if job_dir else None
        finding: Finding | None = None
        evidence_refs: list[EvidenceRef] = []
        target = payload.target
        expected = payload.expected_value
        located_note = ""
        analysis: FeedbackAnalysis | None = None

        if result is None:
            problems.append("找不到该任务的可读产物，无法定位问题")
        else:
            if not _has_target(target):
                analysis = analyze_feedback(
                    result,
                    payload.description,
                    payload.source_quote or "",
                    category=payload.category.value,
                    expected_value=payload.expected_value,
                    model_url=self.settings.model_base_url,
                    model_name=self.settings.model_name,
                    timeout=self.settings.model_timeout,
                )
                if analysis.action == "need_more_info":
                    problems.append(
                        analysis.need_info
                        or "还需要补充具体的问题位置或期望值"
                    )
                else:
                    target = analysis.target
                    expected = expected or analysis.expected
                    located_note = _analysis_note(analysis)
            problems.extend(self._validate_target(payload.category, target, result))
            evidence = _load_evidence(job_dir) if job_dir else {}
            if payload.source_quote:
                match = next(
                    (
                        item
                        for item in evidence.values()
                        if payload.source_quote in item.quote
                    ),
                    None,
                )
                if match is None:
                    problems.append("原文引文未能在证据中找到，请补充更精确的引文")
                else:
                    evidence_refs.append(_ref(match))
            else:
                evidence_refs = [
                    ref
                    for ref in [self._evidence_ref(target, result, job_dir)]
                    if ref is not None
                ]

        item = FeedbackItem(
            feedback_id=new_id("fb"),
            doc_id=payload.doc_id,
            job_id=payload.job_id,
            user_id=payload.user_id,
            category=payload.category,
            target=target,
            description=payload.description,
            expected_value=expected,
            source_quote=payload.source_quote,
            status=FeedbackStatus.open if not problems else FeedbackStatus.needs_more_info,
            priority=payload.priority,
        )
        self.store.add_feedback(item)

        if result is not None and not problems:
            observed = self._observed(target, result)
            finding = Finding(
                doc_id=payload.doc_id,
                job_id=payload.job_id,
                source=FindingSource.user,
                verdict=CATEGORY_VERDICT[payload.category],
                target=target,
                expected=expected,
                observed=observed,
                evidence=evidence_refs,
                rule_code=analysis.rule_code if analysis else "user_feedback",
                confidence=0.9,
                priority=payload.priority,
            )
            if not self.store.add_finding(finding, feedback_id=item.feedback_id):
                finding = None
                problems.append("同一问题已有待处理记录，请补充新的差异说明")
                self.store.update_feedback(
                    item.feedback_id, status=FeedbackStatus.needs_more_info.value
                )

        reply = (
            "已收到反馈并生成问题记录，开始自动核查。"
            if not problems
            else "还需要补充信息：" + "；".join(problems)
        )
        if located_note and not problems:
            reply = located_note + reply
        self.store.add_message(
            FeedbackMessage(
                feedback_id=item.feedback_id, role="system", content=reply
            )
        )
        return {"feedback": item, "finding": finding, "problems": problems}

    def ensure_located(self, feedback_id: str) -> list[Finding]:
        """Locate an old free-text feedback that was stored without findings."""

        item = self.store.get_feedback(feedback_id)
        if item is None:
            return []
        findings = self.store.list_findings_for_feedback(feedback_id)
        if findings or _has_target(item.target):
            return findings
        job_dir = locate_job_dir(self.settings, item.job_id)
        result = load_result(job_dir) if job_dir else None
        if result is None:
            return findings
        analysis = analyze_feedback(
            result,
            item.description,
            item.source_quote or "",
            category=item.category.value,
            expected_value=item.expected_value,
            model_url=self.settings.model_base_url,
            model_name=self.settings.model_name,
            timeout=self.settings.model_timeout,
        )
        if analysis.action == "need_more_info":
            return findings
        expected = item.expected_value or analysis.expected
        self.store.update_feedback_target(feedback_id, analysis.target, expected)
        evidence = self._evidence_ref(analysis.target, result, job_dir)
        finding = Finding(
            doc_id=item.doc_id,
            job_id=item.job_id,
            source=FindingSource.user,
            verdict=CATEGORY_VERDICT[item.category],
            target=analysis.target,
            expected=expected,
            observed=self._observed(analysis.target, result),
            evidence=[evidence] if evidence is not None else [],
            rule_code=analysis.rule_code,
            confidence=0.9,
            priority=item.priority,
        )
        if self.store.add_finding(finding, feedback_id=feedback_id):
            return [finding]
        return findings

    def _evidence_ref(
        self, target: FeedbackTarget, result: DocumentResult, job_dir: Path | None
    ) -> EvidenceRef | None:
        evidence = _load_evidence(job_dir) if job_dir else {}
        if not evidence:
            return None
        value = self._target_value(target, result)
        if value is not None:
            item = evidence.get(value.evidence_id)
            return _ref(item) if item is not None else None
        if target.table_id:
            item = next(
                (
                    row
                    for row in evidence.values()
                    if row.table_id == target.table_id
                ),
                None,
            )
            return _ref(item) if item is not None else None
        item = next(iter(evidence.values()), None)
        return _ref(item) if item is not None else None

    def add_message(self, feedback_id: str, content: str, role: str = "user") -> FeedbackMessage:
        message = FeedbackMessage(
            feedback_id=feedback_id, role=role, content=content
        )
        self.store.add_message(message)
        return message

    @staticmethod
    def _validate_target(
        category: FeedbackCategory,
        target: FeedbackTarget,
        result: DocumentResult,
    ) -> list[str]:
        problems: list[str] = []
        if target.table_id:
            table_ids = {table.table_id for table in result.tables}
            if target.table_id not in table_ids:
                problems.append(f"表号 {target.table_id} 不在该文档产物中")
        record = None
        if target.record_id:
            record = next(
                (item for item in result.records if item.record_id == target.record_id),
                None,
            )
            if record is None:
                problems.append(f"记录 {target.record_id} 不在该文档产物中")
        if record is not None and target.property:
            if (
                target.property not in record.properties
                and category != FeedbackCategory.missing_value
            ):
                problems.append(
                    f"字段 {target.property} 不在记录 {target.record_id} 中"
                )
        return problems

    @staticmethod
    def _target_value(target: FeedbackTarget, result: DocumentResult):
        if not target.record_id or not target.property:
            return None
        record = next(
            (item for item in result.records if item.record_id == target.record_id),
            None,
        )
        if record is None:
            return None
        return record.properties.get(target.property)

    @staticmethod
    def _observed(target: FeedbackTarget, result: DocumentResult) -> str | None:
        value = FeedbackService._target_value(target, result)
        return value.raw if value else None


def _ref(item: Evidence) -> EvidenceRef:
    return EvidenceRef(
        page_no=item.page_no,
        table_id=item.table_id,
        row=item.row,
        col=item.col,
        quote=item.quote,
    )
