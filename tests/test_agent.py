"""End-to-end tests for the intake-to-approval agent."""

from __future__ import annotations

import pytest

from intake_approval.agent import IntakeApprovalAgent
from tests.conftest import clean_case


def test_clean_case_proposes_issues_and_sends_with_both_gates(agent) -> None:
    result = agent.run(clean_case(), approve_packet=True, approve_issue=True)
    assert result.decision == "PROPOSE"
    assert result.packet is not None
    assert result.packet.record_id == "PO-001"  # cheapest confirmed match
    assert result.packet.status == "draft"
    assert result.packet.shared is False
    assert result.packet.issued is False
    assert result.packet.coded_request.category == "it_hardware"
    assert result.packet.coded_request.cost_centre == "CC-410 Design"
    assert result.packet.coded_request.gl_code == "GL-6110"
    assert result.packet.coded_request.supplier_id == "SUP-001"
    assert result.packet.coded_request.supplier_name == "TechSupply Co."
    assert result.packet.coded_request.amount == 1233.0
    assert result.packet.policy.record_id == "PO-001"
    assert result.packet.policy.approval_chain == ["Procurement Lead", "Finance Manager"]
    assert result.draft is not None
    assert result.draft.sent is False
    assert result.draft.to_requester_id == "REQ-01"
    assert result.published is True
    assert result.applied is True
    assert result.sent is True
    assert result.spend_usd == 0.0
    assert result.gates_checked == ["packet", "issue"]
    assert result.provenance == ["PO-001", "agreement-001"]


def test_clean_case_packet_carries_the_supplier_message_draft(agent) -> None:
    result = agent.run(clean_case(), approve_packet=True, approve_issue=True)
    assert result.packet is not None
    assert result.draft is result.packet.supplier_message
    assert result.draft.purpose == "share_packet"
    assert "PO-001" in result.draft.subject
    assert "TechSupply Co." in result.draft.body


def test_clean_case_policy_check_is_recorded_in_flags(agent) -> None:
    result = agent.run(clean_case(), approve_packet=True, approve_issue=True)
    assert result.flags["policy_checked"] == "PO-001"
    assert result.flags["catalog_records"] == ["PO-001", "PO-005"]


def test_plan_is_the_three_allowlisted_tools(agent) -> None:
    assert agent.plan() == ["intake_search", "policy_check", "approval_draft"]


def test_agent_rejects_unknown_mode() -> None:
    with pytest.raises(ValueError, match="unknown mode"):
        IntakeApprovalAgent(mode="oracle")


def test_gates_denied_refuses_and_publishes_nothing(agent) -> None:
    result = agent.run(clean_case(), approve_packet=False, approve_issue=False)
    assert result.decision == "REFUSED"
    assert result.packet is None
    assert result.draft is None
    assert result.published is False
    assert result.applied is False
    assert result.sent is False
    assert result.refusal == "packet gate not approved: no tool ran"
    assert result.gates_checked == ["packet"]


def test_issue_gate_denied_shares_but_does_not_issue(agent) -> None:
    result = agent.run(clean_case(), approve_packet=True, approve_issue=False)
    assert result.decision == "PROPOSE"
    assert result.published is True
    assert result.applied is False
    assert result.sent is False


def test_remediation_holds(agent) -> None:
    data = clean_case()
    data["remediation_needed"] = [
        "PO 001 — TechSupply Co. requires procurement lead sign-off "
        "before issuing — a human must complete this before any PO is issued."
    ]
    result = agent.run(data, approve_packet=True, approve_issue=True)
    assert result.decision == "HOLD"
    assert result.published is False
    assert result.applied is False
    assert result.sent is False


def test_audit_log_records_every_tool_call(agent) -> None:
    agent.run(clean_case(), approve_packet=True, approve_issue=True)
    entries = agent.audit_log()
    tools = [entry["tool"] for entry in entries]
    assert tools == ["intake_search", "policy_check", "approval_draft"]
    assert [entry["seq"] for entry in entries] == [1, 2, 3]
    assert all(entry["case_id"] == "IA-T01" for entry in entries)
    assert entries[0]["detail"].startswith("2 matching record(s)")


def test_audit_log_is_a_copy(agent) -> None:
    agent.run(clean_case(), approve_packet=True, approve_issue=True)
    entries = agent.audit_log()
    entries.clear()
    assert len(agent.audit_log()) == 3


def test_live_agent_refuses_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    agent = IntakeApprovalAgent(mode="live")
    with pytest.raises(RuntimeError, match="no ANTHROPIC_API_KEY"):
        agent.run(clean_case(), approve_packet=True, approve_issue=True)
