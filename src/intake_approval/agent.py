"""The intake-to-approval agent: two human gates around three allowlisted tools.

Gate 1 (G1): the approval packet is issued only because a human
confirmed it. Gate 2 (G2): a PO is issued and the supplier message is
sent only with a second explicit confirmation.

``published`` means the packet was confirmed and placed in the approval
queue; ``applied`` means a PO was issued; ``sent`` means the supplier
message was sent. All three stay False unless the matching gate was
approved for this run.

Every tool call is written to the agent's audit log (``self.audit``), so
the API's audit view shows the real trail of every run.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from intake_approval import guardrail
from intake_approval.reasoner import LiveReasoner, StubReasoner
from intake_approval.tools import (
    ALLOWED_TOOLS,
    ApprovalPacket,
    Draft,
    approval_draft,
    intake_search,
    policy_check,
    read_case,
)


@dataclass(frozen=True)
class AgentResult:
    """Everything one agent run produces (or refuses to produce)."""

    case_id: str
    decision: str  # PROPOSE | HOLD | PAUSE | BLOCK | REFUSED
    packet: ApprovalPacket | None = None
    draft: Draft | None = None
    flags: dict = field(default_factory=dict)
    published: bool = False
    applied: bool = False
    sent: bool = False
    provenance: list[str] = field(default_factory=list)
    spend_usd: float = 0.0
    gates_checked: list[str] = field(default_factory=list)
    refusal: str = ""


class IntakeApprovalAgent:
    """Bounded intake-to-approval agent."""

    def __init__(self, mode: str = "stub", live_model: str | None = None) -> None:
        if mode not in ("stub", "live"):
            raise ValueError(f"unknown mode: {mode!r}")
        self.mode = mode
        self._live = LiveReasoner(model=live_model) if mode == "live" else None
        self.audit: list[dict] = []

    def _log(self, case_id: str, tool: str, detail: str, decision: str = "") -> None:
        self.audit.append(
            {
                "seq": len(self.audit) + 1,
                "case_id": case_id,
                "tool": tool,
                "detail": detail,
                "decision": decision,
            }
        )

    def audit_log(self) -> list[dict]:
        """A copy of the audit trail: every tool call, in order."""
        return [dict(entry) for entry in self.audit]

    def plan(self) -> list[str]:
        """The tool plan, fixed and allowlisted. Gate 1 approves this plan."""
        return list(ALLOWED_TOOLS)

    def run(
        self,
        case_data: dict,
        *,
        approve_packet: bool,
        approve_issue: bool,
    ) -> AgentResult:
        case = read_case(case_data)
        if not approve_packet:
            self._log(case.id, "gate", "packet gate not approved: no tool ran", "REFUSED")
            return AgentResult(
                case_id=case.id,
                decision="REFUSED",
                refusal="packet gate not approved: no tool ran",
                gates_checked=["packet"],
            )
        matches = intake_search(case)
        self._log(
            case.id,
            "intake_search",
            f"{len(matches)} matching record(s): "
            f"{', '.join(m.record.id for m in matches) or 'none'}",
        )
        check = policy_check(case) if matches else None
        if check is not None:
            self._log(
                case.id,
                "policy_check",
                f"{check.record_id}: chain {' -> '.join(check.approval_chain)}; "
                f"three-way {check.three_way}",
            )
        injected = guardrail.scan_injection(case.notes)
        fabricated = guardrail.scan_fabrication(case.claims)
        missing = guardrail.missing_evidence(case)
        conflicts = guardrail.scan_record_conflicts(case)
        violations = guardrail.policy_violations(case)
        misrouted = guardrail.cross_requester_records(case)
        duplicates = [r.id for r in case.records if r.duplicate_of is not None]
        flags = {
            "injection": [note.text for note in injected],
            "fabrication": [claim.text for claim in fabricated],
            "missing_evidence": missing,
            "record_conflicts": conflicts,
            "policy_violations": violations,
            "misrouted": misrouted,
            "duplicates": duplicates,
            "catalog_records": [match.record.id for match in matches],
            "policy_checked": check.record_id if check is not None else None,
        }
        if self.mode == "live":
            assert self._live is not None
            decision, cost = self._live.decide(case, matches)
            spend = cost
        else:
            decision = StubReasoner().decide(
                case,
                matches,
                injection=bool(injected),
                fabrication=bool(fabricated),
                missing=bool(missing),
                conflicts=bool(conflicts),
                violations=bool(violations),
                remediation=bool(case.remediation_needed),
            )
            spend = 0.0
        packet = None
        draft = None
        published = False
        applied = False
        sent = False
        if decision == "PROPOSE" and matches:
            # Gate 1 (G1): the approval packet is issued only because a
            # human confirmed it. Gate 2 (G2): the PO is issued and the
            # supplier message sent only with the second explicit
            # confirmation.
            best = matches[0].record
            packet = approval_draft(case, best.id)
            draft = packet.supplier_message
            self._log(case.id, "approval_draft", f"packet drafted for {best.id}", decision)
            published = True
            applied = bool(approve_issue)
            sent = bool(approve_issue)
        else:
            self._log(case.id, "decision", f"no packet drafted: {decision}", decision)
        return AgentResult(
            case_id=case.id,
            decision=decision,
            packet=packet,
            draft=draft,
            flags=flags,
            published=published,
            applied=applied,
            sent=sent,
            provenance=guardrail.cited_sources(case),
            spend_usd=spend,
            gates_checked=["packet", "issue"],
        )
