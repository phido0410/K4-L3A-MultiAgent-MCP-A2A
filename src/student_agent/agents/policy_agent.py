"""Policy specialist.

Allowed MCP tool: ``get_policy`` only. The policy is fetched per case and never cached across
cases, because evidence refs are scoped to the case that produced them.

Two phases, so the coordinator can decide the primary issue in between:
``load_policy`` fetches the rules; ``decide`` applies the rule for the decided issue, cites
the policy evidence and emits ``policy_decided``. ``analyze`` runs both.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..domain.findings import EvidenceItem, Finding
from ..domain.money import to_brl, to_decimal
from ..mcp_gateway import EvidenceGateway
from ..trace import TraceWriter

ACTOR = "policy-agent"
POLICY_TOOL = "get_policy"
MAX_ATTEMPTS = 2
MAX_PARTIES = 5

# Closed vocabulary for resolution_actions: the policy's own recommended_action values, plus
# the action used when no policy rule applies.
POLICY_ACTIONS: frozenset[str] = frozenset(
    {
        "issue_refund",
        "refund_freight",
        "refund_duplicate_charge",
        "reconcile_payment",
        "retry_refund",
        "monitor_refund",
        "document_no_action",
    }
)
REQUEST_MORE_EVIDENCE = "request_more_evidence"
RESOLUTION_ACTIONS: frozenset[str] = POLICY_ACTIONS | {REQUEST_MORE_EVIDENCE}
FULL_REFUND_ACTIONS = frozenset({"issue_refund"})
PARTY_TYPES = frozenset(
    {"seller", "platform", "logistics_provider", "payment_provider", "customer", "unknown"}
)


@dataclass(frozen=True)
class PolicyContext:
    case_id: str
    policy_version: str
    rules: Mapping[str, Any]
    evidence_ref: str | None
    error: str | None = None


def policy_signal(rule: Mapping[str, Any] | None) -> str:
    refund = to_decimal((rule or {}).get("refund_brl"))
    if refund is None or refund <= 0:
        return "POLICY_NO_REFUND"
    if (rule or {}).get("recommended_action") in FULL_REFUND_ACTIONS:
        return "POLICY_REFUND_FULL"
    return "POLICY_REFUND_PARTIAL"


def responsible_parties(
    rule: Mapping[str, Any] | None, seller_ids: Sequence[str] = ()
) -> list[dict[str, Any]]:
    """Policy parties, with seller ids bound to this case's sellers.

    The public policy names a fixed example seller id; blaming it would point at a seller
    outside the case, so seller entries always take ids from the case's own item data.
    """
    parties: list[dict[str, Any]] = []
    for party in (rule or {}).get("responsible_parties") or []:
        party_type = party.get("party_type")
        if party_type not in PARTY_TYPES:
            party_type = "unknown"
        if party_type == "seller":
            ids: list[str | None] = list(dict.fromkeys(seller_ids)) or [None]
        else:
            ids = [party.get("party_id")]
        for party_id in ids:
            entry = {"party_type": party_type, "party_id": party_id}
            if entry not in parties:
                parties.append(entry)
    if not parties:
        parties.append({"party_type": "unknown", "party_id": None})
    return parties[:MAX_PARTIES]


def apply_policy(
    rules: Mapping[str, Any], primary_issue: str, seller_ids: Sequence[str] = ()
) -> dict[str, Any]:
    """Map a decided primary issue to its policy outcome. Pure function."""
    rule = rules.get(primary_issue)
    if not isinstance(rule, Mapping):
        # insufficient_evidence (or an unknown issue) has no policy rule to apply.
        return {
            "rule_found": False,
            "signal": "POLICY_NO_REFUND",
            "case_status": "needs_investigation",
            "recommended_action": REQUEST_MORE_EVIDENCE,
            "resolution_actions": [REQUEST_MORE_EVIDENCE],
            "refund_brl": 0.0,
            "responsible_parties": [{"party_type": "unknown", "party_id": None}],
        }
    action = rule.get("recommended_action")
    refund = to_decimal(rule.get("refund_brl"))
    return {
        "rule_found": True,
        "signal": policy_signal(rule),
        "case_status": rule.get("case_status"),
        "recommended_action": action,
        "resolution_actions": [action] if action in RESOLUTION_ACTIONS else [],
        "refund_brl": to_brl(refund) if refund is not None and refund > 0 else 0.0,
        "responsible_parties": responsible_parties(rule, seller_ids),
    }


async def load_policy(case: Mapping[str, Any], gateway: EvidenceGateway) -> PolicyContext:
    case_id = case["case_id"]
    version = case.get("policy_version") or ""
    error: str | None = None
    for _ in range(MAX_ATTEMPTS):
        try:
            evidence = await gateway.call(POLICY_TOOL, case_id=case_id, policy_version=version)
        except Exception as exc:  # reported upstream; no default policy is ever substituted
            error = f"{type(exc).__name__}: {exc}"
            continue
        data = evidence.get("data")
        if not isinstance(data, Mapping) or data.get("policy_version") != version:
            return PolicyContext(case_id, version, {}, None, "policy version mismatch")
        rules = data.get("rules")
        if not isinstance(rules, Mapping):
            return PolicyContext(case_id, version, {}, None, "policy has no rules")
        return PolicyContext(case_id, version, rules, evidence["evidence_ref"])
    return PolicyContext(case_id, version, {}, None, error)


def decide(
    context: PolicyContext,
    primary_issue: str,
    trace: TraceWriter,
    *,
    seller_ids: Sequence[str] = (),
) -> Finding:
    decision = apply_policy(context.rules, primary_issue, seller_ids)
    evidence: list[EvidenceItem] = []
    if decision["rule_found"] and context.evidence_ref:
        evidence.append(EvidenceItem(context.evidence_ref, "policy", POLICY_TOOL))
        trace.emit(
            case_id=context.case_id,
            event_type="tool_result_consumed",
            actor=ACTOR,
            tool_name=POLICY_TOOL,
            decision_code=decision["signal"],
            evidence_refs=[context.evidence_ref],
        )
    trace.emit(
        case_id=context.case_id,
        event_type="policy_decided",
        actor=ACTOR,
        decision_code=str(decision["recommended_action"])[:80],
        evidence_refs=[item.evidence_ref for item in evidence] or None,
        attributes={"primary_issue": primary_issue, "policy_version": context.policy_version},
    )

    if context.error is not None:
        confidence = 0.2
    elif decision["rule_found"]:
        confidence = 0.95
    else:
        confidence = 0.5
    return Finding(
        actor=ACTOR,
        signals=[decision["signal"]],
        entities={},
        facts={
            "policy_version": context.policy_version,
            "applied_rule": primary_issue if decision["rule_found"] else None,
            "policy_error": context.error,
            **{key: value for key, value in decision.items() if key != "signal"},
        },
        evidence=evidence,
        conflicts=[],
        confidence=confidence,
    )


async def analyze(
    case: Mapping[str, Any],
    gateway: EvidenceGateway,
    trace: TraceWriter,
    *,
    primary_issue: str,
    seller_ids: Sequence[str] = (),
) -> Finding:
    context = await load_policy(case, gateway)
    return decide(context, primary_issue, trace, seller_ids=seller_ids)
