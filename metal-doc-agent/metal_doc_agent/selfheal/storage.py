"""Isolated SQLite storage for the self-heal route.

The store is never created implicitly: callers construct ``SelfHealStore`` with
an explicit path, and the standalone service only does so when
``SELFHEAL_ENABLED=1``. Production tables are not touched.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .contracts import (
    AuditRun,
    CandidateRecipe,
    CodePatchProposal,
    FeedbackItem,
    FeedbackMessage,
    Finding,
    GateResult,
    RepairProposal,
    content_hash,
    now_iso,
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS sh_feedback (
    feedback_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    user_id TEXT,
    category TEXT NOT NULL,
    target_json TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    expected_value TEXT,
    source_quote TEXT,
    status TEXT NOT NULL,
    priority TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    iterations INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_sh_feedback_doc ON sh_feedback(doc_id);
CREATE INDEX IF NOT EXISTS idx_sh_feedback_status ON sh_feedback(status);

CREATE TABLE IF NOT EXISTS sh_feedback_message (
    message_id TEXT PRIMARY KEY,
    feedback_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sh_message_feedback ON sh_feedback_message(feedback_id);

CREATE TABLE IF NOT EXISTS sh_finding (
    finding_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    source TEXT NOT NULL,
    verdict TEXT NOT NULL,
    target_json TEXT NOT NULL,
    expected TEXT,
    observed TEXT,
    evidence_json TEXT NOT NULL,
    rule_code TEXT,
    confidence REAL NOT NULL,
    priority TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at TEXT NOT NULL,
    dedupe_key TEXT NOT NULL,
    feedback_id TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sh_finding_dedupe ON sh_finding(doc_id, dedupe_key);
CREATE INDEX IF NOT EXISTS idx_sh_finding_doc ON sh_finding(doc_id);

CREATE TABLE IF NOT EXISTS sh_repair_attempt (
    proposal_id TEXT PRIMARY KEY,
    finding_ids_json TEXT NOT NULL,
    level TEXT NOT NULL,
    operator TEXT NOT NULL,
    params_json TEXT NOT NULL,
    target_signature TEXT,
    status TEXT NOT NULL,
    artifact_dir TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sh_proposal_status ON sh_repair_attempt(status);

CREATE TABLE IF NOT EXISTS sh_gate_result (
    gate_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    checks_json TEXT NOT NULL,
    decision TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sh_gate_proposal ON sh_gate_result(proposal_id);

CREATE TABLE IF NOT EXISTS sh_candidate_recipe (
    candidate_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    signature TEXT NOT NULL,
    operator TEXT NOT NULL,
    params_json TEXT NOT NULL,
    status TEXT NOT NULL,
    overlay_dir TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sh_candidate_signature ON sh_candidate_recipe(signature);

CREATE TABLE IF NOT EXISTS sh_code_patch (
    patch_id TEXT PRIMARY KEY,
    proposal_id TEXT NOT NULL,
    files_json TEXT NOT NULL,
    diff TEXT NOT NULL,
    status TEXT NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sh_audit_run (
    audit_run_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL,
    job_id TEXT NOT NULL,
    model TEXT NOT NULL,
    packet_tables INTEGER NOT NULL,
    packet_records INTEGER NOT NULL,
    findings INTEGER NOT NULL,
    status TEXT NOT NULL,
    detail TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sh_audit_doc ON sh_audit_run(doc_id);
"""


class SelfHealStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(SCHEMA)

    # -- feedback ------------------------------------------------------
    def add_feedback(self, item: FeedbackItem) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sh_feedback (
                    feedback_id, doc_id, job_id, user_id, category, target_json,
                    description, expected_value, source_quote, status, priority,
                    created_at, updated_at, iterations
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,0)
                """,
                (
                    item.feedback_id,
                    item.doc_id,
                    item.job_id,
                    item.user_id,
                    item.category.value,
                    item.target.model_dump_json(),
                    item.description,
                    item.expected_value,
                    item.source_quote,
                    item.status.value,
                    item.priority,
                    item.created_at,
                    item.updated_at,
                ),
            )

    def get_feedback(self, feedback_id: str) -> FeedbackItem | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sh_feedback WHERE feedback_id=?", (feedback_id,)
            ).fetchone()
        return self._row_to_feedback(row) if row else None

    def list_feedback(
        self, doc_id: str | None = None, status: str | None = None, limit: int = 100
    ) -> list[FeedbackItem]:
        clauses = []
        values: list[Any] = []
        if doc_id:
            clauses.append("doc_id=?")
            values.append(doc_id)
        if status:
            clauses.append("status=?")
            values.append(status)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM sh_feedback{where} ORDER BY created_at DESC LIMIT ?",
                (*values, limit),
            ).fetchall()
        return [self._row_to_feedback(row) for row in rows]

    def update_feedback(
        self,
        feedback_id: str,
        *,
        status: str | None = None,
        iterations: int | None = None,
    ) -> None:
        sets = ["updated_at=?"]
        values: list[Any] = [now_iso()]
        if status is not None:
            sets.append("status=?")
            values.append(status)
        if iterations is not None:
            sets.append("iterations=?")
            values.append(iterations)
        values.append(feedback_id)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE sh_feedback SET {', '.join(sets)} WHERE feedback_id=?",
                values,
            )

    @staticmethod
    def _row_to_feedback(row: sqlite3.Row) -> FeedbackItem:
        from .contracts import FeedbackCategory, FeedbackStatus, FeedbackTarget

        return FeedbackItem(
            feedback_id=row["feedback_id"],
            doc_id=row["doc_id"],
            job_id=row["job_id"],
            user_id=row["user_id"],
            category=FeedbackCategory(row["category"]),
            target=FeedbackTarget.model_validate_json(row["target_json"]),
            description=row["description"],
            expected_value=row["expected_value"],
            source_quote=row["source_quote"],
            status=FeedbackStatus(row["status"]),
            priority=row["priority"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def add_message(self, message: FeedbackMessage) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO sh_feedback_message VALUES (?,?,?,?,?)",
                (
                    message.message_id,
                    message.feedback_id,
                    message.role,
                    message.content,
                    message.created_at,
                ),
            )

    def list_messages(self, feedback_id: str) -> list[FeedbackMessage]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sh_feedback_message WHERE feedback_id=? ORDER BY created_at",
                (feedback_id,),
            ).fetchall()
        return [
            FeedbackMessage(
                message_id=row["message_id"],
                feedback_id=row["feedback_id"],
                role=row["role"],
                content=row["content"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def feedback_iterations(self, feedback_id: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT iterations FROM sh_feedback WHERE feedback_id=?", (feedback_id,)
            ).fetchone()
        return int(row["iterations"]) if row else 0

    # -- findings ------------------------------------------------------
    def add_finding(self, finding: Finding, feedback_id: str | None = None) -> bool:
        """Insert a finding; returns False when an equivalent one exists."""
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO sh_finding (
                        finding_id, doc_id, job_id, source, verdict, target_json,
                        expected, observed, evidence_json, rule_code, confidence,
                        priority, status, created_at, dedupe_key, feedback_id
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        finding.finding_id,
                        finding.doc_id,
                        finding.job_id,
                        finding.source.value,
                        finding.verdict.value,
                        finding.target.model_dump_json(),
                        finding.expected,
                        finding.observed,
                        json.dumps(
                            [item.model_dump() for item in finding.evidence],
                            ensure_ascii=False,
                        ),
                        finding.rule_code,
                        finding.confidence,
                        finding.priority,
                        finding.status.value,
                        finding.created_at,
                        content_hash(
                            {
                                "target": finding.target.model_dump(),
                                "verdict": finding.verdict.value,
                                # User feedback must stay per-submission: a
                                # repeated report on the same record still
                                # needs its own finding so it can be processed.
                                **({"feedback": feedback_id} if feedback_id else {}),
                            }
                        ),
                        feedback_id,
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            return False

    def get_finding(self, finding_id: str) -> Finding | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sh_finding WHERE finding_id=?", (finding_id,)
            ).fetchone()
        return self._row_to_finding(row) if row else None

    def find_finding(self, doc_id: str, target: Any, verdict: Any) -> Finding | None:
        """Return an equal finding that was deduped instead of re-inserted."""

        key = content_hash(
            {"target": target.model_dump(), "verdict": verdict.value}
        )
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sh_finding WHERE doc_id=? AND dedupe_key=? "
                "ORDER BY created_at DESC LIMIT 1",
                (doc_id, key),
            ).fetchone()
        return self._row_to_finding(row) if row else None

    def list_findings(
        self, doc_id: str | None = None, status: str | None = None, limit: int = 200
    ) -> list[Finding]:
        clauses = []
        values: list[Any] = []
        if doc_id:
            clauses.append("doc_id=?")
            values.append(doc_id)
        if status:
            clauses.append("status=?")
            values.append(status)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM sh_finding{where} ORDER BY created_at DESC LIMIT ?",
                (*values, limit),
            ).fetchall()
        return [self._row_to_finding(row) for row in rows]

    def update_feedback_target(
        self, feedback_id: str, target: Any, expected: str | None
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE sh_feedback SET target_json=?, expected_value=?, "
                "updated_at=? WHERE feedback_id=?",
                (target.model_dump_json(), expected, now_iso(), feedback_id),
            )

    def update_finding_status(self, finding_id: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE sh_finding SET status=? WHERE finding_id=?", (status, finding_id)
            )

    def list_findings_for_feedback(self, feedback_id: str) -> list[Finding]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM sh_finding WHERE feedback_id=? ORDER BY created_at DESC",
                (feedback_id,),
            ).fetchall()
        return [self._row_to_finding(row) for row in rows]

    @staticmethod
    def _row_to_finding(row: sqlite3.Row) -> Finding:
        from .contracts import (
            EvidenceRef,
            FeedbackTarget,
            FindingSource,
            FindingStatus,
            FindingVerdict,
        )

        evidence = [
            EvidenceRef.model_validate(item)
            for item in json.loads(row["evidence_json"] or "[]")
        ]
        return Finding(
            finding_id=row["finding_id"],
            doc_id=row["doc_id"],
            job_id=row["job_id"],
            source=FindingSource(row["source"]),
            verdict=FindingVerdict(row["verdict"]),
            target=FeedbackTarget.model_validate_json(row["target_json"]),
            expected=row["expected"],
            observed=row["observed"],
            evidence=evidence,
            rule_code=row["rule_code"],
            confidence=row["confidence"],
            priority=row["priority"],
            status=FindingStatus(row["status"]),
            created_at=row["created_at"],
        )

    # -- proposals / gates --------------------------------------------
    def add_proposal(self, proposal: RepairProposal) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO sh_repair_attempt (
                    proposal_id, finding_ids_json, level, operator, params_json,
                    target_signature, status, artifact_dir, created_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                """,
                (
                    proposal.proposal_id,
                    json.dumps(proposal.finding_ids, ensure_ascii=False),
                    proposal.level.value,
                    proposal.operator,
                    json.dumps(proposal.params, ensure_ascii=False),
                    proposal.target_signature,
                    proposal.status.value,
                    proposal.artifact_dir,
                    proposal.created_at,
                ),
            )

    def get_proposal(self, proposal_id: str) -> RepairProposal | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sh_repair_attempt WHERE proposal_id=?", (proposal_id,)
            ).fetchone()
        if not row:
            return None
        from .contracts import ProposalStatus, RepairLevel

        return RepairProposal(
            proposal_id=row["proposal_id"],
            finding_ids=json.loads(row["finding_ids_json"]),
            level=RepairLevel(row["level"]),
            operator=row["operator"],
            params=json.loads(row["params_json"]),
            target_signature=row["target_signature"],
            status=ProposalStatus(row["status"]),
            artifact_dir=row["artifact_dir"],
            created_at=row["created_at"],
        )

    def update_proposal_status(self, proposal_id: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE sh_repair_attempt SET status=? WHERE proposal_id=?",
                (status, proposal_id),
            )

    def add_gate_result(self, gate: GateResult) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO sh_gate_result VALUES (?,?,?,?,?)",
                (
                    gate.gate_id,
                    gate.proposal_id,
                    json.dumps(
                        [item.model_dump() for item in gate.checks], ensure_ascii=False
                    ),
                    gate.decision.value,
                    gate.created_at,
                ),
            )

    def latest_gate(self, proposal_id: str) -> GateResult | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM sh_gate_result WHERE proposal_id=? ORDER BY created_at DESC LIMIT 1",
                (proposal_id,),
            ).fetchone()
        if not row:
            return None
        from .contracts import GateCheck, GateDecision

        return GateResult(
            gate_id=row["gate_id"],
            proposal_id=row["proposal_id"],
            checks=[GateCheck.model_validate(item) for item in json.loads(row["checks_json"])],
            decision=GateDecision(row["decision"]),
            created_at=row["created_at"],
        )

    # -- candidates / patches / audit ---------------------------------
    def add_candidate(self, candidate: CandidateRecipe) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO sh_candidate_recipe VALUES (?,?,?,?,?,?,?,?)",
                (
                    candidate.candidate_id,
                    candidate.proposal_id,
                    candidate.signature,
                    candidate.operator,
                    json.dumps(candidate.params, ensure_ascii=False),
                    candidate.status.value,
                    candidate.overlay_dir,
                    candidate.created_at,
                ),
            )

    def list_candidates(self, signature: str | None = None) -> list[CandidateRecipe]:
        with self._connect() as connection:
            if signature:
                rows = connection.execute(
                    "SELECT * FROM sh_candidate_recipe WHERE signature=? ORDER BY created_at DESC",
                    (signature,),
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT * FROM sh_candidate_recipe ORDER BY created_at DESC"
                ).fetchall()
        from .contracts import CandidateStatus

        return [
            CandidateRecipe(
                candidate_id=row["candidate_id"],
                proposal_id=row["proposal_id"],
                signature=row["signature"],
                operator=row["operator"],
                params=json.loads(row["params_json"]),
                status=CandidateStatus(row["status"]),
                overlay_dir=row["overlay_dir"],
                created_at=row["created_at"],
            )
            for row in rows
        ]

    def update_candidate_status(self, candidate_id: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE sh_candidate_recipe SET status=? WHERE candidate_id=?",
                (status, candidate_id),
            )

    def add_code_patch(self, patch: CodePatchProposal) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO sh_code_patch VALUES (?,?,?,?,?,?,?)",
                (
                    patch.patch_id,
                    patch.proposal_id,
                    json.dumps(patch.files, ensure_ascii=False),
                    patch.diff,
                    patch.status.value,
                    patch.reason,
                    patch.created_at,
                ),
            )

    def add_audit_run(self, run: AuditRun) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO sh_audit_run VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    run.audit_run_id,
                    run.doc_id,
                    run.job_id,
                    run.model,
                    run.packet_tables,
                    run.packet_records,
                    run.findings,
                    run.status,
                    run.detail,
                    run.created_at,
                ),
            )

    def metrics(self) -> dict[str, Any]:
        with self._connect() as connection:
            feedback = {
                row["status"]: row["count"]
                for row in connection.execute(
                    "SELECT status, COUNT(*) AS count FROM sh_feedback GROUP BY status"
                )
            }
            findings = {
                row["status"]: row["count"]
                for row in connection.execute(
                    "SELECT status, COUNT(*) AS count FROM sh_finding GROUP BY status"
                )
            }
            levels = {
                row["level"]: row["count"]
                for row in connection.execute(
                    "SELECT level, COUNT(*) AS count FROM sh_repair_attempt GROUP BY level"
                )
            }
            decisions = {
                row["decision"]: row["count"]
                for row in connection.execute(
                    "SELECT decision, COUNT(*) AS count FROM sh_gate_result GROUP BY decision"
                )
            }
        return {
            "feedback": feedback,
            "findings": findings,
            "repairs_by_level": levels,
            "gate_decisions": decisions,
        }
