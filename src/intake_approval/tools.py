"""The three allowlisted tools. Nothing else may touch a case.

1. intake_search — governed request/contract/PO data the requester may
   see, lowest cost first.
2. policy_check — an approval chain, tolerance, contract compliance and
   three-way match for the best record. It checks only; it approves
   nothing.
3. approval_draft — an approval packet for a procurement lead to
   approve. It approves nothing and issues nothing; the supplier
   message it cites travels inside the draft as its evidence step,
   over governed records only.

The supplier message itself is built by ``supplier_message`` (a helper,
not a tool) and travels inside the approval packet, so the packet is
the only place a message to a supplier can originate.
"""

from __future__ import annotations

from dataclasses import dataclass

from intake_approval import guardrail
from intake_approval.inventory import (
    BY_ID,
    GL_CODE_BY_CATEGORY,
    RECORDS,
)
from intake_approval.packet import Case, Record, case_from_dict, record_from_dict

ALLOWED_TOOLS = (
    "intake_search",
    "policy_check",
    "approval_draft",
)

MESSAGE_PURPOSES = (
    "share_packet",
    "request_info",
    "escalation_notice",
)

MATCH_KINDS = ("purchase_order", "contract")
MATCH_STATUSES = ("open", "active")

# Approval chain by amount: who must confirm before a PO is issued.
APPROVAL_TIERS = (
    (1_000, ["Procurement Lead"]),
    (5_000, ["Procurement Lead", "Finance Manager"]),
    (10_000, ["Procurement Lead", "Finance Manager", "VP Finance"]),
    (float("inf"), ["Procurement Lead", "Finance Manager", "VP Finance", "CFO"]),
)

# Request-text keywords -> cost centre. The coded request is derived
# from the request text and the case category only, never invented.
COST_CENTRE_KEYWORDS = (
    ("design", "CC-410 Design"),
    ("engineering", "CC-220 Engineering"),
    ("sales", "CC-310 Sales"),
    ("finance", "CC-120 Finance"),
    ("marketing", "CC-330 Marketing"),
    ("operations", "CC-510 Operations"),
    ("legal", "CC-130 Legal"),
)


@dataclass(frozen=True)
class RecordMatch:
    """One record that can satisfy the case, with its provenance source."""

    record: Record
    source: str


@dataclass(frozen=True)
class PolicyCheck:
    """A policy check for the case's best record. Checks only: it
    approves nothing and issues nothing."""

    record_id: str
    approval_chain: list[str]
    tolerance: float
    three_way: dict
    contract: dict | None


@dataclass(frozen=True)
class CodedRequest:
    """The one-sentence request parsed into a coded intake request."""

    category: str
    cost_centre: str
    gl_code: str
    supplier_id: str
    supplier_name: str
    amount: float


@dataclass(frozen=True)
class Draft:
    """A drafted message to a supplier. ``sent`` is always False: it sends nothing."""

    to_supplier: str
    to_requester_id: str
    purpose: str
    subject: str
    body: str
    sent: bool = False


@dataclass(frozen=True)
class ApprovalPacket:
    """A drafted approval packet. Status is always 'draft': it approves
    nothing and issues nothing.

    ``shared`` and ``issued`` are always False on the packet itself —
    only human confirmations (gates 1 and 2) may flip them on the agent
    result.
    """

    record_id: str
    requester_id: str
    coded_request: CodedRequest
    policy: PolicyCheck
    steps: list[str]
    supplier_message: Draft
    status: str = "draft"
    shared: bool = False
    issued: bool = False


def intake_search(case: Case) -> list[RecordMatch]:
    """Tool 1: records that can satisfy the case, lowest cost first.

    A record matches only when every fact is known and passes: it is a
    purchase order or a contract, visible to the case's requester
    (per-requester isolation), its category matches, its schema and
    amount are known, and its status is open (PO) or active (contract).
    Unknown facts exclude the record (G3) rather than being guessed.
    """
    matches = []
    for record in case.records:
        if record.kind not in MATCH_KINDS:
            continue
        if record.visible_to not in ("shared", case.requester_id):
            continue
        if record.category != case.spend_category:
            continue
        if record.duplicate_of is not None:
            continue
        if record.schema is None or record.amount is None:
            continue
        if record.status not in MATCH_STATUSES:
            continue
        matches.append(RecordMatch(record=record, source=record.id))
    matches.sort(key=lambda match: (match.record.amount or 0.0, match.record.id))
    return matches


