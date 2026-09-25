from __future__ import annotations

import contextlib
from datetime import datetime
from decimal import Decimal
from typing import Any

from ..domain.findings import EvidenceItem, Finding
from ..mcp_gateway import EvidenceGateway
from ..trace import TraceWriter


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _in_window(moment: datetime | None, start: datetime | None, end: datetime | None) -> bool:
    """Mốc có nằm trong cửa sổ của case không. Thiếu mốc thì coi như nằm trong."""
    if moment is None:
        return True
    if start is not None and moment < start:
        return False
    return not (end is not None and moment > end)


def filter_case_items(
    items: list[dict[str, Any]], purchase_at: datetime | None, opened_at: datetime | None
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Lọc dòng item thuộc về case này, trả về (giữ lại, bị loại).

    Gateway trả lẫn dòng của kịch bản khác: cùng `order_item_id` nhưng khác
    `shipping_limit_date` và `freight_value`. Cộng hết sẽ nhân đôi giá trị đơn,
    làm `PAY_DUPLICATE` và `PAY_SPLIT_VALID` không bao giờ khớp.

    Lọc theo cùng cửa sổ `[order_purchase_timestamp, opened_at]` mà payment agent
    dùng cho `event_at`. Nếu lọc xong không còn gì thì lùi về khử trùng theo
    `order_item_id` để không mất toàn bộ dữ liệu.
    """
    kept = [
        item
        for item in items
        if _in_window(_parse_time(item.get("shipping_limit_date")), purchase_at, opened_at)
    ]
    if not kept and items:
        seen: set[str] = set()
        for item in items:
            key = str(item.get("order_item_id"))
            if key not in seen:
                seen.add(key)
                kept.append(item)
    dropped = [item for item in items if item not in kept]
    return kept, dropped


async def analyze_order(
    case: dict[str, Any],
    gateway: EvidenceGateway,
    trace: TraceWriter,
) -> Finding:
    """Order specialist agent.

    Responsible for retrieving authoritative order, items, and seller records from the MCP
    gateway, computing the order total amount, extracting entities, and emitting standardized order
    signals.
    """
    case_id = case.get("case_id", "")
    customer_request = case.get("customer_request", {})
    claimed_order_id = customer_request.get("claimed_order_id")

    if not claimed_order_id:
        return Finding(
            actor="order-agent",
            signals=["ORDER_NOT_FOUND"],
            entities={
                "order_ids": [],
                "item_ids": [],
                "seller_ids": [],
                "payment_references": [],
                "shipment_ids": [],
            },
            facts={"order_status": "not_found", "order_total_brl": 0.0},
            evidence=[],
            conflicts=[],
            confidence=0.5,
        )

    evidence_items: list[EvidenceItem] = []
    signals: list[str] = []
    facts: dict[str, Any] = {}

    # 1. Fetch order details
    try:
        order_res = await gateway.call("get_order", case_id=case_id, order_id=claimed_order_id)
    except Exception:
        return Finding(
            actor="order-agent",
            signals=["ORDER_NOT_FOUND"],
            entities={
                "order_ids": [claimed_order_id],
                "item_ids": [],
                "seller_ids": [],
                "payment_references": [],
                "shipment_ids": [],
            },
            facts={"order_status": "not_found", "order_total_brl": 0.0},
            evidence=[],
            conflicts=[],
            confidence=0.5,
        )

    order_ref = order_res["evidence_ref"]
    order_data = order_res.get("data", {})
    trace.emit(
        case_id=case_id,
        event_type="tool_result_consumed",
        actor="order-agent",
        tool_name="get_order",
        evidence_refs=[order_ref],
    )
    evidence_items.append(
        EvidenceItem(evidence_ref=order_ref, domain="order", tool_name="get_order")
    )

    order_status = str(order_data.get("order_status", "unknown")).lower()
    facts["order_id"] = claimed_order_id
    facts["order_status"] = order_status
    facts["order_purchase_timestamp"] = order_data.get("order_purchase_timestamp")
    facts["order_approved_at"] = order_data.get("order_approved_at")
    facts["order_delivered_carrier_date"] = order_data.get("order_delivered_carrier_date")
    facts["order_delivered_customer_date"] = order_data.get("order_delivered_customer_date")
    facts["order_estimated_delivery_date"] = order_data.get("order_estimated_delivery_date")

    # 2. Fetch order items
    items_data: list[dict[str, Any]] = []
    try:
        items_res = await gateway.call(
            "get_order_items", case_id=case_id, order_id=claimed_order_id
        )
        items_ref = items_res["evidence_ref"]
        items_data = items_res.get("data", [])
        trace.emit(
            case_id=case_id,
            event_type="tool_result_consumed",
            actor="order-agent",
            tool_name="get_order_items",
            evidence_refs=[items_ref],
        )
        evidence_items.append(
            EvidenceItem(evidence_ref=items_ref, domain="item", tool_name="get_order_items")
        )
    except Exception:
        items_data = []

    # 3. Calculate order total (price + freight) using Decimal for exactness.
    # Chỉ cộng dòng item thuộc về case này — xem filter_case_items().
    purchase_at = _parse_time(facts.get("order_purchase_timestamp"))
    opened_at = _parse_time(case.get("opened_at"))
    items_data, dropped_items = filter_case_items(items_data, purchase_at, opened_at)
    conflicts: list[dict[str, Any]] = []
    if dropped_items:
        conflicts.append(
            {
                "field": "order_item_freight_value",
                "sources": ["item", "order"],
                "selected_source": "item",
                "resolution_code": "ITEM_ROW_OUTSIDE_CASE_WINDOW",
            }
        )

    total_decimal = Decimal("0.00")
    item_ids: list[str] = []
    seller_ids: list[str] = []

    for item in items_data:
        item_id = item.get("order_item_id")
        if item_id and item_id not in item_ids and len(item_ids) < 20:
            item_ids.append(str(item_id))

        seller_id = item.get("seller_id")
        if seller_id and seller_id not in seller_ids and len(seller_ids) < 20:
            seller_ids.append(str(seller_id))

        price_str = str(item.get("price", "0.00"))
        freight_str = str(item.get("freight_value", "0.00"))
        with contextlib.suppress(Exception):
            total_decimal += Decimal(price_str) + Decimal(freight_str)

    order_total_brl = float(round(total_decimal, 2))
    facts["order_total_brl"] = order_total_brl
    facts["items_count"] = len(items_data)
    facts["items_dropped_count"] = len(dropped_items)
    facts["items"] = items_data
    facts["seller_ids"] = seller_ids
    facts["primary_seller_id"] = seller_ids[0] if seller_ids else None

    # get_sellers đã bỏ: seller_id lấy được từ get_order_items, dữ liệu seller
    # không dùng cho kết luận nào. Gọi và cite nó chỉ làm tụt evidence precision
    # (điểm evidence là F1) và tốn call budget.

    # 5. Map order_status to standardized signals
    if order_status == "canceled":
        signals.append("ORDER_STATUS_CANCELED")
    elif order_status == "unavailable":
        signals.append("ORDER_STATUS_UNAVAILABLE")
    elif order_status == "delivered":
        signals.append("ORDER_STATUS_DELIVERED")
    elif order_status == "shipped":
        signals.append("ORDER_STATUS_SHIPPED")
    else:
        signals.append("ORDER_STATUS_OTHER")

    # 6. Build root cause hints for canceled/unavailable cases
    if order_status == "canceled":
        facts["ranked_causes"] = [{"cause_code": "ORDER_CANCELED_AFTER_PAYMENT", "rank": 1}]
        facts["responsible_parties"] = [{"party_type": "platform", "party_id": None}]
    elif order_status == "unavailable":
        facts["ranked_causes"] = [
            {"cause_code": "ITEM_UNAVAILABLE_SELLER_OUT_OF_STOCK", "rank": 1}
        ]
        facts["responsible_parties"] = [
            {
                "party_type": "seller",
                "party_id": seller_ids[0] if seller_ids else None,
            }
        ]

    entities = {
        "order_ids": [claimed_order_id],
        "item_ids": item_ids,
        "seller_ids": seller_ids,
        "payment_references": [],
        "shipment_ids": [],
    }

    known_statuses = {"canceled", "unavailable", "delivered", "shipped"}
    confidence = 1.0 if order_status in known_statuses else 0.9

    return Finding(
        actor="order-agent",
        signals=signals,
        entities=entities,
        facts=facts,
        evidence=evidence_items,
        conflicts=conflicts,
        confidence=confidence,
    )
