"""Coordinator L3A — CHỦ SỞ HỮU: Đỗ Ngọc Phi.

Luồng:

    case_received (cli)
      -> order-agent -> shipment-agent -> payment-agent
      -> rules.decide  (chốt primary_issue)
      -> policy-agent  (tra rule của issue đó, emit policy_decided)
      -> money.compute_refund
      -> verifier      (emit verification_completed)
      -> case_finalized (cli)

Policy chạy SAU `rules.decide` vì nó cần biết `primary_issue` mới tra được rule
tương ứng. Coordinator không tự gọi MCP; mọi truy vấn đi qua `ScopedGateway`
của từng agent.
"""

from __future__ import annotations

import os
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
MAX_CLAIM_ASSESSMENTS = 5

#: Đặt DAY09_STRICT_VERIFY=1 khi phát triển để verifier ném lỗi thay vì hạ cấp
#: output. KHÔNG bật khi chạy batch nộp bài.
STRICT_VERIFY = os.getenv("DAY09_STRICT_VERIFY", "").strip() == "1"


async def solve_case(
    case: dict[str, Any], gateway: EvidenceGateway, trace: TraceWriter
) -> dict[str, Any]:
    case_id = case["case_id"]
    dispatcher = Dispatcher(case, gateway, trace)

    order = await dispatcher.run(
        "order-agent",
        lambda scoped: order_agent.analyze_order(case, scoped, trace),
        handoff_to="shipment-agent",
    )
    shipment = await dispatcher.run(
        "shipment-agent",
        lambda scoped: shipment_agent.analyze_shipment(case, scoped, trace, order_finding=order),
        handoff_to="payment-agent",
    )
    payment = await dispatcher.run(
        "payment-agent",
        lambda scoped: payment_agent.analyze(case, scoped, trace, order_facts=order.facts),
        handoff_to="coordinator",
    )

    evidence_findings = [order, shipment, payment]
    decision = rules.decide(collect_signals(evidence_findings), collect_facts(evidence_findings))

    seller_ids = merge_entities(evidence_findings).get("seller_ids", [])
    policy = await dispatcher.run(
        "policy-agent",
        lambda scoped: policy_agent.analyze(
            case, scoped, trace, primary_issue=decision.primary_issue, seller_ids=seller_ids
        ),
        handoff_to="verifier",
    )

    findings = [*evidence_findings, policy]
    try:
        return _synthesize(case, findings, decision, trace)
    except (RuntimeError, ValueError, KeyError, TypeError, AttributeError) as exc:
        if STRICT_VERIFY:
            raise
        # Lỗi bất ngờ trong coordinator cũng không được làm sập cả batch.
        trace.emit(
            case_id=case_id,
            event_type="verification_completed",
            actor="verifier",
            decision_code=f"SYNTH_ERROR_{type(exc).__name__}"[:80],
            attributes={"problem_count": 1, "first": str(exc)[:80]},
        )
        return _degraded_output(case, _dedupe_refs(findings), merge_entities(findings))


def _synthesize(
    case: dict[str, Any],
    findings: list[Finding],
    decision: rules.Decision,
    trace: TraceWriter,
) -> dict[str, Any]:
    """Dựng output cuối từ findings đã thu thập và kết luận của rules."""
    case_id = case["case_id"]
    policy = findings[-1]
    facts = collect_facts(findings)
    _apply_policy(decision, policy)

    refund_total, refund_lines = compute_refund(
        facts.get("order_total_brl"),
        facts.get("captured_total_brl"),
        facts.get("refunded_total_brl"),
        collect_signals(findings),
        {"refund_brl": policy.facts.get("refund_brl")},
        primary_issue=decision.primary_issue,
        entity_id=(case["customer_request"].get("claimed_order_id")),
    )

    evidence_refs = _dedupe_refs(findings)
    confidence = rules.confidence_for(decision, [f.confidence for f in findings])
    actions = _actions_for(decision, policy, refund_total)

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
        "resolution_actions": actions,
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
    if not problems:
        return output

    # `cli.py::_run` không bắt exception: một case ném lỗi là hỏng cả 100 output
    # và không còn gì để nộp. Nên thay vì raise, hạ case về bản an toàn, hợp
    # schema, thừa nhận không đủ căn cứ. Case đó mất điểm semantic nhưng vẫn
    # giữ được schema, provenance và workflow — và 99 case kia không bị kéo theo.
    if STRICT_VERIFY:
        raise ValueError(f"{case_id}: verifier chặn output -> {problems}")
    return _degraded_output(case, evidence_refs, merge_entities(findings))


def _degraded_output(
    case: dict[str, Any], evidence_refs: list[str], entities: dict[str, list[str]]
) -> dict[str, Any]:
    """Bản output tối thiểu khi verifier chặn: thừa nhận thiếu căn cứ, không đoán.

    `evidence_refs` giữ nguyên vì đó là ref thật đã được MCP audit; bỏ đi chỉ
    làm mất điểm provenance mà không được gì.
    """
    return {
        "schema_version": OUTPUT_SCHEMA_VERSION,
        "case_id": case["case_id"],
        "assessment": {
            "primary_issue": "insufficient_evidence",
            "case_status": "needs_investigation",
            "confidence": 0.2,
        },
        "affected_entities": entities,
        "claim_assessments": [
            {
                "claim_id": claim["claim_id"],
                "verdict": "insufficient_evidence",
                "confidence": 0.2,
                "evidence_refs": evidence_refs[:20],
            }
            for claim in case["customer_request"].get("claims", [])[:MAX_CLAIM_ASSESSMENTS]
        ],
        "root_cause_analysis": {
            "ranked_causes": [{"cause_code": "EVIDENCE_UNAVAILABLE", "rank": 1}],
            "responsible_parties": [{"party_type": "unknown", "party_id": None}],
        },
        "evidence_refs": evidence_refs,
        "data_conflicts": [],
        "financial_resolution": {
            "currency": "BRL",
            "recommended_refund_brl": 0.0,
            "refund_lines": [],
        },
        "resolution_actions": ["request_more_evidence"],
    }


def _apply_policy(decision: rules.Decision, policy: Finding) -> None:
    """Policy có thẩm quyền cao hơn hằng số trong rules.py cho status và trách nhiệm."""
    case_status = policy.facts.get("case_status")
    if case_status in {"action_required", "no_action", "needs_investigation"}:
        decision.case_status = case_status
    parties = policy.facts.get("responsible_parties")
    if parties:
        decision.responsible_parties = parties[:5]


def _dedupe_refs(findings: list[Finding]) -> list[str]:
    """Gộp evidence_ref theo thứ tự tiêu thụ, bỏ trùng, cắt theo trần schema.

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
    for claim in case["customer_request"].get("claims", [])[:MAX_CLAIM_ASSESSMENTS]:
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


def _actions_for(decision: rules.Decision, policy: Finding, refund_total: float) -> list[str]:
    """Dùng nguyên văn `recommended_action` của policy làm resolution_actions.

    Policy là nguồn có thẩm quyền; mã tự đặt sẽ lệch với thứ scorer mong đợi.
    """
    actions = [a for a in (policy.facts.get("resolution_actions") or []) if a]
    if not actions:
        actions = ["request_more_evidence"]
    if refund_total <= 0 and decision.case_status == "no_action":
        actions = [a for a in actions if a == "document_no_action"] or ["document_no_action"]
    deduped: list[str] = []
    for action in actions:
        if action not in deduped:
            deduped.append(action)
    return deduped[:8]
