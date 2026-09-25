"""Refund arithmetic and money invariants. Pure functions, no MCP calls.

Amounts are summed as ``Decimal`` and converted to ``float`` (2 decimals) only at the
output boundary, so rounding noise never leaks into comparisons.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

TOLERANCE_BRL = Decimal("0.01")
CENT = Decimal("0.01")
MAX_REFUND_LINES = 10

# Closed vocabulary for financial_resolution.refund_lines[].reason_code.
ISSUE_REASON_CODES: dict[str, str] = {
    "canceled_order_paid": "CANCELED_ORDER_FULL_REFUND",
    "unavailable_order_paid": "UNAVAILABLE_ORDER_FULL_REFUND",
    "late_delivery_seller": "LATE_DELIVERY_FREIGHT_REFUND",
    "late_delivery_logistics": "LATE_DELIVERY_FREIGHT_REFUND",
    "duplicate_charge": "DUPLICATE_CHARGE_EXCESS",
    "payment_mismatch": "PAYMENT_MISMATCH_ADJUSTMENT",
    "refund_failed": "FAILED_REFUND_RETRY",
}
REASON_CODES: frozenset[str] = frozenset(ISSUE_REASON_CODES.values())

# Policy actions that pay money back; a positive refund needs one, no_action forbids them.
REFUND_ACTIONS: frozenset[str] = frozenset(
    {"issue_refund", "refund_freight", "refund_duplicate_charge", "reconcile_payment",
     "retry_refund"}
)


def to_decimal(value: Any) -> Decimal | None:
    """Parse an MCP money value ("44.50", 44.5, Decimal) into Decimal; None if unusable."""
    if value is None or isinstance(value, bool):
        return None
    try:
        # str() first so floats such as 79.0 do not carry binary noise into Decimal.
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def quantize(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def to_brl(value: Decimal) -> float:
    return float(quantize(value))


def sum_brl(values: Iterable[Any]) -> Decimal:
    total = Decimal("0")
    for value in values:
        amount = to_decimal(value)
        if amount is not None:
            total += amount
    return total


def amounts_match(left: Any, right: Any, tolerance: Decimal = TOLERANCE_BRL) -> bool:
    a, b = to_decimal(left), to_decimal(right)
    return a is not None and b is not None and abs(a - b) <= tolerance


def compute_refund(
    order_total_brl: Any,
    captured_total_brl: Any,
    refunded_total_brl: Any,
    signals: Iterable[str],
    policy: Mapping[str, Any] | None,
    *,
    primary_issue: str,
    entity_id: str | None = None,
) -> tuple[float, list[dict[str, Any]]]:
    """Return ``(recommended_refund_brl, refund_lines)`` for the decided primary issue.

    ``policy`` is the ``rules[primary_issue]`` entry from ``get_policy``; its ``refund_brl``
    is the authoritative entitlement. The amount is then limited to what the customer
    actually paid and has not already been refunded (``refunded_total_brl`` counts only
    completed refunds).
    """
    del order_total_brl  # entitlement comes from policy; kept for the agreed signature
    reason_code = ISSUE_REASON_CODES.get(primary_issue)
    entitlement = to_decimal((policy or {}).get("refund_brl"))
    if reason_code is None or entitlement is None or entitlement <= 0:
        return 0.0, []

    refunded = to_decimal(refunded_total_brl) or Decimal("0")
    captured = to_decimal(captured_total_brl)
    if captured is None or "PAY_NONE" in set(signals):
        # Unknown or no capture: nothing proven to give back; never refund on a guess.
        return 0.0, []

    amount = min(entitlement, captured - refunded)
    if amount <= 0:
        return 0.0, []
    amount = quantize(amount)
    line = {"reason_code": reason_code, "amount_brl": float(amount), "entity_id": entity_id}
    return float(amount), [line]


def check_money_invariants(
    output: Mapping[str, Any], *, captured_total_brl: Any = None
) -> list[str]:
    """Return money-consistency violations of a case output; empty means valid."""
    errors: list[str] = []
    financial = output.get("financial_resolution") or {}
    lines = financial.get("refund_lines") or []
    status = (output.get("assessment") or {}).get("case_status")

    if financial.get("currency") != "BRL":
        errors.append("currency must be BRL")

    recommended = to_decimal(financial.get("recommended_refund_brl"))
    if recommended is None:
        errors.append("recommended_refund_brl is missing or not a number")
        return errors
    if recommended < 0:
        errors.append("recommended_refund_brl must be >= 0")

    if len(lines) > MAX_REFUND_LINES:
        errors.append(f"refund_lines has more than {MAX_REFUND_LINES} entries")
    line_total = Decimal("0")
    for index, line in enumerate(lines):
        amount = to_decimal(line.get("amount_brl"))
        if amount is None:
            errors.append(f"refund_lines[{index}].amount_brl is not a number")
            continue
        if amount < 0:
            errors.append(f"refund_lines[{index}].amount_brl must be >= 0")
        if line.get("reason_code") not in REASON_CODES:
            errors.append(f"refund_lines[{index}].reason_code is not in the vocabulary")
        line_total += amount
    if abs(line_total - recommended) > TOLERANCE_BRL:
        errors.append(
            f"refund_lines sum {quantize(line_total)} != recommended_refund_brl "
            f"{quantize(recommended)}"
        )

    if status == "no_action" and recommended > 0:
        errors.append("case_status no_action requires recommended_refund_brl == 0")
    if recommended > 0 and status != "action_required":
        errors.append("a positive refund requires case_status action_required")

    actions = list(output.get("resolution_actions") or [])
    if len(actions) != len(set(actions)):
        errors.append("resolution_actions contains duplicates")
    refund_actions = REFUND_ACTIONS.intersection(actions)
    if recommended > 0 and not refund_actions:
        errors.append("a positive refund requires a refund action in resolution_actions")
    if status == "no_action" and refund_actions:
        errors.append("case_status no_action cannot carry refund actions")

    captured = to_decimal(captured_total_brl)
    if captured is not None and recommended > captured + TOLERANCE_BRL:
        errors.append(
            f"recommended_refund_brl {quantize(recommended)} exceeds captured "
            f"{quantize(captured)}"
        )
    return errors
