"""Intake case: the single input to the agent.

A case is a synthetic purchase request: a one-sentence request parsed
into requester, spend category and approval limit, a shortlist of corpus
records drawn from the governed spend corpus, notes from the requester
or the procurement team, and claims about the case. Every note and claim
carries a provenance source; a claim without a source is unsourced by
construction and the guardrail treats it as fabrication. Every record
carries who may see it: a record visible only to another requester is a
misrouted record, and the agent may never query or cite it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from intake_approval.inventory import CATEGORIES, REQUESTER_BY_ID


@dataclass(frozen=True)
class Field:
    """One field of a corpus record."""

    name: str
    dtype: str
    nullable: bool
    pii: bool = False
    description: str = ""


@dataclass(frozen=True)
class Record:
    """One record in the governed spend corpus, with facts copied from it.

    ``schema`` and ``amount`` are None when that fact is unknown
    (missing evidence, G3). ``requires`` names a human step that must be
    completed before any PO is issued (remediation). ``duplicate_of``
    names the record this one duplicates, if any. ``visible_to`` is
    "shared" or one requester id: a record visible only to another
    requester is never queried or cited for this case (per-requester
    isolation, G3). ``supplier_id`` links a PO, contract or invoice to
    its supplier; ``po_id`` links an invoice to its PO; ``policy_name``
    and ``definition`` carry a policy record's content.
    """

    id: str
    kind: str
    category: str
    name: str
    schema: list[Field] | None
    amount: float | None
    status: str
    owner: str
    visible_to: str
    sensitivity: str
    description: str
    supplier_id: str | None = None
    po_id: str | None = None
    policy_name: str | None = None
    document: str | None = None
    definition: str | None = None
    requires: str | None = None
    duplicate_of: str | None = None


@dataclass(frozen=True)
class Policy:
    """One named policy. The same name may be defined differently in two
    documents (e.g. "approval_threshold" in the procurement policy vs
    the finance policy): a request that needs both definitions is a
    policy conflict (G5)."""

    name: str
    document: str
    record_id: str
    definition: str


@dataclass(frozen=True)
class CaseNote:
    """One note from the requester or the procurement team. ``source`` is
    the record id.

    ``asserts`` holds machine-readable facts the note claims (e.g. an
    amount or a status). The guardrail compares them against the corpus:
    an assert that contradicts the corpus is a conflict (G5).
    """

    text: str
    source: str
    asserts: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Claim:
    """One claim about the case. ``source`` may be None (unsourced)."""

    text: str
    source: str | None


@dataclass(frozen=True)
class Case:
    """An intake case. All fields are required; see tools.read_case.

    ``category`` is the eval category (clean, misrouted, remediation,
    insufficient, fabrication, injection, pause — or "intake" for a case
    submitted through the API). ``spend_category`` is the spend
    category the request is about.
    """

    id: str
    category: str
    spend_category: str
    requester_id: str
    requester_name: str
    request_text: str
    approval_limit: float
    records: list[Record] = field(default_factory=list)
    notes: list[CaseNote] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    required_evidence: list[str] = field(default_factory=list)
    remediation_needed: list[str] = field(default_factory=list)
    required_policies: list[str] = field(default_factory=list)


def field_from_dict(data: dict) -> Field:
    return Field(
        name=data["name"],
        dtype=data["dtype"],
        nullable=data["nullable"],
        pii=data.get("pii", False),
        description=data.get("description", ""),
    )


def record_from_dict(data: dict) -> Record:
    schema = None
    if data.get("schema") is not None:
        schema = [field_from_dict(f) for f in data["schema"]]
    return Record(
        id=data["id"],
        kind=data["kind"],
        category=data["category"],
        name=data["name"],
        schema=schema,
        amount=data.get("amount"),
        status=data["status"],
        owner=data["owner"],
        visible_to=data["visible_to"],
        sensitivity=data["sensitivity"],
        description=data["description"],
        supplier_id=data.get("supplier_id"),
        po_id=data.get("po_id"),
        policy_name=data.get("policy_name"),
        document=data.get("document"),
        definition=data.get("definition"),
        requires=data.get("requires"),
        duplicate_of=data.get("duplicate_of"),
    )


def policy_from_dict(data: dict) -> Policy:
    return Policy(
        name=data["name"],
        document=data["document"],
        record_id=data["record_id"],
        definition=data["definition"],
    )


def case_from_dict(data: dict) -> Case:
    """Build a Case from a plain dict, validating required fields."""
    required = [
        "id",
        "category",
        "spend_category",
        "requester_id",
        "requester_name",
        "request_text",
        "approval_limit",
    ]
    for key in required:
        if key not in data or data[key] in (None, ""):
            raise ValueError(f"case is missing required field: {key}")
    if data["requester_id"] not in REQUESTER_BY_ID:
        raise ValueError(f"unknown requester: {data['requester_id']!r}")
    if data["spend_category"] not in CATEGORIES:
        raise ValueError(f"unknown spend category: {data['spend_category']!r}")
    records = [record_from_dict(r) for r in data.get("records", [])]
    notes = [
        CaseNote(text=n["text"], source=n["source"], asserts=dict(n.get("asserts", {})))
        for n in data.get("notes", [])
    ]
    claims = [Claim(text=c["text"], source=c.get("source")) for c in data.get("claims", [])]
    return Case(
        id=data["id"],
        category=data["category"],
        spend_category=data["spend_category"],
        requester_id=data["requester_id"],
        requester_name=data["requester_name"],
        request_text=data["request_text"],
        approval_limit=float(data["approval_limit"]),
        records=records,
        notes=notes,
        claims=claims,
        required_evidence=list(data.get("required_evidence", [])),
        remediation_needed=list(data.get("remediation_needed", [])),
        required_policies=list(data.get("required_policies", [])),
    )


def field_to_dict(f: Field) -> dict:
    return {
        "name": f.name,
        "dtype": f.dtype,
        "nullable": f.nullable,
        "pii": f.pii,
        "description": f.description,
    }


def record_to_dict(record: Record) -> dict:
    return {
        "id": record.id,
        "kind": record.kind,
        "category": record.category,
        "name": record.name,
        "schema": [field_to_dict(f) for f in record.schema] if record.schema is not None else None,
        "amount": record.amount,
        "status": record.status,
        "owner": record.owner,
        "visible_to": record.visible_to,
        "sensitivity": record.sensitivity,
        "description": record.description,
        "supplier_id": record.supplier_id,
        "po_id": record.po_id,
        "policy_name": record.policy_name,
        "document": record.document,
        "definition": record.definition,
        "requires": record.requires,
        "duplicate_of": record.duplicate_of,
    }


def case_to_dict(case: Case) -> dict:
    """Serialise a Case back to a plain dict."""
    return {
        "id": case.id,
        "category": case.category,
        "spend_category": case.spend_category,
        "requester_id": case.requester_id,
        "requester_name": case.requester_name,
        "request_text": case.request_text,
        "approval_limit": case.approval_limit,
        "records": [record_to_dict(r) for r in case.records],
        "notes": [
            {"text": n.text, "source": n.source, "asserts": dict(n.asserts)} for n in case.notes
        ],
        "claims": [{"text": c.text, "source": c.source} for c in case.claims],
        "required_evidence": list(case.required_evidence),
        "remediation_needed": list(case.remediation_needed),
        "required_policies": list(case.required_policies),
    }
