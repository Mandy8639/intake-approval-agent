"""Deterministic guardrail G1-G5.

Every rule is a pure function over the case, so the eval can reproduce it
exactly. No rule ever invents evidence: when evidence is missing the agent
abstains; when instructions appear inside case notes they are blocked;
when a note contradicts the corpus the run pauses. PII is redacted
before any draft leaves the corpus, and a record another requester alone
may see is never queried or cited (per-requester isolation).

A permission conflict (G5) is when the case itself requires evidence from
a record in its own category that the requester may not see. That is
distinct from a misrouted record (G3): a record from outside the case's
category that landed in the case is flagged and ignored, never a policy
violation.
"""

from __future__ import annotations

import re

from intake_approval.inventory import BY_ID, POLICIES
from intake_approval.packet import Case, CaseNote, Claim

# Three-way match tolerance: a PO and its invoice may differ by this
# fraction of the PO amount before the run pauses (G5).
THREE_WAY_TOLERANCE = 0.02

# G4: substrings that mark an instruction injected into a case note.
# A note containing one of these is treated as an attempt to steer the
# agent, not as corpus evidence.
INJECTION_PATTERNS = (
    "ignore the",
    "ignore all",
    "override",
    "approve anyway",
    "approve it anyway",
    "issue it anyway",
    "send it anyway",
    "pay it anyway",
    "disregard",
    "do not flag",
    "skip the check",
    "skip the three-way",
    "resolve it anyway",
    "close it anyway",
    "mark it resolved",
    "bypass",
    "pretend",
    "confirm without asking",
)

# G3: PII patterns redacted before any draft leaves the corpus.
PII_PATTERNS = (
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "[EMAIL REDACTED]"),
    (
        re.compile(r"\b(?:\+?1[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b"),
        "[PHONE REDACTED]",
    ),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "[SSN REDACTED]"),
)


def redact_pii(text: str) -> str:
    """G3: redact PII from text before it is quoted in any draft."""
    redacted = text
    for pattern, replacement in PII_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def scan_injection(notes: list[CaseNote]) -> list[CaseNote]:
    """G4: return the case notes that carry an injected instruction."""
    hits = []
    for note in notes:
        lowered = note.text.lower()
        if any(pattern in lowered for pattern in INJECTION_PATTERNS):
            hits.append(note)
    return hits


def scan_fabrication(claims: list[Claim]) -> list[Claim]:
    """G3: return the claims with no provenance source. They are dropped."""
    return [claim for claim in claims if not claim.source]


def cited_sources(case: Case) -> list[str]:
    """Provenance the agent is allowed to cite: sourced notes and claims."""
    sources = [note.source for note in case.notes]
    sources += [claim.source for claim in case.claims if claim.source]
    return sorted(set(sources))


def missing_evidence(case: Case) -> list[str]:
    """G3: required evidence items with no supporting record.

    Entries are ``"RID:schema"`` or ``"RID:amount"``. An item is
    missing when the record is not among the case records, or the field
    is unknown (None) on that record.
    """
    missing = []
    by_id = {record.id: record for record in case.records}
    for entry in case.required_evidence:
        parts = entry.split(":")
        record_id, field_name = parts[0], parts[1]
        record = by_id.get(record_id)
        if record is None:
            missing.append(entry)
            continue
        if field_name == "schema" and record.schema is None:
            missing.append(entry)
        elif field_name == "amount" and record.amount is None:
            missing.append(entry)
    return missing


def scan_record_conflicts(case: Case) -> list[dict]:
    """G5: case-note asserts that contradict the corpus.

    Only fields the record actually knows are compared; an assert about
    an unknown field is not a conflict. Returns one dict per contradiction.
    """
    conflicts = []
    by_id = {record.id: record for record in case.records}
    for note in case.notes:
        record = by_id.get(note.source)
        if record is None:
            continue
        for key, asserted in note.asserts.items():
            if key == "amount" and record.amount is not None:
                if asserted != record.amount:
                    conflicts.append(
                        {
                            "record": record.id,
                            "field": key,
                            "asserted": asserted,
                            "corpus": record.amount,
                        }
                    )
            elif key == "status" and asserted != record.status:
                conflicts.append(
                    {
                        "record": record.id,
                        "field": key,
                        "asserted": asserted,
                        "corpus": record.status,
                    }
                )
            elif key == "owner" and asserted != record.owner:
                conflicts.append(
                    {
                        "record": record.id,
                        "field": key,
                        "asserted": asserted,
                        "corpus": record.owner,
                    }
                )
    return conflicts


