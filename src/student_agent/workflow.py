"""Coordinator L3A — CHỦ SỞ HỮU: Đỗ Ngọc Phi.

Luồng: coordinator giao việc tuần tự cho bốn specialist, mỗi bước bàn giao cho
bước sau, rồi verifier kiểm tra bất biến trước khi finalize.

    case_received (cli) -> task_assigned/handoff x4 -> policy_decided
                        -> verification_completed -> case_finalized (cli)

Coordinator không tự gọi MCP. Mọi truy vấn đi qua `AgentContext` của từng agent,
nơi áp allowlist tool và tự emit `tool_result_consumed`.
"""

from __future__ import annotations

from typing import Any

from . import OUTPUT_SCHEMA_VERSION
from .a2a import Dispatcher
from .agents import order_agent, payment_agent, policy_agent, shipment_agent
from .agents.verifier import verify
from .domain import rules
from .domain.findings import (
    Finding,
    collect_conflicts,
    collect_facts,
    collect_signals,
    merge_entities,
)
from .domain.money import compute_refund
from .mcp_gateway import EvidenceGateway
from .trace import TraceWriter

MAX_EVIDENCE_REFS = 30

#: Chuỗi bàn giao: mỗi agent bàn giao cho agent kế tiếp, agent cuối giao verifier.
PIPELINE = (
    ("order-agent", order_agent.analyze, "shipment-agent"),
    ("shipment-agent", shipment_agent.analyze, "payment-agent"),
    ("payment-agent", payment_agent.analyze, "policy-agent"),
    ("policy-agent", policy_agent.analyze, "verifier"),
)


async def solve_case(
    case: dict[str, Any], gateway: EvidenceGateway, trace: TraceWriter
) -> dict[str, Any]:
    case_id = case["case_id"]
    dispatcher = Dispatcher(case, gateway, trace)

    findings: list[Finding] = []
    for actor, agent, handoff_to in PIPELINE:
        findings.append(await dispatcher.run(actor, agent, handoff_to=handoff_to))

    signals = collect_signals(findings)
    facts = collect_facts(findings)
    decision = rules.decide(signals, facts)

    trace.emit(
        case_id=case_id,
        event_type="policy_decided",
        actor="coordinator",
        decision_code=decision.primary_issue,
        attributes={
            "case_status": decision.case_status,
            "signals": ",".join(sorted(signals))[:200],
        },
    )

    refund_total, refund_lines = compute_refund(decision.primary_issue, facts, signals)
    evidence_refs = _dedupe_refs(findings)
    confidence = rules.confidence_for(decision, [f.confidence for f in findings])

    output: dict[str, Any] = {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "case_id": case_id,
        "assessment": {
            "primary_issue": decision.primary_issue,
            "case_status": decision.case_status,
            "confidence": confidence,
        },
        "affected_entities": merge_entities(findings),
        "claim_assessments": _assess_claims(case, decision, evidence_refs, confidence),
        "root_cause_analysis": {
            "ranked_causes": decision.ranked_causes,
            "responsible_parties": decision.responsible_parties,
        },
        "evidence_refs": evidence_refs,
        "data_conflicts": collect_conflicts(findings),
        "financial_resolution": {
            "currency": "BRL",
            "recommended_refund_brl": refund_total,
            "refund_lines": refund_lines,
        },
        "resolution_actions": _actions_for(decision, refund_total),
    }

    problems = verify(output, case, set(evidence_refs), facts)
    trace.emit(
        case_id=case_id,
        event_type="verification_completed",
        actor="verifier",
        decision_code="VERIFY_PASS" if not problems else "VERIFY_FAIL",
        attributes={
            "problem_count": len(problems),
            "first": (problems[0] if problems else "")[:80],
        },
    )
    if problems:
        raise ValueError(f"{case_id}: verifier chặn output -> {problems}")

    return output


def _dedupe_refs(findings: list[Finding]) -> list[str]:
    """Gộp evidence_ref của mọi agent, giữ thứ tự tiêu thụ, cắt theo trần schema.

    Chỉ gom ref mà agent chủ động đưa vào `finding.evidence` — tức ref thực sự
    dẫn tới kết luận. Điểm evidence là F1 nên cite thừa cũng bị phạt.
    """
    refs: list[str] = []
    for finding in findings:
        for ref in finding.refs():
            if ref not in refs:
                refs.append(ref)
    return refs[:MAX_EVIDENCE_REFS]


def _assess_claims(
    case: dict[str, Any],
    decision: rules.Decision,
    evidence_refs: list[str],
    confidence: float,
) -> list[dict[str, Any]]:
    """Đối chiếu từng claim của khách với kết luận dựa trên evidence."""
    result: list[dict[str, Any]] = []
    for claim in case["customer_request"].get("claims", [])[:5]:
        topic = claim.get("topic")
        if decision.primary_issue == "insufficient_evidence":
            verdict = "insufficient_evidence"
        elif topic == "requested_full_refund":
            verdict = "supported" if decision.case_status == "action_required" else "unsupported"
        elif topic == decision.primary_issue:
            verdict = "supported"
        else:
            verdict = "unsupported"
        result.append({
            "claim_id": claim["claim_id"],
            "verdict": verdict,
            "confidence": confidence,
            "evidence_refs": evidence_refs[:20],
        })
    return result


def _actions_for(decision: rules.Decision, refund_total: float) -> list[str]:
    """Sinh hành động từ danh sách đóng trong money.RESOLUTION_ACTIONS."""
    if decision.case_status == "no_action":
        return ["NO_ACTION"]
    if decision.primary_issue == "insufficient_evidence":
        return ["REQUEST_MORE_EVIDENCE"]

    actions: list[str] = []
    if refund_total > 0:
        actions.append("ISSUE_FULL_REFUND" if decision.primary_issue in {
            "canceled_order_paid", "unavailable_order_paid"
        } else "ISSUE_PARTIAL_REFUND")
    if decision.primary_issue == "refund_failed":
        actions.append("RETRY_REFUND")

    escalation = {
        "late_delivery_seller": "ESCALATE_TO_SELLER",
        "late_delivery_logistics": "ESCALATE_TO_LOGISTICS",
        "duplicate_charge": "ESCALATE_TO_PAYMENT_PROVIDER",
        "payment_mismatch": "ESCALATE_TO_PAYMENT_PROVIDER",
        "refund_pending": "ESCALATE_TO_PAYMENT_PROVIDER",
    }.get(decision.primary_issue)
    if escalation:
        actions.append(escalation)

    return actions[:8] or ["REQUEST_MORE_EVIDENCE"]
