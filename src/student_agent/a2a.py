"""Giao thức A2A: phân công task, giới hạn quyền gọi tool, ghi trace quan sát được.

Mỗi specialist agent nhận một `AgentContext`. Context chỉ cho phép gọi những tool
nằm trong allowlist của actor đó (nguyên tắc least privilege, mô tả ở
ARCHITECTURE.md mục 2) và tự động:

- nhét đúng `case_id` vào mọi call;
- kiểm tra `evidence_ref` trả về đúng định dạng công khai;
- emit `tool_result_consumed` kèm ref ngay khi evidence được tiêu thụ.

Không ghi prompt hay chain-of-thought vào trace — chỉ sự kiện và decision code.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .domain.findings import EvidenceItem, Finding
from .mcp_gateway import EvidenceGateway
from .trace import TraceWriter

EVIDENCE_REF_PATTERN = re.compile(r"^ev_[A-Za-z0-9_-]{20,96}$")

#: Quyền gọi tool theo actor. Không agent nào được truy cập toàn bộ gateway.
TOOL_SCOPES: dict[str, frozenset[str]] = {
    "order-agent": frozenset({"get_order", "get_order_items", "get_sellers",
                              "get_product_context"}),
    "shipment-agent": frozenset({"get_shipment_summary"}),
    "payment-agent": frozenset({"get_order_payments", "get_payment_timeline",
                                "get_refund_timeline"}),
    "policy-agent": frozenset({"get_policy"}),
}

#: Trần số lần gọi tool cho mỗi agent trong một case (chặn vòng lặp).
MAX_CALLS_PER_AGENT = 8

#: Timeout cho một lượt chạy của specialist agent, tính bằng giây.
AGENT_TIMEOUT_SECONDS = 120.0


class ToolScopeError(RuntimeError):
    """Agent cố gọi tool ngoài phạm vi được cấp."""


@dataclass(frozen=True)
class Task:
    """Đơn vị công việc coordinator giao cho một specialist agent."""

    case_id: str
    actor: str
    order_id: str | None
    policy_version: str | None


class AgentContext:
    """Cổng MCP đã giới hạn phạm vi, cấp riêng cho một actor trong một case."""

    def __init__(
        self,
        task: Task,
        gateway: EvidenceGateway,
        trace: TraceWriter,
        allowed_tools: frozenset[str],
    ) -> None:
        self.task = task
        self.case_id = task.case_id
        self.actor = task.actor
        self._gateway = gateway
        self._trace = trace
        self._allowed = allowed_tools
        self._calls = 0

    @property
    def call_count(self) -> int:
        return self._calls

    async def call(self, tool_name: str, **arguments: str) -> tuple[Any, EvidenceItem]:
        """Gọi một tool MCP và ghi nhận evidence. Trả về `(data, evidence_item)`."""
        if tool_name not in self._allowed:
            raise ToolScopeError(
                f"{self.actor} không được phép gọi {tool_name!r}; "
                f"phạm vi cho phép: {sorted(self._allowed)}"
            )
        if self._calls >= MAX_CALLS_PER_AGENT:
            raise RuntimeError(f"{self.actor} vượt trần {MAX_CALLS_PER_AGENT} call cho một case")
        self._calls += 1

        evidence = await self._gateway.call(tool_name, case_id=self.case_id, **arguments)

        ref = evidence["evidence_ref"]
        if not EVIDENCE_REF_PATTERN.fullmatch(ref):
            raise ValueError(f"{tool_name} trả về evidence_ref sai định dạng: {ref!r}")

        item = EvidenceItem(evidence_ref=ref, domain=evidence["domain"], tool_name=tool_name)
        self._trace.emit(
            case_id=self.case_id,
            event_type="tool_result_consumed",
            actor=self.actor,
            tool_name=tool_name,
            evidence_refs=[ref],
            attributes={"domain": evidence["domain"]},
        )
        return evidence["data"], item


SpecialistAgent = Callable[[dict[str, Any], AgentContext], Awaitable[Finding]]


class Dispatcher:
    """Điều phối vòng đời một task: giao việc, chạy, bàn giao kết quả."""

    def __init__(self, case: dict[str, Any], gateway: EvidenceGateway, trace: TraceWriter) -> None:
        self.case = case
        self.case_id = case["case_id"]
        self._gateway = gateway
        self._trace = trace

    async def run(self, actor: str, agent: SpecialistAgent, *, handoff_to: str) -> Finding:
        """Giao việc cho `actor`, chạy agent, rồi bàn giao cho `handoff_to`.

        Agent lỗi hoặc quá hạn không làm hỏng cả case: trả về Finding rỗng kèm
        decision code quan sát được, để verifier hạ confidence thay vì đoán bừa.
        """
        request = self.case["customer_request"]
        task = Task(
            case_id=self.case_id,
            actor=actor,
            order_id=request.get("claimed_order_id"),
            policy_version=self.case.get("policy_version"),
        )
        scope = TOOL_SCOPES.get(actor, frozenset())
        context = AgentContext(task, self._gateway, self._trace, scope)

        self._trace.emit(
            case_id=self.case_id,
            event_type="task_assigned",
            actor="coordinator",
            target=actor,
            attributes={"tool_scope": len(scope)},
        )

        decision_code = "AGENT_OK"
        try:
            finding = await asyncio.wait_for(agent(self.case, context), AGENT_TIMEOUT_SECONDS)
        except TimeoutError:
            decision_code = "AGENT_TIMEOUT"
            finding = Finding(actor=actor, confidence=0.0)
        except ToolScopeError:
            raise
        except (RuntimeError, ValueError, KeyError) as exc:
            decision_code = f"AGENT_ERROR_{type(exc).__name__}"[:80]
            finding = Finding(actor=actor, confidence=0.0)

        self._trace.emit(
            case_id=self.case_id,
            event_type="handoff",
            actor=actor,
            target=handoff_to,
            decision_code=decision_code,
            evidence_refs=finding.refs()[:20] or None,
            attributes={
                "signals": ",".join(finding.signals)[:200],
                "calls": context.call_count,
            },
        )
        return finding
