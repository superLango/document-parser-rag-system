"""Feedback/audit finding -> L1/L2/L3 -> gates -> reply orchestration."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Callable

from .audit import Reviewer, audit_job as run_audit_job
from .config import SelfHealSettings
from .contracts import (
    EvidenceRef,
    FeedbackStatus,
    Finding,
    FindingSource,
    FindingStatus,
    GateDecision,
    GateResult,
    FindingVerdict,
    ProposalStatus,
    RepairLevel,
    RepairOutcome,
    RepairProposal,
    new_id,
)
from .diagnose import Diagnosis, diagnose
from .feedback import CATEGORY_VERDICT, FeedbackService
from .gates import GateContext, evaluate
from .l1 import L1Repairer, target_resolved
from .l2 import L2Repairer, rollback_overlay
from .l3 import CodePatchService
from .locate import locate_job_dir, load_result
from .planner import HeuristicPlanner, ModelPlanner, Planner
from .storage import SelfHealStore
from .table_fix import plan_table_fix

PatchProvider = Callable[[Finding, Any], str | None]
RegressionCheck = Callable[[], tuple[bool, str]]
AUDIT_RULE_CODES = {
    "user_feedback_table",
    "user_feedback_document",
    "user_feedback_clause",
}


class SelfHealPipeline:
    def __init__(
        self,
        store: SelfHealStore,
        settings: SelfHealSettings,
        *,
        planner: Planner | None = None,
        patch_provider: PatchProvider | None = None,
        regression_check: RegressionCheck | None = None,
    ) -> None:
        self.store = store
        self.settings = settings
        self.l1 = L1Repairer(settings)
        self.l2 = L2Repairer(settings)
        self.l3 = CodePatchService(settings)
        self.planner = planner
        self.patch_provider = patch_provider
        self.regression_check = regression_check
        self.feedback = FeedbackService(store, settings)

    # -- audit ---------------------------------------------------------
    def audit_job(
        self,
        job_dir: str | Path,
        out_dir: str | Path | None = None,
        reviewer: Reviewer | None = None,
    ) -> list[Finding]:
        target = Path(out_dir) if out_dir else Path(job_dir) / "selfheal_audit"
        return run_audit_job(
            job_dir,
            target,
            settings=self.settings,
            store=self.store,
            reviewer=reviewer,
        )

    # -- user feedback -------------------------------------------------
    def process_feedback(self, feedback_id: str) -> RepairOutcome:
        item = self.store.get_feedback(feedback_id)
        if item is None:
            raise KeyError(feedback_id)
        iterations = self.store.feedback_iterations(feedback_id) + 1
        if iterations > self.settings.max_iterations:
            for finding in self.store.list_findings_for_feedback(feedback_id):
                self.store.update_finding_status(finding.finding_id, FindingStatus.quarantined.value)
            self.store.update_feedback(feedback_id, status=FeedbackStatus.needs_more_info.value)
            self.feedback.add_message(
                feedback_id,
                f"已超过最大自动修复次数（{self.settings.max_iterations}），转入人工处理。",
            )
            return RepairOutcome(
                feedback_id=feedback_id,
                status=FeedbackStatus.needs_more_info,
                reply="超过最大自动修复次数，转入人工处理",
                iterations=iterations,
            )

        self.store.update_feedback(
            feedback_id, status=FeedbackStatus.processing.value, iterations=iterations
        )
        job_dir = locate_job_dir(self.settings, item.job_id)
        result = load_result(job_dir) if job_dir else None
        if result is None or job_dir is None:
            return self._finish(
                feedback_id,
                FeedbackStatus.needs_more_info,
                "找不到任务产物，无法复现该问题。",
                iterations,
            )

        diagnosis = diagnose(
            self.settings,
            result,
            job_dir,
            description=item.description,
            category=item.category.value,
            target=item.target,
            expected=item.expected_value,
            source_quote=item.source_quote or "",
        )
        self._save_diagnosis(feedback_id, diagnosis)

        findings = self.feedback.ensure_located(feedback_id)
        if findings:
            finding = findings[0]
            if diagnosis.target and _diagnosis_target_present(diagnosis, result):
                finding = finding.model_copy(
                    update={
                        "target": diagnosis.target,
                        "expected": finding.expected or diagnosis.expected,
                        "evidence": finding.evidence
                        or [
                            EvidenceRef(**entry)
                            for entry in diagnosis.evidence
                            if entry.get("quote")
                        ],
                        "rule_code": finding.rule_code
                        or f"diagnosis_{diagnosis.scope}",
                    }
                )
        else:
            finding = self._finding_from_diagnosis(item, diagnosis)
            if finding is None:
                return self._finish(
                    feedback_id,
                    FeedbackStatus.unresolved,
                    self._evidence_reply(
                        diagnosis,
                        "诊断",
                        "已定位问题，但未生成可核查的问题记录",
                    ),
                    iterations,
                )
            if not self.store.add_finding(finding, feedback_id=feedback_id):
                existing = self.store.find_finding(
                    item.doc_id, finding.target, finding.verdict
                )
                if existing is not None:
                    finding = existing

        base = self.settings.jobs_root / feedback_id
        attempts: list[str] = []
        resolver = self._resolver(finding, diagnosis)

        if diagnosis.action == "document_meta":
            meta = self._apply_document_meta(
                feedback_id, finding, diagnosis, result, base, iterations
            )
            if meta is not None:
                return meta
            attempts.append("文档元数据修正未通过")

        if diagnosis.action == "table_repair" and finding.target.table_id:
            fixed = self._apply_table_fix(
                feedback_id, finding, item.description, iterations
            )
            if fixed is not None:
                return fixed
            attempts.append("表结构修复未通过")

        if diagnosis.action != "report_only":
            l1 = self._attempt_l1(
                finding,
                job_dir,
                base / "sandbox",
                iterations,
                target_ok=resolver,
            )
            attempts.append(l1["detail"])
            if l1["ok"]:
                self.store.update_finding_status(
                    finding.finding_id, FindingStatus.fixed.value
                )
                reply = self._evidence_reply(
                    diagnosis,
                    "L1 文档重解析（沙箱）",
                    "已生成修正，等待你确认应用。"
                    f"\n变更：{json.dumps(l1['diff'].get('summary'), ensure_ascii=False)}",
                )
                return self._finish(
                    feedback_id,
                    FeedbackStatus.fixed,
                    reply,
                    iterations,
                    l1["proposal"],
                    l1["gate"],
                )

            l2 = self._attempt_l2(finding, job_dir, result, base, iterations)
            attempts.append(l2["detail"])
            if l2["ok"]:
                self.store.update_finding_status(
                    finding.finding_id, FindingStatus.fixed.value
                )
                reply = self._evidence_reply(
                    diagnosis,
                    f"L2 规则修复（{l2['proposal'].operator}）",
                    "已生成候选规则并通过 shadow 验证，等待你确认应用。"
                    f"\n签名：{l2['proposal'].target_signature}",
                )
                return self._finish(
                    feedback_id,
                    FeedbackStatus.fixed,
                    reply,
                    iterations,
                    l2["proposal"],
                    l2["gate"],
                )

            l3 = self._attempt_l3(
                finding,
                result,
                iterations,
                diagnosis=diagnosis,
                feedback_id=feedback_id,
            )
            attempts.append(l3["detail"])
            if l3["patch"] is not None:
                patch = l3["patch"]
                reply = self._evidence_reply(
                    diagnosis,
                    "L3 代码修复",
                    "已生成规则补丁，等待确认。"
                    f"\n文件：{', '.join(patch.files)}"
                    f"\n状态：{patch.status.value}，原因：{patch.reason}",
                )
                return self._finish(
                    feedback_id, FeedbackStatus.processing, reply, iterations
                )

        reply = self._evidence_reply(
            diagnosis,
            "；".join(attempts) or "仅诊断，未执行修改",
            "自动修复未通过门禁，已保留证据与尝试记录。",
        )
        return self._finish(
            feedback_id, FeedbackStatus.unresolved, reply, iterations
        )

    def _save_diagnosis(self, feedback_id: str, diagnosis: Diagnosis) -> None:
        base = self.settings.jobs_root / feedback_id
        base.mkdir(parents=True, exist_ok=True)
        (base / "diagnosis.json").write_text(
            json.dumps(diagnosis.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def _finding_from_diagnosis(self, item, diagnosis: Diagnosis) -> Finding | None:
        target = diagnosis.target
        if not (target.record_id or target.table_id or target.feature):
            return None
        evidence = [
            EvidenceRef(**entry)
            for entry in diagnosis.evidence
            if entry.get("quote")
        ]
        return Finding(
            doc_id=item.doc_id,
            job_id=item.job_id,
            source=FindingSource.user,
            verdict=CATEGORY_VERDICT.get(item.category, FindingVerdict.ambiguous),
            target=target,
            expected=diagnosis.expected,
            evidence=evidence,
            rule_code=f"diagnosis_{diagnosis.scope}",
            confidence=diagnosis.confidence,
            priority=item.priority,
        )

    def _resolver(self, finding: Finding, diagnosis: Diagnosis):
        def check(before: Any, after: Any) -> bool:
            scope = diagnosis.scope
            expected = diagnosis.expected
            if scope == "document_meta":
                field = (
                    diagnosis.correction.field
                    if diagnosis.correction is not None
                    else None
                ) or "standard_no"
                if diagnosis.target.feature in {"standard_no", "title", "version"}:
                    field = diagnosis.target.feature
                current = getattr(after.document, field, None)
                return bool(current) and _norm(current) == _norm(expected)
            if scope == "missing_item":
                feature = diagnosis.target.feature or expected
                return _feature_present(after, feature)
            if scope == "missing_field":
                name = (
                    diagnosis.target.property
                    or diagnosis.target.feature
                    or expected
                )
                return _field_present(after, name, diagnosis.target.table_id)
            if scope == "table" and diagnosis.target.table_id and not diagnosis.target.property:
                return _table_changed(before, after, diagnosis.target.table_id)
            if finding.target.record_id:
                return target_resolved(finding, after)
            return _document_changed(before, after)

        return check

    def _apply_document_meta(
        self,
        feedback_id: str,
        finding: Finding,
        diagnosis: Diagnosis,
        result: Any,
        base: Path,
        iterations: int,
    ) -> RepairOutcome | None:
        """Patch document metadata (standard number/title) without a full reparse."""

        field = (
            diagnosis.correction.field
            if diagnosis.correction is not None
            else None
        ) or "standard_no"
        if diagnosis.target.feature in {"standard_no", "title", "version"}:
            field = diagnosis.target.feature
        value = diagnosis.expected or (
            diagnosis.correction.value
            if diagnosis.correction is not None
            else None
        )
        if not value:
            return None
        before_value = getattr(result.document, field, None)
        if _norm(before_value) == _norm(value):
            return None

        out_dir = base / "document_meta"
        out_dir.mkdir(parents=True, exist_ok=True)
        after = result.model_copy(
            update={
                "document": result.document.model_copy(update={field: value})
            }
        )
        (out_dir / "result.json").write_text(
            json.dumps(after.model_dump(mode="json"), ensure_ascii=False, indent=2)
            + "\n",
            encoding="utf-8",
        )
        diff = {
            "reproduced": True,
            "target_resolved": True,
            "new_errors": 0,
            "summary": {
                "records_before": len(result.records),
                "records_after": len(result.records),
                "added": 0,
                "removed": 0,
                "changed": 1,
            },
            "changed": [
                {
                    "field": field,
                    "before": before_value,
                    "after": value,
                }
            ],
        }
        (out_dir / "repair_diff.json").write_text(
            json.dumps(diff, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        proposal = RepairProposal(
            finding_ids=[finding.finding_id],
            level=RepairLevel.L1,
            operator="document.meta",
            params={"field": field, "value": value},
            status=ProposalStatus.verified,
            artifact_dir=str(out_dir),
        )
        self.store.add_proposal(proposal)
        gate = self._gate(finding, proposal, diff, iterations)
        if gate.decision != GateDecision.accept:
            self.store.update_proposal_status(
                proposal.proposal_id, ProposalStatus.rolled_back.value
            )
            return None
        self.store.update_proposal_status(
            proposal.proposal_id, ProposalStatus.applied.value
        )
        self.store.update_finding_status(finding.finding_id, FindingStatus.fixed.value)
        reply = self._evidence_reply(
            diagnosis,
            "文档元数据修正",
            "已生成修正，等待你确认应用。"
            f"\n{field}: {before_value or '空'} → {value}",
        )
        return self._finish(
            feedback_id,
            FeedbackStatus.fixed,
            reply,
            iterations,
            proposal,
            gate,
        )

    def _evidence_reply(
        self, diagnosis: Diagnosis, executed: str, outcome: str
    ) -> str:
        lines = [
            f"判定：{_diagnosis_label(diagnosis)}"
            f"（{diagnosis.root_cause}，置信度 {diagnosis.confidence:.2f}）"
        ]
        if diagnosis.expected:
            lines.append(f"正解：{diagnosis.expected}")
        if diagnosis.mechanism:
            lines.append(f"机制：{diagnosis.mechanism}")
        if diagnosis.evidence:
            lines.append("依据：")
            for entry in diagnosis.evidence[:6]:
                lines.append(
                    f"- {_evidence_label(entry)}「{str(entry.get('quote') or '')[:120]}」"
                )
        elif diagnosis.checks:
            lines.append("依据（已核对）：")
            for check in diagnosis.checks[:8]:
                lines.append(f"- {check}")
        else:
            lines.append("依据：未在原文、表网格、条款中找到可确认内容")
        lines.append(f"已执行：{executed or '仅诊断'}")
        lines.append(f"结果：{outcome}")
        return "\n".join(lines)

    def _apply_table_fix(
        self,
        feedback_id: str,
        finding: Finding,
        feedback: str,
        iterations: int,
    ) -> RepairOutcome | None:
        """Ask the model for a table_repair spec and run it in the sandbox."""

        job_dir = locate_job_dir(self.settings, finding.job_id)
        before = load_result(job_dir) if job_dir else None
        if before is None:
            return None
        table = next(
            (
                item
                for item in before.tables
                if item.table_id == finding.target.table_id
            ),
            None,
        )
        if table is None:
            return None
        records = [
            record
            for record in before.records
            if record.source_table_id == table.table_id
        ]
        plan = plan_table_fix(
            table,
            records,
            feedback,
            model_url=self.settings.model_base_url,
            model_name=self.settings.model_name,
            timeout=self.settings.model_timeout,
        )
        if plan is None:
            return None
        out_dir = self.settings.jobs_root / feedback_id / "table_fix"
        result = self.l1.apply(
            finding,
            job_dir,
            out_dir,
            proposal_id=new_id("prp"),
            table_repair=plan.spec,
        )
        if not result.ok or result.proposal is None:
            return None
        self.store.add_proposal(result.proposal)
        gate = self._gate(finding, result.proposal, result.diff, iterations)
        if gate.decision != GateDecision.accept:
            return None
        self.store.update_proposal_status(
            result.proposal.proposal_id, ProposalStatus.applied.value
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "plan.json").write_text(
            json.dumps(
                {
                    "table_id": plan.table_id,
                    "spec": plan.spec,
                    "reason": plan.reason,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        summary = result.diff.get("summary") or {}
        changes = _table_change_count(result.diff, finding.target.table_id)
        reply = (
            f"已让模型根据反馈生成表修复方案并重新解析{_scope_label(finding)}，"
            f"变更 {changes} 处（新增 {summary.get('added', 0)}，"
            f"修改 {summary.get('changed', 0)}，删除 {summary.get('removed', 0)}）。"
            f"\n方案：{json.dumps(plan.spec, ensure_ascii=False)}"
            f"\n沙箱产物：{result.out_dir}"
        )
        return self._finish(
            feedback_id,
            FeedbackStatus.fixed,
            reply,
            iterations,
            result.proposal,
            gate,
        )

    def _audit_feedback(
        self, feedback_id: str, finding: Finding, iterations: int
    ) -> RepairOutcome:
        """Re-review a table/document/clause feedback with the audit pass."""

        item = self.store.get_feedback(feedback_id)
        if finding.target.table_id and item is not None:
            fixed = self._apply_table_fix(
                feedback_id, finding, item.description, iterations
            )
            if fixed is not None:
                return fixed

        job_dir = locate_job_dir(self.settings, finding.job_id)
        if job_dir is None:
            return self._finish(
                feedback_id,
                FeedbackStatus.needs_more_info,
                "找不到任务产物，无法重新审查。",
                iterations,
            )
        out_dir = self.settings.jobs_root / feedback_id / "audit"
        try:
            findings = self.audit_job(job_dir, out_dir)
        except Exception as exc:  # noqa: BLE001 - audit failure is reported
            return self._finish(
                feedback_id,
                FeedbackStatus.needs_more_info,
                f"重新审查失败：{str(exc)[:200]}",
                iterations,
            )
        scoped = findings
        if finding.target.table_id:
            scoped = [
                item
                for item in findings
                if (item.target.table_id or "") == finding.target.table_id
            ]
        # Audit findings are deduped by target/verdict; reuse the stored row so
        # a repeat audit can still repair the existing issue.
        resolved: list[Finding] = []
        for item in scoped:
            existing = self.store.get_finding(item.finding_id) or self.store.find_finding(
                item.doc_id, item.target, item.verdict
            )
            resolved.append(existing or item)
        scoped = resolved
        if not scoped:
            return self._finish(
                feedback_id,
                FeedbackStatus.needs_more_info,
                f"已重新审查{_scope_label(finding)}，未发现新的可自动判定问题。"
                "如仍认为有问题，请指出具体字段或期望值。",
                iterations,
            )
        repaired: list[Finding] = []
        remaining: list[Finding] = []
        # Try one concrete repair; reporting only would leave "processing" stuck.
        for item in scoped[:1]:
            try:
                outcome = self.process_finding(item.finding_id)
            except Exception:  # noqa: BLE001 - report the rest
                remaining.append(item)
                continue
            if outcome.get("repaired"):
                repaired.append(item)
            else:
                remaining.append(item)
        remaining.extend(scoped[1:])
        lines = [f"已重新审查{_scope_label(finding)}，发现 {len(scoped)} 个问题："]
        for item in scoped[:5]:
            label = (
                item.target.property
                or item.target.record_id
                or item.target.table_id
                or "问题"
            )
            detail = item.observed or item.expected
            suffix = f"（当前 {detail}）" if detail else ""
            lines.append(
                f"- {label}：{item.verdict.value}"
                f"（{item.rule_code or 'audit'}）{suffix}"
            )
        if repaired:
            lines.insert(0, f"其中 {len(repaired)} 个已自动修复。")
        if repaired and not remaining:
            status = FeedbackStatus.fixed
        else:
            status = FeedbackStatus.needs_more_info
            lines.append("其余问题需要确认正确比较符、单位或期望值后才能自动修复。")
        return self._finish(feedback_id, status, "\n".join(lines), iterations)

    # -- automatic audit findings -------------------------------------
    def process_finding(self, finding_id: str) -> dict[str, Any]:
        finding = self.store.get_finding(finding_id)
        if finding is None:
            raise KeyError(finding_id)
        if finding.status != FindingStatus.open:
            return {"finding_id": finding_id, "status": finding.status.value, "repaired": False}
        job_dir = locate_job_dir(self.settings, finding.job_id)
        result = load_result(job_dir) if job_dir else None
        if job_dir is None or result is None:
            return {"finding_id": finding_id, "status": "unverifiable", "repaired": False}
        base = self.settings.jobs_root / "_audit" / finding_id
        l1 = self._attempt_l1(finding, job_dir, base / "l1", 1, plan_only=False)
        if l1["ok"]:
            self.store.update_finding_status(finding_id, FindingStatus.fixed.value)
            return {
                "finding_id": finding_id,
                "status": "fixed",
                "repaired": True,
                "level": "L1",
                "decision": l1["gate"].decision.value,
            }
        l2 = self._attempt_l2(finding, job_dir, result, base, 1, plan_only=False)
        if l2["ok"]:
            self.store.update_finding_status(finding_id, FindingStatus.fixed.value)
            return {
                "finding_id": finding_id,
                "status": "fixed",
                "repaired": True,
                "level": "L2",
                "decision": l2["gate"].decision.value,
            }
        self.store.update_finding_status(finding_id, FindingStatus.rejected.value)
        return {
            "finding_id": finding_id,
            "status": "rejected",
            "repaired": False,
            "detail": [l1["detail"], l2["detail"]],
        }

    def process_open(self, limit: int = 20) -> list[RepairOutcome]:
        outcomes = []
        for item in self.store.list_feedback(status=FeedbackStatus.open.value, limit=limit):
            outcomes.append(self.process_feedback(item.feedback_id))
        return outcomes

    # ------------------------------------------------------------------
    def _attempt_l1(
        self,
        finding: Finding,
        job_dir: Path,
        out_dir: Path,
        iterations: int,
        *,
        plan_only: bool = False,
        target_ok=None,
    ) -> dict[str, Any]:
        proposal_id = new_id("prp")
        try:
            result = self.l1.apply(
                finding,
                job_dir,
                out_dir,
                proposal_id=proposal_id,
                target_ok=target_ok,
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": f"L1 重解析不可用：{str(exc)[:200]}"}
        if not result.ok or result.proposal is None:
            return {"ok": False, "detail": f"L1 重解析失败：{result.error}"}
        proposal = result.proposal
        self.store.add_proposal(proposal)
        gate = self._gate(finding, proposal, result.diff, iterations)
        if gate.decision == GateDecision.accept and not plan_only:
            self.store.update_proposal_status(proposal.proposal_id, ProposalStatus.applied.value)
            return {
                "ok": True,
                "detail": "L1 修复通过门禁",
                "proposal": proposal,
                "gate": gate,
                "diff": result.diff,
                "out_dir": result.out_dir,
            }
        if not self._proposal_open(proposal):
            self.store.update_proposal_status(proposal.proposal_id, ProposalStatus.rolled_back.value)
        return {"ok": False, "detail": "L1 未通过门禁：" + _failed_checks(gate)}

    def _attempt_l2(
        self,
        finding: Finding,
        job_dir: Path,
        result: Any,
        base: Path,
        iterations: int,
        *,
        plan_only: bool = False,
    ) -> dict[str, Any]:
        planner, owned = self._planner()
        plan = None
        if planner is not None:
            try:
                plan = planner.plan(finding, _planner_context(result, finding))
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "detail": f"L2 规划失败：{str(exc)[:200]}"}
            finally:
                if owned is not None:
                    owned.close()
        if not plan:
            return {"ok": False, "detail": "L2 无可用的白名单算子"}

        try:
            proposal, candidate = self.l2.propose(
                finding, job_dir, plan["operator"], plan["params"]
            )
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "detail": f"L2 候选生成失败：{str(exc)[:200]}"}
        self.store.add_proposal(proposal)
        self.store.add_candidate(candidate)

        shadow_dir = base / f"shadow_{proposal.proposal_id}"
        try:
            diff = self.l2.shadow(proposal, finding, job_dir, shadow_dir)
        except Exception as exc:  # noqa: BLE001
            self.store.update_proposal_status(proposal.proposal_id, ProposalStatus.rejected.value)
            self.store.update_candidate_status(candidate.candidate_id, "rejected")
            return {"ok": False, "detail": f"L2 shadow 运行失败：{str(exc)[:200]}"}
        gate = self._gate(finding, proposal, diff, iterations)
        if gate.decision == GateDecision.accept and not plan_only:
            self.store.update_proposal_status(proposal.proposal_id, ProposalStatus.verified.value)
            self.store.update_candidate_status(candidate.candidate_id, "shadow")
            return {
                "ok": True,
                "detail": "L2 修复通过门禁",
                "proposal": proposal,
                "gate": gate,
                "diff": diff,
            }
        self.store.update_proposal_status(proposal.proposal_id, ProposalStatus.rolled_back.value)
        self.store.update_candidate_status(candidate.candidate_id, "rejected")
        rollback_overlay(proposal)
        return {"ok": False, "detail": "L2 未通过门禁：" + _failed_checks(gate)}

    def _attempt_l3(
        self,
        finding: Finding,
        result: Any,
        iterations: int,
        *,
        diagnosis: Diagnosis | None = None,
        feedback_id: str = "",
    ) -> dict[str, Any]:
        if not self.settings.code_agent:
            return {"ok": False, "detail": "L3 未启用（SELFHEAL_CODE_AGENT=off）", "patch": None}
        report: dict[str, Any] = {}
        if self.patch_provider is not None:
            diff = self.patch_provider(finding, result)
        else:
            from .codefix import CodeFixAgent

            diff, report = CodeFixAgent(self.settings).propose(
                finding,
                result,
                diagnosis.to_dict() if diagnosis is not None else None,
                feedback_id=feedback_id,
            )
        if not diff:
            return {
                "ok": False,
                "detail": report.get("reason") or "L3 未生成补丁",
                "patch": None,
                "report": report,
            }
        proposal_id = new_id("prp")
        patch = self.l3.propose(finding, proposal_id, diff)
        if patch is None:
            return {
                "ok": False,
                "detail": "L3 提案被策略拒绝",
                "patch": None,
                "report": report,
            }
        self.store.add_code_patch(patch)
        if report.get("applied"):
            self.store.update_proposal_status(
                proposal_id, ProposalStatus.applied.value
            )
        return {
            "ok": True,
            "detail": "L3 已生成补丁提案",
            "patch": patch,
            "report": report,
        }

    def _planner(self) -> tuple[Planner | None, Planner | None]:
        if self.planner is not None:
            return self.planner, None
        if self.settings.model_base_url:
            try:
                planner = ModelPlanner(self.settings)
                return planner, planner
            except ValueError:
                return None, None
        return HeuristicPlanner(), None

    def _gate(
        self, finding: Finding, proposal, diff: dict, iterations: int
    ) -> GateResult:
        gate = evaluate(
            GateContext(
                finding=finding,
                proposal=proposal,
                diff=diff,
                iterations=iterations,
                regression_check=self.regression_check,
            ),
            self.settings,
        )
        self.store.add_gate_result(gate)
        return gate

    def _finish(
        self,
        feedback_id: str,
        status: FeedbackStatus,
        reply: str,
        iterations: int,
        proposal=None,
        gate: GateResult | None = None,
    ) -> RepairOutcome:
        self.store.update_feedback(feedback_id, status=status.value)
        if reply:
            self.feedback.add_message(feedback_id, reply)
        return RepairOutcome(
            feedback_id=feedback_id,
            status=status,
            proposal_id=proposal.proposal_id if proposal else None,
            level=proposal.level if proposal else None,
            decision=gate.decision if gate else None,
            reply=reply,
            iterations=iterations,
        )

    @staticmethod
    def _proposal_open(proposal) -> bool:
        return proposal.status in {
            ProposalStatus.proposed,
            ProposalStatus.sandbox,
            ProposalStatus.verified,
        }


def _planner_context(result: Any, finding: Finding) -> dict[str, Any]:
    table = next(
        (item for item in result.tables if item.table_id == finding.target.table_id),
        None,
    )
    record = next(
        (item for item in result.records if item.record_id == finding.target.record_id),
        None,
    )
    document = result.document
    if document.standard_no:
        document_key = "".join(
            char for char in document.standard_no.upper() if char.isalnum()
        )
    else:
        document_key = document.doc_id
    return {
        "document_key": document_key,
        "header": table.header_paths if table else [],
        "record": {
            "record_id": record.record_id,
            "grade": record.grade,
            "condition": record.condition,
            "properties": {
                name: {"raw": value.raw, "unit": value.unit}
                for name, value in record.properties.items()
            },
        }
        if record
        else {},
    }


def _table_change_count(diff: dict[str, Any], table_id: str) -> int:
    total = 0
    for key in ("added", "removed", "changed"):
        total += sum(
            1
            for item in diff.get(key) or []
            if (item.get("table_id") or "") == table_id
        )
    return total


def _scope_label(finding: Finding) -> str:
    if finding.target.table_id:
        return f"表 {finding.target.table_id}（{finding.target.feature or '相关检验项目'}）"
    if finding.target.feature:
        return finding.target.feature
    return "整篇文档"


def _failed_checks(gate: GateResult) -> str:
    failed = [f"{check.name}({check.detail})" for check in gate.checks if not check.passed]
    return ", ".join(failed) if failed else "未知原因"


def _norm(text: Any) -> str:
    return re.sub(r"\s+", "", str(text or ""))


def _diagnosis_target_present(diagnosis: Diagnosis, result: Any) -> bool:
    target = diagnosis.target
    if target.table_id and not any(
        table.table_id == target.table_id for table in result.tables
    ):
        return False
    if target.record_id and not any(
        record.record_id == target.record_id for record in result.records
    ):
        return False
    return bool(target.table_id or target.record_id or target.feature)


def _diagnosis_label(diagnosis: Diagnosis) -> str:
    return {
        "document_meta": "文档元数据（标准编号/名称）",
        "missing_item": "检验项目缺失",
        "missing_field": "字段缺失",
        "table": "整表解析问题",
        "clause": "条款解析问题",
        "field": "字段值问题",
        "document": "整篇解析问题",
    }.get(diagnosis.scope, "解析问题")


def _evidence_label(entry: dict[str, Any]) -> str:
    parts = []
    if entry.get("page_no"):
        parts.append(f"第{entry['page_no']}页")
    if entry.get("table_id"):
        parts.append(f"表{entry['table_id']}")
    if entry.get("row") is not None:
        parts.append(f"第{int(entry['row']) + 1}行")
    if entry.get("col") is not None:
        parts.append(f"第{int(entry['col']) + 1}列")
    return " ".join(parts) or "原文"


def _feature_present(result: Any, feature: str | None) -> bool:
    needle = _norm(feature)
    if not needle:
        return False
    for item in result.inspection_items:
        if needle in _norm(item.item):
            return True
    for table in result.tables:
        haystack = _norm(
            " ".join([table.caption or ""] + [" ".join(path) for path in table.header_paths])
        )
        if needle in haystack:
            return True
    for record in result.records:
        if needle in _norm(record.grade or record.grade_level):
            return True
        if any(needle in _norm(name) for name in record.properties):
            return True
    return False


def _field_present(result: Any, name: str | None, table_id: str | None) -> bool:
    needle = _norm(name)
    if not needle:
        return False
    for record in result.records:
        if table_id and record.source_table_id != table_id:
            continue
        if any(needle in _norm(key) for key in record.properties):
            return True
    return False


def _document_changed(before: Any, after: Any) -> bool:
    if before.document.model_dump() != after.document.model_dump():
        return True
    if len(before.records) != len(after.records):
        return True
    if len(before.tables) != len(after.tables):
        return True
    if {item.item for item in before.inspection_items} != {
        item.item for item in after.inspection_items
    }:
        return True
    return _table_changed(before, after, None)


def _table_changed(before: Any, after: Any, table_id: str | None) -> bool:
    def snapshot(result: Any) -> dict[tuple, dict[str, str]]:
        rows: dict[tuple, dict[str, str]] = {}
        for record in result.records:
            if table_id and record.source_table_id != table_id:
                continue
            key = (
                record.source_table_id,
                _norm(record.grade or record.grade_level),
                _norm(record.condition),
            )
            rows[key] = {
                name: _norm(value.raw or value.text)
                for name, value in record.properties.items()
            }
        return rows

    return snapshot(before) != snapshot(after)
