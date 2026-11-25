"""Tests for the three allowlisted tools."""

from __future__ import annotations

import pytest

from intake_approval import tools
from intake_approval.packet import case_from_dict
from tests.conftest import clean_case, record_dict


def _case_with_one_po(amount: float) -> dict:
    """A clean case whose only record is PO-001 at the given amount."""
    data = clean_case()
    data["records"] = [dict(record_dict("PO-001"), amount=amount)]
    return data


def test_intake_search_returns_confirmed_matches_sorted_by_amount() -> None:
    case = case_from_dict(clean_case())
    matches = tools.intake_search(case)
    assert [(m.record.id, m.source) for m in matches] == [
        ("PO-001", "PO-001"),
        ("PO-005", "PO-005"),
    ]


def test_intake_search_excludes_each_bad_fact_in_isolation() -> None:
    data = clean_case()
    base = record_dict("PO-001")
    data["records"] = [
        base,  # confirmed
        dict(base, visible_to="REQ-02"),  # restricted to another requester
        dict(base, duplicate_of="PO-001"),  # duplicate
        dict(base, amount=None),  # unknown amount
        dict(base, schema=None),  # unknown schema
        dict(base, status="closed"),  # closed
        dict(base, kind="invoice", po_id="PO-001"),  # wrong kind
        dict(base, category="facilities"),  # wrong category
    ]
    case = case_from_dict(data)
    matches = tools.intake_search(case)
    assert [m.record.id for m in matches] == ["PO-001"]


def test_intake_search_excludes_real_corpus_duplicates_and_restricted() -> None:
    data = clean_case()
    data["records"] = [
        record_dict("PO-001"),
        record_dict("PO-031"),  # duplicate of PO-001
        record_dict("PO-037"),  # restricted to REQ-02 (and facilities)
    ]
    case = case_from_dict(data)
    matches = tools.intake_search(case)
    assert [m.record.id for m in matches] == ["PO-001"]


def test_intake_search_empty_when_nothing_matches() -> None:
    data = clean_case()
    data["records"] = [record_dict("PO-037")]
    case = case_from_dict(data)
    assert tools.intake_search(case) == []


def test_policy_check_approval_chain_tiers() -> None:
    for amount, chain in [
        (800.0, ["Procurement Lead"]),
        (3000.0, ["Procurement Lead", "Finance Manager"]),
        (8000.0, ["Procurement Lead", "Finance Manager", "VP Finance"]),
        (15000.0, ["Procurement Lead", "Finance Manager", "VP Finance", "CFO"]),
    ]:
        case = case_from_dict(_case_with_one_po(amount))
        check = tools.policy_check(case)
        assert check.record_id == "PO-001"
        assert check.approval_chain == chain
        assert check.tolerance == 0.02


def test_policy_check_three_way_not_applicable_without_invoice() -> None:
    case = case_from_dict(clean_case())
    check = tools.policy_check(case)
    assert check.three_way == {
        "applicable": False,
        "reason": "no invoice for PO-001 in the case",
    }


def test_policy_check_three_way_matched() -> None:
    data = clean_case()
    invoice = dict(record_dict("INV-002"), po_id="PO-001", amount=1233.0)
    data["records"] = data["records"] + [invoice]
    case = case_from_dict(data)
    check = tools.policy_check(case)
    assert check.three_way == {
        "applicable": True,
        "po_id": "PO-001",
        "invoice_id": "INV-002",
        "po_amount": 1233.0,
        "invoice_amount": 1233.0,
        "difference": 0.0,
        "matched": True,
    }


def test_policy_check_contract_found() -> None:
    data = clean_case()
    data["records"] = data["records"] + [record_dict("CON-013")]
    case = case_from_dict(data)
    check = tools.policy_check(case)
    assert check.contract == {
        "contract_id": "CON-013",
        "supplier_id": "SUP-001",
        "active": True,
    }


def test_policy_check_contract_missing_when_none_in_case() -> None:
    case = case_from_dict(clean_case())
    check = tools.policy_check(case)
    assert check.contract is None


def test_policy_check_raises_without_a_match() -> None:
    data = clean_case()
    data["records"] = [record_dict("PO-037")]
    case = case_from_dict(data)
    with pytest.raises(ValueError, match="no governed record matches"):
        tools.policy_check(case)


