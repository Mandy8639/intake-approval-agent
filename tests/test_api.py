"""Tests for the FastAPI backend (queue, intake, gate 2, audit)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from intake_approval.api import app

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "agent": "intake-approval-agent"}


def test_list_cases_is_the_seeded_48() -> None:
    response = client.get("/api/cases")
    assert response.status_code == 200
    cases = response.json()
    assert len(cases) == 48
    assert cases[0]["case_id"] == "IA-001"
    assert cases[0]["decision"] == "PROPOSE"
    # Seeded with gate 1 approved and gate 2 denied: queued, never issued.
    assert cases[0]["published"] is True
    assert cases[0]["applied"] is False
    assert cases[0]["sent"] is False


def test_get_case_detail() -> None:
    response = client.get("/api/cases/IA-001")
    assert response.status_code == 200
    case = response.json()
    assert case["case_id"] == "IA-001"
    assert case["decision"] == "PROPOSE"
    assert case["packet"] is not None
    assert case["packet"]["record_id"] == "PO-025"  # cheapest open it_hardware PO
    assert case["records"]


def test_get_case_unknown_is_404() -> None:
    response = client.get("/api/cases/IA-999")
    assert response.status_code == 404


def test_intake_flow_then_issue() -> None:
    response = client.post(
        "/api/intake",
        json={
            "request_text": "Order 12 laptops for the design team.",
            "requester_id": "REQ-03",
            "category": "it_hardware",
            "approval_limit": 10000,
        },
    )
    assert response.status_code == 201
    case = response.json()
    assert case["case_id"] == "UI-001"
    assert case["decision"] == "PROPOSE"
    assert case["packet"] is not None
    assert case["packet"]["record_id"] == "PO-025"  # cheapest open it_hardware PO
    assert case["published"] is True
    assert case["applied"] is False
    assert case["sent"] is False

    fetched = client.get("/api/cases/UI-001")
    assert fetched.status_code == 200
    assert fetched.json()["decision"] == "PROPOSE"

    issued = client.post("/api/cases/UI-001/issue")
    assert issued.status_code == 200
    assert issued.json()["applied"] is True
    assert issued.json()["sent"] is True
    assert issued.json()["decision"] == "PROPOSE"

    audit = client.get("/api/audit")
    tools = [entry["tool"] for entry in audit.json() if entry["case_id"] == "UI-001"]
    assert tools.count("intake_search") == 2  # intake + re-run at issue
    assert tools.count("policy_check") == 2
    assert tools.count("approval_draft") == 2


def test_intake_validation() -> None:
    base = {
        "request_text": "Order 12 laptops for the design team.",
        "requester_id": "REQ-03",
        "category": "it_hardware",
        "approval_limit": 10000,
    }
    assert client.post("/api/intake", json={**base, "request_text": "  "}).status_code == 422
    assert client.post("/api/intake", json={**base, "requester_id": "REQ-99"}).status_code == 422
    assert client.post("/api/intake", json={**base, "category": "travel"}).status_code == 422
    assert client.post("/api/intake", json={**base, "approval_limit": 0}).status_code == 422


def test_issue_hold_case_conflicts() -> None:
    # IA-013 is a misrouted case: HOLD, so gate 2 must refuse it.
    response = client.post("/api/cases/IA-013/issue")
    assert response.status_code == 409


def test_issue_unknown_case_is_404() -> None:
    response = client.post("/api/cases/IA-999/issue")
    assert response.status_code == 404


def test_audit_contains_seed_entries() -> None:
    audit = client.get("/api/audit")
    assert audit.status_code == 200
    entries = audit.json()
    assert len(entries) > 100  # 48 seeded cases, 2-3 entries each
    assert all(entry["seq"] == i + 1 for i, entry in enumerate(entries))
    assert {"intake_search", "policy_check", "approval_draft", "decision"} <= {
        entry["tool"] for entry in entries
    }
