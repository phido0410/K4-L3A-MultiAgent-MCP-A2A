"""Ghép tín hiệu của các specialist agent thành kết luận cuối cùng.

Đây là nơi DUY NHẤT quyết định `primary_issue`. Specialist agent chỉ phát tín hiệu.

Thứ tự ưu tiên dưới đây là bản v1 do coordinator đề xuất; nhóm chốt lại ở buổi
họp D4 (mục C1–C3 trong PHAN_CONG.md). Mọi thay đổi phải cập nhật đồng thời
bảng trong ARCHITECTURE.md.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

#: Ánh xạ primary_issue -> case_status. Mọi giá trị enum đều phải có mặt ở đây.
CASE_STATUS_BY_ISSUE: dict[str, str] = {
    "canceled_order_paid": "action_required",
    "unavailable_order_paid": "action_required",
    "late_delivery_seller": "action_required",
    "late_delivery_logistics": "action_required",
    "payment_mismatch": "action_required",
    "duplicate_charge": "action_required",
    "refund_failed": "action_required",
    "refund_pending": "needs_investigation",   # TODO(D4): action_required hay no_action?
    "valid_split_payment": "no_action",
    "unsupported_claim": "no_action",
    "insufficient_evidence": "needs_investigation",
}

#: Mã nguyên nhân gốc gợi ý theo từng issue (rank 1).
PRIMARY_CAUSE_BY_ISSUE: dict[str, str] = {
    "canceled_order_paid": "ORDER_CANCELED_AFTER_PAYMENT",
    "unavailable_order_paid": "ITEM_UNAVAILABLE_AFTER_PAYMENT",
    "late_delivery_seller": "SELLER_HANDOVER_DELAY",
    "late_delivery_logistics": "CARRIER_TRANSIT_DELAY",
    "payment_mismatch": "PAYMENT_TOTAL_MISMATCH",
    "duplicate_charge": "DUPLICATE_PAYMENT_CAPTURE",
    "refund_failed": "REFUND_EXECUTION_FAILURE",
    "refund_pending": "REFUND_NOT_SETTLED",
    "valid_split_payment": "SPLIT_PAYMENT_AS_DESIGNED",
    "unsupported_claim": "CLAIM_NOT_SUPPORTED_BY_EVIDENCE",
    "insufficient_evidence": "EVIDENCE_UNAVAILABLE",
}

#: Bên chịu trách nhiệm mặc định theo issue. `party_id` được điền sau từ facts.
RESPONSIBLE_TYPE_BY_ISSUE: dict[str, str] = {
    "canceled_order_paid": "platform",
    "unavailable_order_paid": "seller",
    "late_delivery_seller": "seller",
    "late_delivery_logistics": "logistics_provider",
    "payment_mismatch": "payment_provider",
    "duplicate_charge": "payment_provider",
    "refund_failed": "payment_provider",
    "refund_pending": "payment_provider",
    "valid_split_payment": "unknown",
    "unsupported_claim": "customer",
    "insufficient_evidence": "unknown",
}


@dataclass
class Decision:
    primary_issue: str
    case_status: str
    ranked_causes: list[dict[str, Any]] = field(default_factory=list)
    responsible_parties: list[dict[str, Any]] = field(default_factory=list)
    evidence_complete: bool = True
    #: Có tín hiệu cạnh tranh cho một issue khác — kết luận kém chắc chắn hơn.
    ambiguous: bool = False


def decide(signals: set[str], facts: dict[str, Any]) -> Decision:
    """Chọn `primary_issue` theo thứ tự ưu tiên giảm dần.

    Nguyên tắc xếp thứ tự: thiệt hại tài chính trực tiếp và chưa được khắc phục
    xếp trên vấn đề giao nhận; kết luận "không có vấn đề" xếp cuối cùng.
    """
    has_order = bool(signals & {
        "ORDER_STATUS_CANCELED", "ORDER_STATUS_UNAVAILABLE",
        "ORDER_STATUS_DELIVERED", "ORDER_STATUS_SHIPPED", "ORDER_STATUS_OTHER",
    })
    paid = "PAY_CAPTURED" in signals or "PAY_SPLIT_VALID" in signals or "PAY_DUPLICATE" in signals
    settled = "REFUND_COMPLETED" in signals

    issue = _select_issue(signals, has_order, paid, settled)
    complete = has_order and not (signals & {"SHIP_TIMELINE_INCOMPLETE", "PAY_AMOUNT_UNKNOWN"})

    # get_policy trả về bảng quy tắc theo từng issue (xem docs/mcp-evidence-shapes.md).
    # Giá trị từ policy có thẩm quyền cao hơn hằng số hard-code ở module này.
    policy_rule = (facts.get("policy_rules") or {}).get(issue) or {}

    return Decision(
        primary_issue=issue,
        ambiguous=_is_ambiguous(issue, signals),
        case_status=policy_rule.get("case_status") or CASE_STATUS_BY_ISSUE[issue],
        ranked_causes=_ranked_causes(issue, signals),
        responsible_parties=(
            policy_rule.get("responsible_parties") or _responsible_parties(issue, facts)
        )[:5],
        evidence_complete=complete,
    )


def _select_issue(signals: set[str], has_order: bool, paid: bool, settled: bool) -> str:
    if "ORDER_NOT_FOUND" in signals or not has_order:
        return "insufficient_evidence"

    # 1. Khách đã trả tiền cho đơn không bao giờ được giao.
    if "ORDER_STATUS_CANCELED" in signals and paid and not settled:
        return "canceled_order_paid"
    if "ORDER_STATUS_UNAVAILABLE" in signals and paid and not settled:
        return "unavailable_order_paid"

    # 2. Thiệt hại tài chính trực tiếp.
    if "PAY_DUPLICATE" in signals:
        return "duplicate_charge"

    # 3. Khắc phục đang hỏng hoặc chưa xong.
    if "REFUND_FAILED" in signals:
        return "refund_failed"
    if "REFUND_PENDING" in signals:
        return "refund_pending"

    # 4. Sai lệch đối soát.
    if "PAY_MISMATCH" in signals:
        return "payment_mismatch"

    # 5. Giao nhận. Seller trễ xếp trên logistics vì là mắt xích đầu tiên.
    if "SHIP_LATE_SELLER" in signals:
        return "late_delivery_seller"
    if "SHIP_LATE_LOGISTICS" in signals:
        return "late_delivery_logistics"

    # 6. Không tìm thấy vấn đề.
    if "PAY_SPLIT_VALID" in signals:
        return "valid_split_payment"
    if signals & {"SHIP_ON_TIME", "ORDER_STATUS_DELIVERED", "PAY_CAPTURED", "REFUND_COMPLETED"}:
        return "unsupported_claim"
    return "insufficient_evidence"


#: Tín hiệu cạnh tranh: nếu cùng bật với issue đã chọn thì kết luận kém chắc.
COMPETING_SIGNALS: dict[str, set[str]] = {
    "late_delivery_seller": {"SHIP_LATE_LOGISTICS"},
    "late_delivery_logistics": {"SHIP_LATE_SELLER"},
    "payment_mismatch": {"PAY_DUPLICATE", "PAY_SPLIT_VALID"},
    "duplicate_charge": {"PAY_SPLIT_VALID"},
    "valid_split_payment": {"PAY_DUPLICATE", "PAY_MISMATCH"},
}


def _is_ambiguous(issue: str, signals: set[str]) -> bool:
    if signals & {"SHIP_TIMELINE_CONFLICT", "SHIP_TIMELINE_INCOMPLETE"}:
        return True
    return bool(signals & COMPETING_SIGNALS.get(issue, set()))


def _ranked_causes(issue: str, signals: set[str]) -> list[dict[str, Any]]:
    causes = [{"cause_code": PRIMARY_CAUSE_BY_ISSUE[issue], "rank": 1}]
    if issue == "late_delivery_logistics" and "SHIP_LATE_SELLER" in signals:
        causes.append({"cause_code": "SELLER_HANDOVER_DELAY", "rank": 2})
    if issue == "late_delivery_seller" and "SHIP_LATE_LOGISTICS" in signals:
        causes.append({"cause_code": "CARRIER_TRANSIT_DELAY", "rank": 2})
    if "SHIP_TIMELINE_CONFLICT" in signals:
        causes.append({"cause_code": "SHIPMENT_TIMELINE_CONFLICT", "rank": len(causes) + 1})
    return causes[:5]


def _responsible_parties(issue: str, facts: dict[str, Any]) -> list[dict[str, Any]]:
    party_type = RESPONSIBLE_TYPE_BY_ISSUE[issue]
    party_id = None
    if party_type == "seller":
        seller_ids = facts.get("late_seller_ids") or facts.get("seller_ids") or []
        party_id = seller_ids[0] if seller_ids else None
    return [{"party_type": party_type, "party_id": party_id}]


#: Trần confidence theo mức chắc chắn của kết luận.
#: Điểm calibration là 1 − (đúng − confidence)², cực đại khi confidence bằng
#: đúng xác suất kết luận đúng. Một giá trị phẳng cho mọi case luôn dưới tối ưu:
#: quá cao thì case sai bị phạt nặng, quá thấp thì case đúng không được hưởng.
CONFIDENCE_CLEAR = 0.92
CONFIDENCE_AMBIGUOUS = 0.72
CONFIDENCE_INCOMPLETE = 0.55
CONFIDENCE_INSUFFICIENT = 0.30


def confidence_for(decision: Decision, findings_confidence: list[float]) -> float:
    """Confidence phản ánh mức chắc chắn thật của kết luận, không phải hằng số."""
    if not findings_confidence:
        return CONFIDENCE_INSUFFICIENT
    if decision.primary_issue == "insufficient_evidence":
        return CONFIDENCE_INSUFFICIENT
    if not decision.evidence_complete:
        return CONFIDENCE_INCOMPLETE
    if decision.ambiguous:
        return CONFIDENCE_AMBIGUOUS

    # Agent nào cũng kém tự tin thì kết luận cũng không thể chắc.
    agent_floor = min(findings_confidence)
    return round(min(CONFIDENCE_CLEAR, max(agent_floor, 0.4)), 2)
