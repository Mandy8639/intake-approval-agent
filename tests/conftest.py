"""Shared fixtures for the intake-approval tests."""

from __future__ import annotations

import sys
from pathlib import Path

# The eval package (eval/build_golden.py, eval/run_eval.py) lives at the
# repo root, not under src/; make it importable for the eval tests.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from intake_approval.agent import IntakeApprovalAgent
from intake_approval.inventory import BY_ID


def record_dict(record_id: str) -> dict:
    record = dict(BY_ID[record_id])
    if record.get("schema") is not None:
        record["schema"] = [dict(f) for f in record["schema"]]
    return record


def clean_case() -> dict:
    """A clean it_hardware case: PO-001 and PO-005 both satisfy it."""
    return {
        "id": "IA-T01",
        "category": "clean",
        "spend_category": "it_hardware",
        "requester_id": "REQ-01",
        "requester_name": "Dana Ortiz",
        "request_text": "Order 12 laptops for the design team.",
        "approval_limit": 10000,
        "records": [record_dict("PO-001"), record_dict("PO-005")],
        "notes": [
            {
                "text": "Record PO-001: PO 001 — TechSupply Co. Amount $1233.0, status open.",
                "source": "PO-001",
                "asserts": {"amount": 1233.0, "status": "open"},
            },
            {
                "text": "The corpus lists PO-001 under IT.",
                "source": "PO-001",
                "asserts": {"owner": "IT"},
            },
        ],
        "claims": [
            {
                "text": "Cascade Manufacturing Group has an active procurement "
                "agreement covering this request.",
                "source": "agreement-001",
            }
        ],
        "required_evidence": ["PO-001:schema", "PO-001:amount"],
        "remediation_needed": [],
        "required_policies": ["approval_threshold"],
    }


@pytest.fixture
def agent() -> IntakeApprovalAgent:
    return IntakeApprovalAgent(mode="stub")
