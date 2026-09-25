"""A degraded MCP gateway must trigger a retry, never a silently empty conclusion."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from student_agent.contracts import Contracts
from student_agent.domain import rules
from student_agent.mcp_gateway import TransientGatewayError
from student_agent.trace import TraceWriter
from student_agent.workflow import IncompleteEvidenceError, _assess_claims, solve_case

ROOT = Path(__file__).resolve().parents[1]
CASE: dict[str, Any] = {
    "case_id": "L3A_CASE_001",
    "opened_at": "2018-01-01T09:00:00-03:00",
    "policy_version": "EC_POLICY_V1",
    "customer_request": {
        "claimed_order_id": "e2a03ccf5ea816036608b2d8c3ab8e60",
        "claims": [
            {"claim_id": "claim-001-a", "topic": "unsupported_claim"},
            {"claim_id": "claim-001-b", "topic": "requested_full_refund"},
        ],
    },
}


class ToolErrorGateway:
    """Every tool reports a tool-level error, as the gateway does when degraded."""

    def __init__(self) -> None:
        self.failed_tools: list[str] = []

    async def call(self, tool_name: str, *, case_id: str, **arguments: str) -> dict[str, Any]:
        self.failed_tools.append(tool_name)
        raise RuntimeError(f"MCP tool {tool_name} failed: Error executing tool")


class DroppedStreamGateway:
    failed_tools: list[str] = []

    async def call(self, tool_name: str, *, case_id: str, **arguments: str) -> dict[str, Any]:
        raise TransientGatewayError(f"{tool_name}: ReadError")


def trace(tmp_path: Path) -> TraceWriter:
    return TraceWriter(tmp_path / "trace.jsonl", Contracts(ROOT / "contracts" / "schemas"))


def test_strict_mode_refuses_to_conclude_without_core_evidence(tmp_path: Path) -> None:
    with pytest.raises(IncompleteEvidenceError):
        asyncio.run(solve_case(CASE, ToolErrorGateway(), trace(tmp_path), strict=True))


def test_final_non_strict_attempt_still_produces_an_output(tmp_path: Path) -> None:
    output = asyncio.run(solve_case(CASE, ToolErrorGateway(), trace(tmp_path), strict=False))
    assert output["assessment"]["primary_issue"] == "insufficient_evidence"


def test_transport_failure_is_not_swallowed_by_agents(tmp_path: Path) -> None:
    with pytest.raises(TransientGatewayError):
        asyncio.run(solve_case(CASE, DroppedStreamGateway(), trace(tmp_path), strict=True))


def test_unsupported_claim_topic_gets_unsupported_verdict() -> None:
    decision = rules.Decision(primary_issue="unsupported_claim", case_status="no_action")
    verdicts = [c["verdict"] for c in _assess_claims(CASE, decision, [], 0.9)]
    assert verdicts == ["unsupported", "unsupported"]
