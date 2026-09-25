"""Giao thức A2A: phân công task, giới hạn quyền gọi tool, ghi trace quan sát được.

Specialist agent nhận `gateway` và `trace` như bình thường, nhưng `gateway` thực
tế là một `ScopedGateway`: cùng interface với `EvidenceGateway.call()`, khác ở
chỗ nó cưỡng chế

- allowlist tool theo actor (least privilege, ARCHITECTURE.md mục 2);
- `case_id` phải khớp case đang xử lý (chặn evidence chéo case);
- trần số call cho mỗi agent (chặn vòng lặp);
- `evidence_ref` trả về đúng định dạng công khai.

Nhờ vậy agent không phải biết gì về cơ chế này, và coordinator vẫn kiểm soát được
phạm vi truy cập. Trace `tool_result_consumed` do chính agent emit — agent biết
rõ evidence nào thực sự dẫn tới kết luận, coordinator thì không.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .domain.findings import Finding
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

#: Trần số lần gọi tool cho mỗi agent trong một case.
MAX_CALLS_PER_AGENT = 8

#: Timeout cho một lượt chạy của specialist agent, tính bằng giây.
AGENT_TIMEOUT_SECONDS = 120.0


class ToolScopeError(RuntimeError):
    """Agent cố gọi tool ngoài phạm vi được cấp. Lỗi lập trình, không nuốt."""


@dataclass(frozen=True)
class Task:
    """Đơn vị công việc coordinator giao cho một specialist agent."""

    case_id: str
    actor: str
    order_id: str | None
    policy_version: str | None


class ScopedGateway:
    """Bọc `EvidenceGateway`, chỉ cho một actor gọi các tool được cấp."""

    def __init__(
        self, inner: EvidenceGateway, actor: str, case_id: str, allowed: frozenset[str]
    ) -> None:
        self._inner = inner
        self._actor = actor
        self._case_id = case_id
        self._allowed = allowed
        self.call_count = 0

    async def call(self, tool_name: str, *, case_id: str, **arguments: str) -> dict[str, Any]:
        if tool_name not in self._allowed:
            raise ToolScopeError(
                f"{self._actor} không được phép gọi {tool_name!r}; "
                f"phạm vi cho phép: {sorted(self._allowed)}"
            )
        if case_id != self._case_id:
            raise ToolScopeError(
                f"{self._actor} gọi {tool_name!r} với case_id {case_id!r}, "
                f"case đang xử lý là {self._case_id!r}"
            )
        if self.call_count >= MAX_CALLS_PER_AGENT:
            raise RuntimeError(f"{self._actor} vượt trần {MAX_CALLS_PER_AGENT} call cho một case")
        self.call_count += 1

        evidence = await self._inner.call(tool_name, case_id=case_id, **arguments)

        ref = evidence.get("evidence_ref", "")
        if not EVIDENCE_REF_PATTERN.fullmatch(ref):
            raise ValueError(f"{tool_name} trả về evidence_ref sai định dạng: {ref!r}")
        return evidence


AgentRunner = Callable[[ScopedGateway], Awaitable[Finding]]


class Dispatcher:
    """Điều phối vòng đời một task: giao việc, chạy, bàn giao kết quả."""

    def __init__(self, case: dict[str, Any], gateway: EvidenceGateway, trace: TraceWriter) -> None:
        self.case = case
        self.case_id = case["case_id"]
        self._gateway = gateway
        self._trace = trace

    async def run(self, actor: str, runner: AgentRunner, *, handoff_to: str) -> Finding:
        """Giao việc cho `actor`, chạy agent, rồi bàn giao cho `handoff_to`.

        Agent lỗi hoặc quá hạn không làm hỏng cả case: trả về Finding rỗng kèm
        decision code quan sát được, để rules hạ về `insufficient_evidence`
        thay vì đoán bừa.
        """
        scope = TOOL_SCOPES.get(actor, frozenset())
        scoped = ScopedGateway(self._gateway, actor, self.case_id, scope)

        self._trace.emit(
            case_id=self.case_id,
            event_type="task_assigned",
            actor="coordinator",
            target=actor,
            attributes={"tool_scope": len(scope)},
        )

        decision_code = "AGENT_OK"
        try:
            finding = await asyncio.wait_for(runner(scoped), AGENT_TIMEOUT_SECONDS)
        except TimeoutError:
            decision_code = "AGENT_TIMEOUT"
            finding = Finding(actor=actor, confidence=0.0)
        except ToolScopeError:
            raise
        except (RuntimeError, ValueError, KeyError, TypeError) as exc:
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
                "calls": scoped.call_count,
            },
        )
        return finding
