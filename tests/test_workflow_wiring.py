"""Kiểm tra khung workflow chạy thông từ đầu tới cuối, không cần mạng.

Test này KHÔNG kiểm tra tính đúng nghiệp vụ (đó là việc của test từng agent).
Nó chỉ bảo đảm: coordinator gọi đủ specialist, trace có đủ lifecycle event mà
scoring policy yêu cầu, và output lọt qua JSON Schema công khai.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from student_agent.contracts import Contracts
from student_agent.trace import TraceWriter
from student_agent.workflow import solve_case

ROOT = Path(__file__).resolve().parents[1]

# Scoring policy yêu cầu 5 event này; case_received và case_finalized do cli.py emit.
WORKFLOW_REQUIRED_EVENTS = {"task_assigned", "handoff", "verification_completed"}

CASE: dict[str, Any] = {
    "case_id": "L3A_CASE_001",
    "opened_at": "2018-01-01T09:00:00-03:00",
    "policy_version": "EC_POLICY_V1",
    "customer_request": {
        "language": "vi",
        "message": "test",
        "claimed_order_id": "e2a03ccf5ea816036608b2d8c3ab8e60",
        "claims": [
            {"claim_id": "claim-001-a", "topic": "canceled_order_paid"},
            {"claim_id": "claim-001-b", "topic": "requested_full_refund"},
        ],
    },
}


class RefusingGateway:
    """Gateway giả: mọi call đều hỏng, mô phỏng trường hợp mất evidence hoàn toàn."""

    async def call(self, tool_name: str, *, case_id: str, **arguments: str) -> dict[str, Any]:
        raise RuntimeError(f"gateway giả từ chối {tool_name}")


def run_workflow(tmp_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    contracts = Contracts(ROOT / "contracts" / "schemas")
    trace_path = tmp_path / "trace.jsonl"
    trace = TraceWriter(trace_path, contracts)
    output = asyncio.run(solve_case(CASE, RefusingGateway(), trace))
    events = [json.loads(line) for line in trace_path.read_text(encoding="utf-8").splitlines()]
    return output, events


def test_output_satisfies_public_schema(tmp_path: Path) -> None:
    output, _ = run_workflow(tmp_path)
    Contracts(ROOT / "contracts" / "schemas").validate_output(output, "smoke")
    assert output["case_id"] == CASE["case_id"]


def test_missing_evidence_never_becomes_a_guess(tmp_path: Path) -> None:
    """Không có evidence thì phải nói không đủ bằng chứng, không được đoán."""
    output, _ = run_workflow(tmp_path)
    assert output["assessment"]["primary_issue"] == "insufficient_evidence"
    assert output["evidence_refs"] == []
    assert output["financial_resolution"]["recommended_refund_brl"] == 0
    assert output["assessment"]["confidence"] <= 0.4


def test_trace_covers_required_lifecycle_events(tmp_path: Path) -> None:
    _, events = run_workflow(tmp_path)
    assert {event["event_type"] for event in events} >= WORKFLOW_REQUIRED_EVENTS


def test_every_specialist_is_dispatched(tmp_path: Path) -> None:
    _, events = run_workflow(tmp_path)
    handed_off = {event["actor"] for event in events if event["event_type"] == "handoff"}
    assert handed_off == {"order-agent", "shipment-agent", "payment-agent", "policy-agent"}
