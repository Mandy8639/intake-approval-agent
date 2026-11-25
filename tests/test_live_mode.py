"""Tests for live-mode refusals. No real API call is ever made."""

from __future__ import annotations

import json
from datetime import date

import pytest

from intake_approval.reasoner import (
    DAILY_CAP_USD,
    DEFAULT_MODEL,
    PRICED_MODELS,
    LiveReasoner,
)
from intake_approval.tools import intake_search
from intake_approval.packet import case_from_dict
from tests.conftest import clean_case


def _live_case():
    case = case_from_dict(clean_case())
    return case, intake_search(case)


def test_live_refuses_without_api_key(monkeypatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    case, matches = _live_case()
    reasoner = LiveReasoner()
    with pytest.raises(RuntimeError, match="no ANTHROPIC_API_KEY set"):
        reasoner.decide(case, matches)


def test_live_refuses_unknown_model(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    case, matches = _live_case()
    reasoner = LiveReasoner(model="claude-opus-4-5", spend_path=str(tmp_path / "spend.json"))
    with pytest.raises(RuntimeError, match="not in the priced-model table"):
        reasoner.decide(case, matches)


def test_live_refuses_when_daily_cap_reached(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    spend_path = tmp_path / "spend.json"
    spend_path.write_text(
        json.dumps({"date": date.today().isoformat(), "spent_usd": DAILY_CAP_USD}),
        encoding="utf-8",
    )
    case, matches = _live_case()
    reasoner = LiveReasoner(spend_path=str(spend_path))
    with pytest.raises(RuntimeError, match="daily cap of \\$1.00 reached"):
        reasoner.decide(case, matches)


def test_live_refuses_when_anthropic_package_missing(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setitem(__import__("sys").modules, "anthropic", None)
    case, matches = _live_case()
    reasoner = LiveReasoner(spend_path=str(tmp_path / "spend.json"))
    with pytest.raises(RuntimeError, match="anthropic package not installed"):
        reasoner.decide(case, matches)


def test_priced_model_table_is_haiku_only() -> None:
    assert DEFAULT_MODEL == "claude-haiku-4-5"
    assert list(PRICED_MODELS) == ["claude-haiku-4-5"]
    assert PRICED_MODELS["claude-haiku-4-5"] == {
        "input_usd_per_mtok": 1.00,
        "output_usd_per_mtok": 5.00,
    }
    assert DAILY_CAP_USD == 1.00


def test_spend_tracker_ignores_yesterday_and_bad_files(tmp_path) -> None:
    from intake_approval.reasoner import SpendTracker

    tracker = SpendTracker(str(tmp_path / "missing.json"))
    assert tracker.today_spent() == 0.0
    stale = tmp_path / "stale.json"
    stale.write_text(json.dumps({"date": "2020-01-01", "spent_usd": 99.0}), encoding="utf-8")
    assert SpendTracker(str(stale)).today_spent() == 0.0
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    assert SpendTracker(str(bad)).today_spent() == 0.0
