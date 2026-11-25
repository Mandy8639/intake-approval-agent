"""Minimal MCP server (stdio JSON-RPC 2.0), no external dependencies.

Exposes the three allowlisted tools over the Model Context Protocol:
tools/list and tools/call. Run: python -m intake_approval.mcp_server
"""

from __future__ import annotations

import json
import sys
from dataclasses import asdict

from intake_approval.tools import (
    ALLOWED_TOOLS,
    approval_draft,
    intake_search,
    policy_check,
    read_case,
)

TOOLS = {
    "intake_search": {
        "description": "Governed request/contract/PO data the requester may see, "
        "lowest cost first.",
        "inputSchema": {
            "type": "object",
            "properties": {"case": {"type": "object"}},
            "required": ["case"],
        },
    },
    "policy_check": {
        "description": "An approval chain, tolerance, contract compliance and "
        "three-way match for the best record. Checks only; it approves "
        "nothing.",
        "inputSchema": {
            "type": "object",
            "properties": {"case": {"type": "object"}},
            "required": ["case"],
        },
    },
    "approval_draft": {
        "description": "Draft an approval packet for one matching record. Never "
        "approves anything or issues anything; the supplier message "
        "travels inside the packet.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "case": {"type": "object"},
                "record_id": {"type": "string"},
            },
            "required": ["case", "record_id"],
        },
    },
}


def _tool_result(payload: object) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, indent=2)}]}


def handle(request: dict) -> dict | None:
    """Handle one JSON-RPC request. Returns None for notifications."""
    method = request.get("method", "")
    request_id = request.get("id")
    params = request.get("params", {}) or {}

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "intake-approval-agent", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": request_id, "result": {}}
    if method.startswith("notifications/"):
        return None
    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "result": {
                "tools": [
                    {"name": name, **spec} for name, spec in TOOLS.items() if name in ALLOWED_TOOLS
                ]
            },
        }
    if method == "tools/call":
        name = params.get("name", "")
        arguments = params.get("arguments", {}) or {}
        try:
            if name == "intake_search":
                case = read_case(arguments["case"])
                matches = intake_search(case)
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": _tool_result([asdict(match) for match in matches]),
                }
            if name == "policy_check":
                case = read_case(arguments["case"])
                check = policy_check(case)
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": _tool_result(asdict(check)),
                }
            if name == "approval_draft":
                case = read_case(arguments["case"])
                packet = approval_draft(case, arguments["record_id"])
                return {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": _tool_result(asdict(packet)),
                }
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": f"unknown tool: {name}"},
            }
        except (KeyError, ValueError) as exc:
            return {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {"code": -32602, "message": str(exc)},
            }
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {"code": -32601, "message": f"unknown method: {method}"},
    }


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
