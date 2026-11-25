"""Tests for the React/TypeScript frontend and its end-to-end flow.

Builds the bundle (``npm ci`` + ``npm run build``), checks the API
serves it, and drives the intake form flow against the live API with
the test client — no browser harness.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from intake_approval.api import app

FRONTEND = Path(__file__).resolve().parents[1] / "frontend"
DIST = FRONTEND / "dist"


@pytest.fixture(scope="module")
def built_frontend() -> Path:
    """Build the bundle once for the module (npm ci if needed)."""
    if not (FRONTEND / "node_modules").exists():
        result = subprocess.run(
            ["npm", "ci"],
            cwd=FRONTEND,
            capture_output=True,
            text=True,
            timeout=300,
        )
        assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run(
        ["npm", "run", "build"],
        cwd=FRONTEND,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (DIST / "index.html").exists()
    return DIST


def test_frontend_builds(built_frontend) -> None:
    index = (built_frontend / "index.html").read_text(encoding="utf-8")
    assert '<div id="root">' in index
    assets = list((built_frontend / "assets").glob("*.js"))
    assert assets, "no JS bundle in dist/assets"


def test_api_serves_the_built_bundle(built_frontend) -> None:
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert '<div id="root">' in response.text
    index = (built_frontend / "index.html").read_text(encoding="utf-8")
    asset = re.search(r"/assets/[^\"']+\.js", index)
    assert asset is not None
    bundle = client.get(asset.group(0))
    assert bundle.status_code == 200
    assert "javascript" in bundle.headers["content-type"]
    assert len(bundle.content) > 10_000


def test_intake_flow_end_to_end_against_the_live_api() -> None:
    """The intake form's flow, as the frontend drives it: submit a
    one-sentence request, read the coded request back from the queue,
    then issue it through gate 2."""
    client = TestClient(app)
    created = client.post(
        "/api/intake",
        json={
            "request_text": "Order 12 laptops for the design team.",
            "requester_id": "REQ-01",
            "category": "it_hardware",
            "approval_limit": 10000,
        },
    )
    assert created.status_code == 201
    case = created.json()
    assert case["decision"] == "PROPOSE"
    packet = case["packet"]
    assert packet is not None
    assert packet["coded_request"]["category"] == "it_hardware"
    assert packet["coded_request"]["cost_centre"] == "CC-410 Design"
    assert packet["coded_request"]["gl_code"] == "GL-6110"
    assert packet["coded_request"]["supplier_name"] == "NetSphere Networks"  # PO-025
    assert packet["supplier_message"]["purpose"] == "share_packet"

    queue = client.get("/api/cases")
    assert queue.status_code == 200
    assert any(c["case_id"] == case["case_id"] for c in queue.json())

    audit = client.get("/api/audit")
    assert audit.status_code == 200
    tools = [e["tool"] for e in audit.json() if e["case_id"] == case["case_id"]]
    assert tools == ["intake_search", "policy_check", "approval_draft"]

    issued = client.post(f"/api/cases/{case['case_id']}/issue")
    assert issued.status_code == 200
    assert issued.json()["applied"] is True
    assert issued.json()["sent"] is True