def cross_requester_records(case: Case) -> list[str]:
    """G3: record ids in the case that another requester alone may see.

    A misrouted record is flagged, never queried or cited: per-requester
    isolation means the agent may only work records its requester may see.
    """
    return [
        record.id
        for record in case.records
        if record.visible_to not in ("shared", case.requester_id)
    ]


def _policy_conflicts(case: Case) -> list[str]:
    """G5: a required policy defined two ways across the case's records.

    The conflict is judged on the records the case actually carries: a
    policy with two distinct definitions among them means the request
    cannot be answered without disambiguation.
    """
    conflicts = []
    by_id = {record.id: record for record in case.records}
    for policy_name in case.required_policies:
        definitions: dict[str, str] = {}
        for policy in POLICIES:
            if policy["name"] != policy_name:
                continue
            if policy["record_id"] not in by_id:
                continue
            definitions.setdefault(policy["document"], policy["definition"])
        if len(set(definitions.values())) > 1:
            documents = sorted(definitions)
            conflicts.append(
                f"policy_conflict: {policy_name} is defined as "
                f"'{definitions[documents[0]]}' in {documents[0]} and "
                f"'{definitions[documents[1]]}' in {documents[1]}"
            )
    return sorted(conflicts)


def _permission_conflicts(case: Case) -> list[str]:
    """G5: required evidence from a record in the case's own category that
    the requester may not see. Records from outside the case's category
    are misrouted records (G3), not permission conflicts."""
    conflicts = []
    seen: set[str] = set()
    for entry in case.required_evidence:
        record_id = entry.split(":")[0]
        if record_id in seen:
            continue
        seen.add(record_id)
        record = BY_ID.get(record_id)
        if record is None:
            continue
        if record["category"] != case.spend_category:
            continue
        if record["visible_to"] not in ("shared", case.requester_id):
            conflicts.append(
                f"permission_conflict: {record_id} is not visible to requester {case.requester_id}"
            )
    return sorted(conflicts)


def _three_way_mismatches(case: Case) -> list[str]:
    """G5: a PO whose linked invoice differs by more than the tolerance.

    Only invoices the case actually carries are compared, and only
    against the PO they link to. A PO with no invoice in the case has no
    three-way match to fail.
    """
    mismatches = []
    for record in case.records:
        if record.kind != "purchase_order" or record.amount is None:
            continue
        if record.visible_to not in ("shared", case.requester_id):
            continue
        if record.category != case.spend_category:
            continue
        for other in case.records:
            if other.kind != "invoice" or other.po_id != record.id:
                continue
            if other.amount is None:
                continue
            diff = abs(other.amount - record.amount)
            if diff > THREE_WAY_TOLERANCE * record.amount:
                mismatches.append(
                    f"three_way_mismatch: {other.id} (${other.amount:,.2f}) "
                    f"differs from {record.id} (${record.amount:,.2f}) by "
                    f"${diff:,.2f} (tolerance {THREE_WAY_TOLERANCE:.0%})"
                )
    return sorted(mismatches)


def _tolerance_breaches(case: Case) -> list[str]:
    """G5: an in-scope PO whose amount exceeds the requester's approval
    limit. Breaches block only when no viable PO exists: a PO is viable
    when every computable constraint passes, so the agent can use a
    viable one instead. Unknown amounts never count as breaches — they
    are missing evidence (G3), not policy."""
    in_scope = [
        record
        for record in case.records
        if record.kind == "purchase_order"
        and record.visible_to in ("shared", case.requester_id)
        and record.category == case.spend_category
        and record.duplicate_of is None
    ]
    if not in_scope:
        return []
    breaches: set[str] = set()
    viable = False
    for record in in_scope:
        if record.amount is None:
            continue
        if record.amount > case.approval_limit:
            breaches.add(
                f"tolerance_breach: {record.id} is ${record.amount:,.2f} "
                f"against a ${case.approval_limit:,.2f} approval limit"
            )
        elif record.schema is not None and record.status == "open":
            viable = True
    if viable:
        return []
    return sorted(breaches)


def policy_violations(case: Case) -> list[str]:
    """G5: policy violations that block any auto-approval.

    Case-level violations (policy and permission conflicts, three-way
    mismatches) always block. Record-level violations (tolerance
    breaches) block only when no viable PO exists.
    """
    violations = _policy_conflicts(case) + _permission_conflicts(case)
    violations += _three_way_mismatches(case) + _tolerance_breaches(case)
    return sorted(violations)