def _approval_chain(amount: float) -> list[str]:
    for ceiling, chain in APPROVAL_TIERS:
        if amount <= ceiling:
            return list(chain)
    return list(APPROVAL_TIERS[-1][1])


def _three_way(case: Case, record: Record) -> dict:
    """Three-way match for one record: PO amount vs its linked invoice.

    Only invoices the case actually carries are compared. A record with
    no invoice in the case has no three-way match to fail.
    """
    po = record
    if record.kind == "contract":
        candidates = [
            r
            for r in case.records
            if r.kind == "purchase_order"
            and r.supplier_id == record.supplier_id
            and r.visible_to in ("shared", case.requester_id)
            and r.category == case.spend_category
        ]
        if not candidates:
            return {"applicable": False, "reason": "no purchase order in the case"}
        po = sorted(candidates, key=lambda r: (r.amount or 0.0, r.id))[0]
    invoices = [r for r in case.records if r.kind == "invoice" and r.po_id == po.id]
    if not invoices:
        return {"applicable": False, "reason": f"no invoice for {po.id} in the case"}
    invoice = sorted(invoices, key=lambda r: r.id)[0]
    if invoice.amount is None or po.amount is None:
        return {
            "applicable": False,
            "reason": f"amount unknown for {po.id} or {invoice.id}",
        }
    diff = abs(invoice.amount - po.amount)
    return {
        "applicable": True,
        "po_id": po.id,
        "invoice_id": invoice.id,
        "po_amount": po.amount,
        "invoice_amount": invoice.amount,
        "difference": round(diff, 2),
        "matched": diff <= guardrail.THREE_WAY_TOLERANCE * po.amount,
    }


def _contract_for(case: Case, record: Record) -> dict | None:
    """The active contract for the record's supplier, if the case carries one."""
    contracts = [
        r for r in case.records if r.kind == "contract" and r.supplier_id == record.supplier_id
    ]
    if not contracts:
        return None
    contract = sorted(contracts, key=lambda r: r.id)[0]
    return {
        "contract_id": contract.id,
        "supplier_id": contract.supplier_id,
        "active": contract.status == "active",
    }


def policy_check(case: Case) -> PolicyCheck:
    """Tool 2: a policy check for the case's best record.

    The check is an approval chain by amount tier, the three-way match
    tolerance, the three-way match itself, and contract compliance. It
    checks only: no packet is approved, no PO is issued, nothing is
    sent. Only a case with a matching governed record can be checked.
    """
    matches = intake_search(case)
    if not matches:
        raise ValueError("no governed record matches this case")
    record = matches[0].record
    assert record.amount is not None
    return PolicyCheck(
        record_id=record.id,
        approval_chain=_approval_chain(record.amount),
        tolerance=guardrail.THREE_WAY_TOLERANCE,
        three_way=_three_way(case, record),
        contract=_contract_for(case, record),
    )


def _cost_centre(request_text: str) -> str:
    lowered = request_text.lower()
    for keyword, centre in COST_CENTRE_KEYWORDS:
        if keyword in lowered:
            return centre
    return "CC-100 General"


def coded_request(case: Case, record: Record) -> CodedRequest:
    """Parse the one-sentence request into a coded intake request.

    Category and GL code come from the case; cost centre from a keyword
    in the request text; supplier and amount from the matched record.
    Nothing is invented: a field with no source is left to the human.
    """
    supplier_id = record.supplier_id or "unknown"
    supplier = BY_ID.get(supplier_id, {})
    return CodedRequest(
        category=case.spend_category,
        cost_centre=_cost_centre(case.request_text),
        gl_code=GL_CODE_BY_CATEGORY[case.spend_category],
        supplier_id=supplier_id,
        supplier_name=supplier.get("name", "unknown supplier"),
        amount=record.amount if record.amount is not None else 0.0,
    )


