"""Tests for the stub (rule-based) reasoner."""

from __future__ import annotations

from intake_approval.packet import case_from_dict
from intake_approval.reasoner import StubReasoner
from intake_approval.tools import intake_search
from tests.conftest import clean_case


def _decide(case_data: dict, **flags: bool) -> str:
    case = case_from_dict(case_data)
    matches = intake_search(case)
    return StubReasoner().decide(
        case,
        matches,
        injection=flags.get("injection", False),
        fabrication=flags.get("fabrication", False),
        missing=flags.get("missing", False),
        conflicts=flags.get("conflicts", False),
        violations=flags.get("violations", False),
        remediation=flags.get("remediation", False),
    )


def test_stub_proposes_clean_case() -> None:
    assert _decide(clean_case()) == "PROPOSE"


def test_stub_blocks_injection_first() -> None:
    assert _decide(clean_case(), injection=True) == "BLOCK"
    # Injection outranks every other signal.
    assert _decide(clean_case(), injection=True, conflicts=True, missing=True) == "BLOCK"


def test_stub_pauses_on_conflicts_and_violations() -> None:
    assert _decide(clean_case(), conflicts=True) == "PAUSE"
    assert _decide(clean_case(), violations=True) == "PAUSE"


def test_stub_holds_on_missing_remediation_fabrication() -> None:
    assert _decide(clean_case(), missing=True) == "HOLD"
    assert _decide(clean_case(), remediation=True) == "HOLD"
    assert _decide(clean_case(), fabrication=True) == "HOLD"


def test_stub_holds_when_nothing_matches() -> None:
    data = clean_case()
    data["records"] = []
    assert _decide(data) == "HOLD"


def test_stub_decision_is_deterministic() -> None:
    case = clean_case()
    assert _decide(case) == _decide(case) == "PROPOSE"
