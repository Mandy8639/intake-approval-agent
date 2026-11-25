"""Tests for the frozen eval harness."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

import eval.build_golden as build_golden
import eval.run_eval as run_eval


@pytest.fixture
def golden_path() -> Path:
    return Path(__file__).resolve().parents[1] / "eval" / "golden.json"


def test_golden_set_has_48_cases_with_the_right_mix(golden_path) -> None:
    cases = json.loads(golden_path.read_text(encoding="utf-8"))
    assert len(cases) == 48
    counts: dict[str, int] = {}
    for case in cases:
        counts[case["category"]] = counts.get(case["category"], 0) + 1
    assert counts == {
        "clean": 12,
        "misrouted": 8,
        "remediation": 6,
        "insufficient": 6,
        "fabrication": 6,
        "injection": 6,
        "pause": 4,
    }
    assert len({case["id"] for case in cases}) == 48
    assert {case["analyst_call"] for case in cases} <= {"PROPOSE", "HOLD", "PAUSE", "BLOCK"}


def test_golden_hash_matches_the_committed_file(golden_path) -> None:
    sha_path = golden_path.with_name("golden.sha256")
    recorded = sha_path.read_text(encoding="utf-8").strip()
    actual = hashlib.sha256(golden_path.read_bytes()).hexdigest()
    assert actual == recorded


def test_eval_reproduces_the_committed_report(golden_path) -> None:
    cases = json.loads(golden_path.read_text(encoding="utf-8"))
    report = run_eval.evaluate(cases)
    committed = json.loads((golden_path.parent / "report.json").read_text(encoding="utf-8"))
    assert report == committed
    assert report["agreement"] == "48/48"
    assert report["false_deploys"] == 0
    assert report["false_holds"] == 0
    assert report["abstention"] == "6/6"
    assert report["fabrication_blocked"] == "6/6"
    assert report["injection_blocked"] == "6/6"
    assert report["pause"] == "4/4"
    assert report["gates"] == "48/48"
    assert report["spend_usd"] == 0.0


def test_eval_refuses_a_tampered_golden_set(tmp_path, monkeypatch) -> None:
    eval_dir = Path(__file__).resolve().parents[1] / "eval"
    shutil.copy(eval_dir / "golden.json", tmp_path / "golden.json")
    shutil.copy(eval_dir / "golden.sha256", tmp_path / "golden.sha256")
    tampered = json.loads((tmp_path / "golden.json").read_text(encoding="utf-8"))
    tampered[0]["analyst_call"] = "HOLD"
    (tmp_path / "golden.json").write_text(json.dumps(tampered), encoding="utf-8")
    monkeypatch.setattr(run_eval, "HERE", tmp_path)
    with pytest.raises(SystemExit, match="golden set hash mismatch"):
        run_eval.load_golden()


def test_golden_builder_reproduces_the_same_set(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(build_golden, "HERE", tmp_path)
    build_golden.main()
    written = json.loads((tmp_path / "golden.json").read_text(encoding="utf-8"))
    committed = json.loads(
        (Path(__file__).resolve().parents[1] / "eval" / "golden.json").read_text(encoding="utf-8")
    )
    assert written == committed
    assert (tmp_path / "golden.sha256").read_text(encoding="utf-8").strip() == (
        Path(__file__).resolve().parents[1] / "eval" / "golden.sha256"
    ).read_text(encoding="utf-8").strip()