def supplier_message(case: Case, record: Record, purpose: str) -> Draft:
    """Build a message draft to the supplier. It is never sent.

    The body cites corpus facts only — never a fact the corpus does
    not know — and any PII quoted from the record is redacted before
    the draft leaves the corpus (G3).
    """
    if purpose not in MESSAGE_PURPOSES:
        raise ValueError(f"unknown message purpose: {purpose!r}")
    supplier = BY_ID.get(record.supplier_id or "", {})
    supplier_name = supplier.get("name", "unknown supplier")
    description = guardrail.redact_pii(record.description)
    if purpose == "share_packet":
        subject = f"Approval packet — {record.id} ({record.name})"
        body = (
            f"Hello {supplier_name}, we have prepared an approval packet for "
            f"'{case.request_text}' against {record.id} ({record.name}). "
            f"Corpus note: {description} A procurement lead must confirm "
            f"the packet before anything is issued or sent. "
            f"Approval limit: ${case.approval_limit:,.2f}."
        )
    elif purpose == "request_info":
        subject = f"More information needed — {record.id} ({record.name})"
        body = (
            f"Hello {supplier_name}, we need one more detail to prepare the "
            f"approval packet for {record.id} ({record.name}). Corpus note: "
            f"{description} Could you confirm the delivery date?"
        )
    else:  # escalation_notice
        subject = f"Escalation — {record.id} ({record.name})"
        body = (
            f"Hello {supplier_name}, {record.id} ({record.name}) has been "
            f"escalated to a procurement lead for review. Corpus note: "
            f"{description} We will update you once they have looked at it."
        )
    return Draft(
        to_supplier=supplier_name,
        to_requester_id=case.requester_id,
        purpose=purpose,
        subject=subject,
        body=body,
    )


def approval_draft(case: Case, record_id: str) -> ApprovalPacket:
    """Tool 3: draft an approval packet for one matching record.

    The packet is a draft: it approves nothing and issues nothing. Only
    a record returned by intake_search may be drafted. The supplier
    message travels inside the packet, and the policy check travels
    inside the packet too.
    """
    matches = {match.record.id: match for match in intake_search(case)}
    if record_id not in matches:
        raise ValueError(f"record {record_id!r} is not a confirmed match for this case")
    record = matches[record_id].record
    check = policy_check(case)
    coded = coded_request(case, record)
    steps = [
        f"Answer the request with the governed check over {record.id} ({record.name}): "
        f"amount ${coded.amount:,.2f}, supplier {coded.supplier_name}, "
        f"cost centre {coded.cost_centre}, {coded.gl_code}.",
        f"Approval chain: {' -> '.join(check.approval_chain)}.",
        f"Three-way match: {check.three_way}.",
        f"Confirm the packet with the requester before sharing "
        f"(approval limit ${case.approval_limit:,.2f}).",
    ]
    if record.requires:
        steps.append(f"Pre-issue step (human): {record.requires}")
    steps.append("Procurement lead confirmation required before issuing or sending anything.")
    return ApprovalPacket(
        record_id=record.id,
        requester_id=case.requester_id,
        coded_request=coded,
        policy=check,
        steps=steps,
        supplier_message=supplier_message(case, record, "share_packet"),
    )


def read_case(data: dict) -> Case:
    """Load and validate a case. Raises ValueError if malformed."""
    return case_from_dict(data)


def record_by_id(record_id: str) -> Record:
    """Look a corpus record up by id (for tests and the MCP server)."""
    data = BY_ID.get(record_id)
    if data is None:
        raise ValueError(f"unknown record: {record_id!r}")
    return record_from_dict(data)


def fitting_records(requester_id: str, category: str, approval_limit: float) -> list[dict]:
    """Records that can satisfy a request, with every fact known.

    Shared by the eval builder and the API intake endpoint: a synthetic
    case carrying the whole corpus, run through intake_search.
    """
    from intake_approval.packet import case_from_dict, record_to_dict  # noqa: PLC0415

    case = case_from_dict(
        {
            "id": "IA-FIT",
            "category": "fit",
            "spend_category": category,
            "requester_id": requester_id,
            "requester_name": "fit check",
            "request_text": "fit check",
            "approval_limit": approval_limit,
            "records": [
                dict(
                    r,
                    schema=None if r.get("schema") is None else [dict(f) for f in r["schema"]],
                )
                for r in RECORDS
            ],
        }
    )
    return [record_to_dict(match.record) for match in intake_search(case)]
