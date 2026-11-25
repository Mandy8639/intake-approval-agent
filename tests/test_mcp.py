"""Tests for the MCP server (stdio JSON-RPC)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from intake_approval.mcp_server import handle
from tests.conftest import clean_case

ROOT = Path(__file__).resolve().parents[1]


def test_initialize_names_the_server() -> None:
    response = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert response["result"]["serverInfo"]["name"] == "intake-approval-agent"
    assert response["result"]["protocolVersion"] == "2024-11-05"


def test_tools_list_exposes_exactly_the_three_allowlisted_tools() -> None:
    response = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    names = [tool["name"] for tool in response["result"]["tools"]]
    assert names == ["intake_search", "policy_check", "approval_draft"]


def test_tools_call_intake_search() -> None:
    response = handle(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "intake_search", "arguments": {"case": clean_case()}},
        }
    )
    payload = json.loads(response["result"]["content"][0]["text"])
    assert [match["record"]["id"] for match in payload] == ["PO-001", "PO-005"]


def test_tools_call_policy_check() -> None:
    response = handle(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "policy_check", "arguments": {"case": clean_case()}},
        }
    )
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["record_id"] == "PO-001"
    assert payload["approval_chain"] == ["Procurement Lead", "Finance Manager"]
    assert payload["three_way"]["applicable"] is False


def test_tools_call_approval_draft() -> None:
    response = handle(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "approval_draft",
                "arguments": {"case": clean_case(), "record_id": "PO-001"},
            },
        }
    )
    payload = json.loads(response["result"]["content"][0]["text"])
    assert payload["record_id"] == "PO-001"
    assert payload["status"] == "draft"
    assert payload["supplier_message"]["purpose"] == "share_packet"


def test_tools_call_unknown_tool_errors() -> None:
    response = handle(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "issue_po", "arguments": {"case": clean_case()}},
        }
    )
    assert response["error"]["code"] == -32602
    assert "unknown tool: issue_po" in response["error"]["message"]


def test_tools_call_bad_case_errors() -> None:
    bad = clean_case()
    del bad["request_text"]
    response = handle(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "intake_search", "arguments": {"case": bad}},
        }
    )
    assert response["error"]["code"] == -32602
    assert "missing required field" in response["error"]["message"]


def test_unknown_method_errors() -> None:
    response = handle({"jsonrpc": "2.0", "id": 8, "method": "resources/list", "params": {}})
    assert response["error"]["code"] == -32601


def test_notifications_return_none() -> None:
    assert handle({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}) is None


def test_stdio_smoke_initialize_and_list() -> None:
    """The server speaks JSON-RPC over stdio, end to end."""
    requests = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}),
        ]
    )
    proc = subprocess.run(
        [sys.executable, "-m", "intake_approval.mcp_server"],
        input=requests,
        capture_output=True,
        text=True,
        cwd=ROOT,
        timeout=30,
    )
    assert proc.returncode == 0
    lines = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    assert lines[0]["result"]["serverInfo"]["name"] == "intake-approval-agent"
    assert [t["name"] for t in lines[1]["result"]["tools"]] == [
        "intake_search",
        "policy_check",
        "approval_draft",
    ]