def test_approval_draft_codes_the_request() -> None:
    case = case_from_dict(clean_case())
    packet = tools.approval_draft(case, "PO-001")
    assert packet.record_id == "PO-001"
    assert packet.requester_id == "REQ-01"
    assert packet.coded_request.category == "it_hardware"
    assert packet.coded_request.cost_centre == "CC-410 Design"
    assert packet.coded_request.gl_code == "GL-6110"
    assert packet.coded_request.supplier_id == "SUP-001"
    assert packet.coded_request.supplier_name == "TechSupply Co."
    assert packet.coded_request.amount == 1233.0
    assert packet.policy.record_id == "PO-001"
    assert packet.policy.approval_chain == ["Procurement Lead", "Finance Manager"]
    assert packet.status == "draft"
    assert packet.shared is False
    assert packet.issued is False


def test_approval_draft_message_is_inside_the_packet() -> None:
    case = case_from_dict(clean_case())
    packet = tools.approval_draft(case, "PO-001")
    message = packet.supplier_message
    assert message.purpose == "share_packet"
    assert message.to_supplier == "TechSupply Co."
    assert message.to_requester_id == "REQ-01"
    assert "PO-001" in message.subject
    assert "TechSupply Co." in message.body
    assert "procurement lead" in message.body
    assert message.sent is False


def test_approval_draft_redacts_pii_from_corpus_text() -> None:
    data = clean_case()
    po = dict(
        record_dict("PO-001"),
        description="Order from TechSupply Co. — contact "
        "j.smith@cascade-mfg.example or 415-555-0143.",
    )
    data["records"] = [po, record_dict("PO-005")]
    case = case_from_dict(data)
    packet = tools.approval_draft(case, "PO-001")
    body = packet.supplier_message.body
    assert "j.smith@cascade-mfg.example" not in body
    assert "415-555-0143" not in body
    assert "[EMAIL REDACTED]" in body
    assert "[PHONE REDACTED]" in body


def test_approval_draft_raises_for_a_record_that_does_not_match() -> None:
    data = clean_case()
    data["records"] = [record_dict("PO-037")]
    case = case_from_dict(data)
    with pytest.raises(ValueError, match="not a confirmed match"):
        tools.approval_draft(case, "PO-001")


def test_supplier_message_rejects_unknown_purpose() -> None:
    case = case_from_dict(clean_case())
    with pytest.raises(ValueError, match="unknown message purpose"):
        tools.supplier_message(case, tools.record_by_id("PO-001"), "blast")


def test_coded_request_cost_centre_defaults_to_general() -> None:
    data = clean_case()
    data["request_text"] = "Order 12 laptops for the office."
    case = case_from_dict(data)
    coded = tools.coded_request(case, tools.record_by_id("PO-001"))
    assert coded.cost_centre == "CC-100 General"
    assert coded.gl_code == "GL-6110"


def test_read_case_rejects_missing_and_unknown_fields() -> None:
    data = clean_case()
    del data["request_text"]
    with pytest.raises(ValueError, match="missing required field: request_text"):
        tools.read_case(data)
    data = clean_case()
    data["requester_id"] = "REQ-99"
    with pytest.raises(ValueError, match="unknown requester"):
        tools.read_case(data)
    data = clean_case()
    data["spend_category"] = "travel"
    with pytest.raises(ValueError, match="unknown spend category"):
        tools.read_case(data)


def test_record_by_id_and_unknown() -> None:
    record = tools.record_by_id("PO-001")
    assert record.id == "PO-001"
    assert record.supplier_id == "SUP-001"
    with pytest.raises(ValueError, match="unknown record"):
        tools.record_by_id("PO-999")


def test_fitting_records_returns_visible_known_records() -> None:
    records = tools.fitting_records("REQ-01", "it_hardware", 10000)
    assert records
    assert all(r["kind"] in ("purchase_order", "contract") for r in records)
    assert all(r["amount"] is not None for r in records)
    assert all(r["status"] in ("open", "active") for r in records)
    assert all(r["visible_to"] in ("shared", "REQ-01") for r in records)
    assert "PO-037" not in [r["id"] for r in records]
    assert "PO-031" not in [r["id"] for r in records]
    assert [r["id"] for r in records][:3] == ["PO-025", "PO-013", "PO-001"]
