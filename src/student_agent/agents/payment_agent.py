"""Payment/refund specialist.

Allowed MCP tools: ``get_payment_timeline`` and ``get_refund_timeline`` only. Order context
(purchase timestamp, order total) comes from the order agent via the coordinator.

MCP responses mix the case's own rows with distractor rows copied from other scenarios.
Distractors carry timestamps outside ``[order_purchase_timestamp, opened_at]``, so every
payment/refund event is filtered to that window before any rule runs.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from ..domain.findings import EvidenceItem, Finding
from ..domain.money import TOLERANCE_BRL, quantize, sum_brl, to_brl, to_decimal
from ..mcp_gateway import EvidenceGateway
from ..trace import TraceWriter

ACTOR = "payment-agent"
PAYMENT_TOOL = "get_payment_timeline"
REFUND_TOOL = "get_refund_timeline"
MAX_ATTEMPTS = 2
MAX_ENTITY_IDS = 20

CAPTURE_EVENT = "captured"
VOID_CAPTURE_STATUSES = frozenset(
    {"failed", "declined", "voided", "canceled", "cancelled", "reversed", "rejected"}
)
CLOSED_MISMATCH_STATUSES = frozenset({"closed", "resolved", "reconciled"})
REFUND_COMPLETED_STATUSES = frozenset(
    {"completed", "complete", "succeeded", "success", "refunded", "processed", "done"}
)
REFUND_FAILED_STATUSES = frozenset({"failed", "declined", "rejected", "error", "reversed"})

CAUSE_CODES: dict[str, str] = {
    "PAY_DUPLICATE": "DUPLICATE_CAPTURE",
    "PAY_MISMATCH": "PAYMENT_RECONCILIATION_MISMATCH",
    "PAY_SPLIT_VALID": "VALID_SPLIT_PAYMENT",
    "REFUND_FAILED": "REFUND_PROCESSING_FAILED",
    "REFUND_PENDING": "REFUND_PROCESSING_PENDING",
}


def parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    # Naive timestamps cannot be compared safely with the -03:00 case clock.
    return parsed if parsed.tzinfo is not None else None


def in_window(moment: datetime | None, start: datetime | None, end: datetime | None) -> bool:
    if moment is None:
        return False
    if start is not None and moment < start:
        return False
    return not (end is not None and moment > end)


def _pair_payments_with_captures(
    payments: Sequence[Mapping[str, Any]], captures: Sequence[Mapping[str, Any]]
) -> list[tuple[Mapping[str, Any], Mapping[str, Any] | None]]:
    """Attach each payment row to the capture event that timestamps it.

    The gateway lists capture events in payment-row order; when counts differ, fall back to
    the first unused capture with the same amount.
    """
    if len(payments) == len(captures):
        return list(zip(payments, captures, strict=True))
    unused = list(captures)
    pairs: list[tuple[Mapping[str, Any], Mapping[str, Any] | None]] = []
    for row in payments:
        amount = to_decimal(row.get("payment_value"))
        match = next(
            (event for event in unused if to_decimal(event.get("amount_brl")) == amount), None
        )
        if match is not None:
            unused.remove(match)
        pairs.append((row, match))
    return pairs


def assess_payments(
    data: Mapping[str, Any],
    *,
    purchase_at: datetime | None,
    opened_at: datetime | None,
    order_total_brl: Any,
) -> dict[str, Any]:
    """Classify the in-window payment picture of one order. Pure function."""
    order_id = data.get("order_id")
    payments = [row for row in data.get("payments") or [] if isinstance(row, Mapping)]
    events = [event for event in data.get("events") or [] if isinstance(event, Mapping)]
    order_total = to_decimal(order_total_brl)

    captures = [e for e in events if str(e.get("event_type", "")).lower() == CAPTURE_EVENT]
    kept_rows: list[Mapping[str, Any]] = []
    kept_amounts: list[Decimal] = []
    for row, event in _pair_payments_with_captures(payments, captures):
        if event is None:
            continue
        if not in_window(parse_time(event.get("event_at")), purchase_at, opened_at):
            continue
        if str(event.get("status", "")).lower() in VOID_CAPTURE_STATUSES:
            continue
        amount = to_decimal(event.get("amount_brl"))
        if amount is None:
            amount = to_decimal(row.get("payment_value"))
        if amount is None:
            continue
        kept_rows.append(row)
        kept_amounts.append(amount)

    mismatches = [
        event
        for event in events
        if "mismatch" in str(event.get("event_type", "")).lower()
        and str(event.get("status", "")).lower() not in CLOSED_MISMATCH_STATUSES
        and in_window(parse_time(event.get("event_at")), purchase_at, opened_at)
    ]

    captured_total = sum(kept_amounts, Decimal("0"))
    repeated = [amount for amount, count in Counter(kept_amounts).items() if count >= 2]
    excess = None if order_total is None else captured_total - order_total

    signals: list[str] = []
    if not kept_amounts:
        signals.append("PAY_NONE")
        reason = "no in-window captured payment"
    elif mismatches:
        signals.append("PAY_MISMATCH")
        reason = "open reconciliation_mismatch event in window"
    elif order_total is None:
        signals += ["PAY_CAPTURED", "PAY_AMOUNT_UNKNOWN"]
        reason = "captured, but order total unavailable for comparison"
    elif repeated and excess is not None and excess > TOLERANCE_BRL:
        signals.append("PAY_DUPLICATE")
        reason = "repeated capture amount and captured total exceeds order total"
    elif len(kept_amounts) >= 2 and abs(captured_total - order_total) <= TOLERANCE_BRL:
        signals.append("PAY_SPLIT_VALID")
        reason = "multiple captures summing to the order total"
    else:
        signals.append("PAY_CAPTURED")
        reason = "captured payment without reconciliation or duplication anomaly"

    conflicts: list[dict[str, Any]] = []
    if "PAY_MISMATCH" in signals and order_total is not None:
        conflicts.append(
            {
                "field": "payment_total_brl",
                "sources": ["order", "payment"],
                "selected_source": "payment",
                "resolution_code": "PAYMENT_RECONCILIATION_OPEN",
            }
        )

    references: list[str] = []
    for row in kept_rows:
        reference = f"{order_id}:{row.get('payment_sequential')}"
        if reference not in references and len(references) < MAX_ENTITY_IDS:
            references.append(reference)

    installments = [
        int(value)
        for value in (str(row.get("payment_installments", "")).strip() for row in kept_rows)
        if value.isdigit()
    ]
    return {
        "signals": signals,
        "payment_references": references,
        "conflicts": conflicts,
        "facts": {
            "payment_rows": [dict(row) for row in kept_rows],
            "captured_total_brl": to_brl(captured_total) if kept_amounts else None,
            "payment_types": sorted({str(row.get("payment_type")) for row in kept_rows}),
            "max_installments": max(installments) if installments else None,
            "payment_reason": reason,
            "duplicate_amount_brl": to_brl(max(repeated))
            if "PAY_DUPLICATE" in signals
            else None,
            "mismatch_amount_brl": to_brl(sum_brl(e.get("amount_brl") for e in mismatches))
            if mismatches
            else None,
            "excluded_payment_rows": len(payments) - len(kept_rows),
        },
    }


def assess_refunds(
    data: Mapping[str, Any] | None,
    *,
    purchase_at: datetime | None,
    opened_at: datetime | None,
) -> dict[str, Any]:
    """Classify the in-window refund lifecycle. ``None`` data means no refund record."""
    events = [e for e in (data or {}).get("events") or [] if isinstance(e, Mapping)]
    kept = [
        (moment, event)
        for event in events
        if in_window(moment := parse_time(event.get("event_at")), purchase_at, opened_at)
    ]
    kept.sort(key=lambda pair: pair[0])

    completed = [
        e for _, e in kept if str(e.get("status", "")).lower() in REFUND_COMPLETED_STATUSES
    ]
    refunded_total = sum_brl(e.get("amount_brl") for e in completed)
    if not kept:
        signal, status = "REFUND_NONE", None
    else:
        latest = kept[-1][1]
        status = str(latest.get("status", "")).lower() or None
        if status in REFUND_COMPLETED_STATUSES:
            signal = "REFUND_COMPLETED"
        elif status in REFUND_FAILED_STATUSES:
            signal = "REFUND_FAILED"
        else:
            signal = "REFUND_PENDING"
    return {
        "signal": signal,
        "relevant": bool(kept),
        "facts": {
            "refund_status": status,
            "refunded_total_brl": to_brl(refunded_total),
            "refund_requested_brl": to_brl(quantize(to_decimal(kept[-1][1].get("amount_brl"))))
            if kept and to_decimal(kept[-1][1].get("amount_brl")) is not None
            else None,
            "refund_requested_at": kept[0][1].get("event_at") if kept else None,
            "excluded_refund_events": len(events) - len(kept),
        },
    }


async def _fetch(
    gateway: EvidenceGateway, tool_name: str, *, case_id: str, order_id: str
) -> tuple[dict[str, Any] | None, str | None]:
    """Read-only call with one bounded retry. Returns ``(evidence, error)``."""
    error: str | None = None
    for _ in range(MAX_ATTEMPTS):
        try:
            evidence = await gateway.call(tool_name, case_id=case_id, order_id=order_id)
        except Exception as exc:  # MCP/transport errors are reported, never replaced by guesses
            error = f"{type(exc).__name__}: {exc}"
            continue
        data = evidence.get("data")
        if not isinstance(data, Mapping) or data.get("order_id") not in (None, order_id):
            return None, "evidence scoped to a different order"
        return evidence, None
    return None, error


def _emit_consumed(
    trace: TraceWriter, case_id: str, tool_name: str, evidence_ref: str, decision_code: str
) -> None:
    trace.emit(
        case_id=case_id,
        event_type="tool_result_consumed",
        actor=ACTOR,
        tool_name=tool_name,
        decision_code=decision_code,
        evidence_refs=[evidence_ref],
    )


async def analyze(
    case: Mapping[str, Any],
    gateway: EvidenceGateway,
    trace: TraceWriter,
    *,
    order_facts: Mapping[str, Any] | None = None,
) -> Finding:
    """Run the payment/refund investigation for one case.

    ``order_facts`` are the order agent's facts; ``order_purchase_timestamp`` and
    ``order_total_brl`` are used. Without them the window has no lower bound and totals are
    not compared, which lowers confidence instead of inventing a total.
    """
    case_id = case["case_id"]
    order_id = case["customer_request"]["claimed_order_id"]
    order_facts = order_facts or {}
    purchase_at = parse_time(order_facts.get("order_purchase_timestamp"))
    opened_at = parse_time(case.get("opened_at"))
    order_total = order_facts.get("order_total_brl")

    signals: list[str] = []
    facts: dict[str, Any] = {"order_total_brl": order_total, "errors": {}, "warnings": []}
    evidence: list[EvidenceItem] = []
    conflicts: list[dict[str, Any]] = []
    references: list[str] = []

    payment_evidence, payment_error = await _fetch(
        gateway, PAYMENT_TOOL, case_id=case_id, order_id=order_id
    )
    if payment_evidence is None:
        signals.append("PAY_NONE")
        facts["errors"][PAYMENT_TOOL] = payment_error
    else:
        payments = assess_payments(
            payment_evidence["data"],
            purchase_at=purchase_at,
            opened_at=opened_at,
            order_total_brl=order_total,
        )
        signals += payments["signals"]
        facts.update(payments["facts"])
        facts["warnings"] += list(payment_evidence.get("warnings") or [])
        conflicts += payments["conflicts"]
        references = payments["payment_references"]
        evidence.append(EvidenceItem(payment_evidence["evidence_ref"], "payment", PAYMENT_TOOL))
        _emit_consumed(
            trace, case_id, PAYMENT_TOOL, payment_evidence["evidence_ref"], payments["signals"][0]
        )

    refund_evidence, refund_error = await _fetch(
        gateway, REFUND_TOOL, case_id=case_id, order_id=order_id
    )
    if refund_error is not None:
        # The gateway errors when an order has no refund record; that is the absence of a
        # refund, and there is no evidence object to cite for it.
        facts["errors"][REFUND_TOOL] = refund_error
    refunds = assess_refunds(
        refund_evidence["data"] if refund_evidence else None,
        purchase_at=purchase_at,
        opened_at=opened_at,
    )
    signals.append(refunds["signal"])
    facts.update(refunds["facts"])
    if refund_evidence is not None:
        facts["warnings"] += list(refund_evidence.get("warnings") or [])
        if refunds["relevant"]:
            evidence.append(EvidenceItem(refund_evidence["evidence_ref"], "refund", REFUND_TOOL))
            _emit_consumed(
                trace, case_id, REFUND_TOOL, refund_evidence["evidence_ref"], refunds["signal"]
            )

    facts["cause_codes"] = [CAUSE_CODES[s] for s in signals if s in CAUSE_CODES]

    if payment_evidence is None:
        confidence = 0.2
    elif purchase_at is None or order_total is None:
        confidence = 0.55
    elif facts["warnings"]:
        confidence = 0.75
    else:
        confidence = 0.9

    return Finding(
        actor=ACTOR,
        signals=list(dict.fromkeys(signals)),
        entities={"order_ids": [order_id], "payment_references": references},
        facts=facts,
        evidence=evidence,
        conflicts=conflicts,
        confidence=confidence,
    )
