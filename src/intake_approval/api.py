"""FastAPI backend for the intake-approval agent.

Serves the React/TypeScript frontend (the built bundle in
``frontend/dist``) and a JSON API over the agent:

- ``GET /api/health`` — liveness.
- ``GET /api/cases`` — the approval queue: every case the agent has
  seen (the 48 frozen eval cases, seeded at startup, plus any case
  submitted through the intake form), with its decision and gate state.
- ``GET /api/cases/{case_id}`` — one case, with its packet if any.
- ``POST /api/intake`` — submit a one-sentence purchase request. The
  submit is gate 1: a human confirms the packet may be prepared and
  queued for approvers. Nothing is issued or sent.
- ``POST /api/cases/{case_id}/issue`` — gate 2: a second explicit
  confirmation before a PO is issued and the supplier is messaged.
  Only a PROPOSE case can be issued.
- ``GET /api/audit`` — the real audit trail: every tool call, in order.

Run: ``uvicorn intake_approval.api:app --reload`` (from the repo root,
after ``pip install -e .`` and ``npm run build`` in ``frontend/``).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from intake_approval.agent import AgentResult, IntakeApprovalAgent
from intake_approval.inventory import CATEGORIES, REQUESTER_BY_ID
from intake_approval.tools import fitting_records

ROOT = Path(__file__).resolve().parents[2]
DIST = ROOT / "frontend" / "dist"

app = FastAPI(title="intake-approval-agent")

_AGENT = IntakeApprovalAgent(mode="stub")
_CASES: dict[str, dict] = {}
_INTAKE_COUNTER = 0


class IntakeRequest(BaseModel):
    """A one-sentence purchase request from the intake form."""

    request_text: str
    requester_id: str
    category: str
    approval_limit: float


def _summarise(case: dict, result: AgentResult) -> dict:
    """The JSON view of one case and its agent result."""
    summary: dict = {
        "case_id": case["id"],
        "category": case["category"],
        "spend_category": case["spend_category"],
        "request_text": case["request_text"],
        "requester_id": case["requester_id"],
        "requester_name": case["requester_name"],
        "approval_limit": case["approval_limit"],
        "decision": result.decision,
        "published": result.published,
        "applied": result.applied,
        "sent": result.sent,
        "spend_usd": result.spend_usd,
        "gates_checked": result.gates_checked,
        "refusal": result.refusal,
        "flags": result.flags,
        "provenance": result.provenance,
        "packet": asdict(result.packet) if result.packet is not None else None,
    }
    return summary


def _load_seed() -> None:
    """Seed the queue with the frozen 48-case eval set, drafted only.

    Each case is run with gate 1 approved (the packet may be prepared
    and queued) and gate 2 denied (nothing is issued or sent).
    """
    golden_path = ROOT / "eval" / "golden.json"
    if not golden_path.exists():
        return
    cases = json.loads(golden_path.read_text(encoding="utf-8"))
    for case in cases:
        result = _AGENT.run(case, approve_packet=True, approve_issue=False)
        _CASES[case["id"]] = {"case": case, "result": result}


_load_seed()


@app.get("/api/health")
def health() -> dict:
    return {"status": "ok", "agent": "intake-approval-agent"}


@app.get("/api/cases")
def list_cases() -> list[dict]:
    return [_summarise(entry["case"], entry["result"]) for entry in _CASES.values()]


@app.get("/api/cases/{case_id}")
def get_case(case_id: str) -> dict:
    entry = _CASES.get(case_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown case: {case_id}")
    summary = _summarise(entry["case"], entry["result"])
    summary["records"] = entry["case"]["records"]
    return summary


@app.post("/api/intake", status_code=201)
def submit_intake(payload: IntakeRequest) -> dict:
    """Gate 1: submit a purchase request; the agent drafts the packet.

    The submit is the human confirming the packet may be prepared and
    queued for approvers. Nothing is issued or sent by this endpoint.
    """
    global _INTAKE_COUNTER
    if not payload.request_text.strip():
        raise HTTPException(status_code=422, detail="request_text must not be empty")
    if payload.requester_id not in REQUESTER_BY_ID:
        raise HTTPException(status_code=422, detail=f"unknown requester: {payload.requester_id!r}")
    if payload.category not in CATEGORIES:
        raise HTTPException(status_code=422, detail=f"unknown category: {payload.category!r}")
    if payload.approval_limit <= 0:
        raise HTTPException(status_code=422, detail="approval_limit must be positive")
    _INTAKE_COUNTER += 1
    case_id = f"UI-{_INTAKE_COUNTER:03d}"
    requester = REQUESTER_BY_ID[payload.requester_id]
    records = fitting_records(payload.requester_id, payload.category, payload.approval_limit)[:3]
    case = {
        "id": case_id,
        "category": "intake",
        "spend_category": payload.category,
        "requester_id": payload.requester_id,
        "requester_name": requester["name"],
        "request_text": payload.request_text.strip(),
        "approval_limit": payload.approval_limit,
        "records": records,
        "notes": [],
        "claims": [
            {
                "text": "Cascade Manufacturing Group has an active "
                "procurement agreement covering this request.",
                "source": f"agreement-{case_id}",
            }
        ],
        "required_evidence": [],
        "remediation_needed": [],
        "required_policies": ["approval_threshold"],
    }
    result = _AGENT.run(case, approve_packet=True, approve_issue=False)
    _CASES[case_id] = {"case": case, "result": result}
    return _summarise(case, result)


@app.post("/api/cases/{case_id}/issue")
def issue_case(case_id: str) -> dict:
    """Gate 2: a second explicit confirmation before a PO is issued
    and the supplier is messaged. Only a PROPOSE case can be issued."""
    entry = _CASES.get(case_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"unknown case: {case_id}")
    if entry["result"].decision != "PROPOSE":
        raise HTTPException(
            status_code=409,
            detail=f"case {case_id} is {entry['result'].decision}: "
            "only a PROPOSE case can be issued",
        )
    result = _AGENT.run(entry["case"], approve_packet=True, approve_issue=True)
    entry["result"] = result
    return _summarise(entry["case"], result)


@app.get("/api/audit")
def audit() -> list[dict]:
    return _AGENT.audit_log()


@app.get("/{full_path:path}")
def serve_frontend(full_path: str):
    """Serve the built React bundle (and fall back to index.html for
    SPA routes). The bundle is checked at request time, so the API
    serves it as soon as ``npm run build`` has run — no restart needed.
    """
    if not DIST.exists():
        return {
            "message": "frontend not built — run `npm ci && npm run build` in frontend/",
            "api": "/api/health",
        }
    candidate = DIST / full_path
    if candidate.is_file():
        return FileResponse(candidate)
    index = DIST / "index.html"
    if index.exists():
        return FileResponse(index)
    raise HTTPException(status_code=404, detail=f"not found: {full_path}")
