"""Tính tiền hoàn và bất biến tài chính — CHỦ SỞ HỮU: Phạm Cường Quốc.

Module thuần tính toán, không gọi MCP, nên test được không cần mạng.
`check_money_invariants` được `agents/verifier.py` gọi trước khi finalize.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

#: Dung sai khi so khớp số tiền, tính bằng BRL. TODO(D4): nhóm chốt lại.
MONEY_TOLERANCE_BRL = 0.01

#: Danh sách đóng các mã lý do hoàn tiền. Verifier chặn giá trị ngoài danh sách.
REASON_CODES = frozenset({
    "CANCELED_ORDER_FULL_REFUND",
    "UNAVAILABLE_ORDER_FULL_REFUND",
    "DUPLICATE_CHARGE_EXCESS",
    "LATE_DELIVERY_FREIGHT_REFUND",
    "PAYMENT_MISMATCH_ADJUSTMENT",
    "REFUND_RETRY_OUTSTANDING",
})

#: Danh sách đóng các hành động xử lý.
RESOLUTION_ACTIONS = frozenset({
    "ISSUE_FULL_REFUND",
    "ISSUE_PARTIAL_REFUND",
    "RETRY_REFUND",
    "ESCALATE_TO_SELLER",
    "ESCALATE_TO_LOGISTICS",
    "ESCALATE_TO_PAYMENT_PROVIDER",
    "REQUEST_MORE_EVIDENCE",
    "NO_ACTION",
})


#: Mã lý do tương ứng với từng primary_issue.
REASON_BY_ISSUE: dict[str, str] = {
    "canceled_order_paid": "CANCELED_ORDER_FULL_REFUND",
    "unavailable_order_paid": "UNAVAILABLE_ORDER_FULL_REFUND",
    "duplicate_charge": "DUPLICATE_CHARGE_EXCESS",
    "late_delivery_seller": "LATE_DELIVERY_FREIGHT_REFUND",
    "late_delivery_logistics": "LATE_DELIVERY_FREIGHT_REFUND",
    "payment_mismatch": "PAYMENT_MISMATCH_ADJUSTMENT",
    "refund_failed": "REFUND_RETRY_OUTSTANDING",
    "refund_pending": "REFUND_RETRY_OUTSTANDING",
}


def brl(value: float | Decimal | str) -> float:
    """Làm tròn về 2 chữ số thập phân theo kiểu tiền tệ."""
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def compute_refund(
    primary_issue: str,
    facts: dict[str, Any],
    signals: set[str],
) -> tuple[float, list[dict[str, Any]]]:
    """TODO(Quốc): trả về (recommended_refund_brl, refund_lines).

    Quy tắc mong đợi:

    - canceled_order_paid / unavailable_order_paid -> hoàn toàn bộ captured_total_brl
    - duplicate_charge -> chỉ hoàn PHẦN DƯ: captured_total_brl - order_total_brl
    - late_delivery_* -> theo EC_POLICY_V1 (có thể chỉ hoàn phí ship)
    - đã hoàn xong / no_action -> 0 và refund_lines rỗng

    Mỗi dòng: {"reason_code": <trong REASON_CODES>, "amount_brl": >= 0,
               "entity_id": <order/payment id hoặc None>}.
    Tổng các dòng phải bằng giá trị trả về đầu tiên (xem bất biến M1 bên dưới).
    """
    # get_policy cho sẵn refund_brl theo từng issue — dùng làm mốc thay vì tự suy.
    # Xem docs/mcp-evidence-shapes.md mục get_policy.
    policy_rule = (facts.get("policy_rules") or {}).get(primary_issue) or {}
    policy_amount = policy_rule.get("refund_brl")
    if policy_amount is None:
        return 0.0, []

    del signals  # TODO(Quốc): dùng signals để chia nhiều refund_lines khi cần
    reason = REASON_BY_ISSUE.get(primary_issue)
    if reason is None:
        return 0.0, []
    amount = brl(policy_amount)
    entity_id = (facts.get("order_ids") or [None])[0]
    return amount, [{"reason_code": reason, "amount_brl": amount, "entity_id": entity_id}]


def check_money_invariants(output: dict[str, Any], facts: dict[str, Any]) -> list[str]:
    """Kiểm tra các bất biến tài chính. Trả về danh sách lỗi; rỗng là hợp lệ."""
    problems: list[str] = []
    resolution = output.get("financial_resolution") or {}
    total = resolution.get("recommended_refund_brl")
    lines = resolution.get("refund_lines") or []

    if resolution.get("currency") != "BRL":
        problems.append("M5: currency phải là BRL")

    if not isinstance(total, (int, float)):
        return [*problems, "M0: thiếu recommended_refund_brl"]

    # M1: tổng các dòng phải khớp tổng đề xuất.
    line_sum = sum(float(line.get("amount_brl", 0)) for line in lines)
    if abs(line_sum - float(total)) > MONEY_TOLERANCE_BRL:
        problems.append(f"M1: tổng refund_lines {line_sum:.2f} != recommended {float(total):.2f}")

    # M2: no_action thì không được đề xuất hoàn tiền.
    if (output.get("assessment") or {}).get("case_status") == "no_action" and float(total) > 0:
        problems.append("M2: case_status=no_action nhưng recommended_refund_brl > 0")

    # M3: không có số tiền âm.
    if float(total) < 0:
        problems.append("M3: recommended_refund_brl âm")
    for index, line in enumerate(lines):
        if float(line.get("amount_brl", 0)) < 0:
            problems.append(f"M3: refund_lines[{index}].amount_brl âm")
        if line.get("reason_code") not in REASON_CODES:
            problems.append(f"M4: reason_code lạ {line.get('reason_code')!r}")

    # M6: không hoàn nhiều hơn số đã thu.
    captured = facts.get("captured_total_brl")
    if isinstance(captured, (int, float)) and float(total) - float(captured) > MONEY_TOLERANCE_BRL:
        problems.append(f"M6: hoàn {float(total):.2f} vượt số đã thu {float(captured):.2f}")

    return problems
