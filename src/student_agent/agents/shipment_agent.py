from __future__ import annotations

from datetime import datetime
from typing import Any

from ..domain.findings import EvidenceItem, Finding
from ..mcp_gateway import EvidenceGateway
from ..trace import TraceWriter


def _parse_iso(timestamp: str | None) -> datetime | None:
    if not timestamp:
        return None
    try:
        return datetime.fromisoformat(timestamp)
    except Exception:
        return None


def _filter_window(
    rows: list[dict[str, Any]],
    field: str,
    start: datetime | None,
    end: datetime | None,
    *,
    fallback_when_empty: bool,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Giữ lại dòng có mốc thời gian nằm trong cửa sổ của case.

    Dòng thiếu mốc được giữ vì không đủ căn cứ để loại.

    `fallback_when_empty` quyết định xử lý khi lọc xong không còn gì:

    - `shipping_limits` cần ít nhất một hạn mới tính được seller trễ hay không,
      nên bật fallback: thà dùng dòng ngoài cửa sổ còn hơn mù hoàn toàn.
    - `events` thì KHÔNG: danh sách rỗng là hợp lệ và có nghĩa — không có sự
      kiện nào bị đánh dấu. Bật fallback ở đây sẽ hồi sinh đúng cái event nhiễu
      vừa loại, và đó chính là lý do case giao đúng hạn từng bị kết luận
      `late_delivery_logistics` thay vì `unsupported_claim`.
    """
    if start is None and end is None:
        return rows, []
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for row in rows:
        moment = _parse_iso(row.get(field))
        inside = moment is None or (
            (start is None or moment >= start) and (end is None or moment <= end)
        )
        (kept if inside else dropped).append(row)
    if not kept and fallback_when_empty:
        return rows, []
    return kept, dropped


async def analyze_shipment(
    case: dict[str, Any],
    gateway: EvidenceGateway,
    trace: TraceWriter,
    order_finding: Finding | None = None,
) -> Finding:
    """Shipment specialist agent.

    Responsible for retrieving authoritative shipment summary, auditing delivery timelines,
    differentiating between seller handover delay vs logistics carrier transit delay, detecting
    cross-domain timeline conflicts, and identifying root cause / responsible parties.
    """
    case_id = case.get("case_id", "")
    customer_request = case.get("customer_request", {})
    claimed_order_id = customer_request.get("claimed_order_id")

    if not claimed_order_id:
        return Finding(
            actor="shipment-agent",
            signals=["SHIP_TIMELINE_INCOMPLETE"],
            entities={
                "order_ids": [],
                "item_ids": [],
                "seller_ids": [],
                "payment_references": [],
                "shipment_ids": [],
            },
            facts={},
            evidence=[],
            conflicts=[],
            confidence=0.5,
        )

    evidence_items: list[EvidenceItem] = []
    signals: list[str] = []
    conflicts: list[dict[str, Any]] = []
    facts: dict[str, Any] = {}

    try:
        ship_res = await gateway.call(
            "get_shipment_summary", case_id=case_id, order_id=claimed_order_id
        )
    except Exception:
        return Finding(
            actor="shipment-agent",
            signals=["SHIP_TIMELINE_INCOMPLETE"],
            entities={
                "order_ids": [claimed_order_id],
                "item_ids": [],
                "seller_ids": [],
                "payment_references": [],
                "shipment_ids": [],
            },
            facts={},
            evidence=[],
            conflicts=[],
            confidence=0.5,
        )

    ship_ref = ship_res["evidence_ref"]
    ship_data = ship_res.get("data", {})
    trace.emit(
        case_id=case_id,
        event_type="tool_result_consumed",
        actor="shipment-agent",
        tool_name="get_shipment_summary",
        evidence_refs=[ship_ref],
    )
    evidence_items.append(
        EvidenceItem(evidence_ref=ship_ref, domain="shipment", tool_name="get_shipment_summary")
    )

    delivered_carrier_at = ship_data.get("delivered_carrier_at")
    delivered_customer_at = ship_data.get("delivered_customer_at")
    estimated_delivery_at = ship_data.get("estimated_delivery_at")
    shipping_limits: list[dict[str, Any]] = ship_data.get("shipping_limits", [])
    events: list[dict[str, Any]] = ship_data.get("events", [])

    # Gateway trả lẫn dòng của kịch bản khác. Nếu không lọc, một `shipping_limit_at`
    # nhiễu sớm hơn sẽ làm `min()` bên dưới báo seller trễ cho đơn giao đúng hạn —
    # đó là lý do `late_delivery_seller` từng bị dự đoán 25/100 thay vì ~10.
    purchase_at = _parse_iso(
        order_finding.facts.get("order_purchase_timestamp") if order_finding else None
    )
    opened_at = _parse_iso(case.get("opened_at"))
    shipping_limits, dropped_limits = _filter_window(
        shipping_limits, "shipping_limit_at", purchase_at, opened_at, fallback_when_empty=True
    )
    events, _ = _filter_window(
        events, "event_at", purchase_at, opened_at, fallback_when_empty=False
    )

    # Extract entities
    item_ids: list[str] = []
    seller_ids: list[str] = []
    if order_finding:
        item_ids = list(order_finding.entities.get("item_ids", []))
        seller_ids = list(order_finding.entities.get("seller_ids", []))

    for item in shipping_limits:
        it_id = item.get("order_item_id")
        if it_id and it_id not in item_ids and len(item_ids) < 20:
            item_ids.append(str(it_id))
        sel_id = item.get("seller_id")
        if sel_id and sel_id not in seller_ids and len(seller_ids) < 20:
            seller_ids.append(str(sel_id))

    primary_seller_id = (
        seller_ids[0]
        if seller_ids
        else (order_finding.facts.get("primary_seller_id") if order_finding else None)
    )

    # Cross-source conflict checks (B7)
    if order_finding:
        ord_cust = order_finding.facts.get("order_delivered_customer_date")
        if ord_cust and delivered_customer_at and ord_cust != delivered_customer_at:
            conflicts.append(
                {
                    "field": "order_delivered_customer_date",
                    "sources": ["order", "shipment"],
                    "selected_source": "shipment",
                    "resolution_code": "PREFER_SHIPMENT_TIMELINE",
                }
            )

        ord_carrier = order_finding.facts.get("order_delivered_carrier_date")
        if ord_carrier and delivered_carrier_at and ord_carrier != delivered_carrier_at:
            conflicts.append(
                {
                    "field": "order_delivered_carrier_date",
                    "sources": ["order", "shipment"],
                    "selected_source": "shipment",
                    "resolution_code": "PREFER_SHIPMENT_TIMELINE",
                }
            )

    # Parse timestamps
    dt_carrier = _parse_iso(delivered_carrier_at)
    dt_cust = _parse_iso(delivered_customer_at)
    dt_est = _parse_iso(estimated_delivery_at)

    limit_dates = [
        _parse_iso(lim.get("shipping_limit_at"))
        for lim in shipping_limits
        if lim.get("shipping_limit_at")
    ]
    valid_limit_dates = [d for d in limit_dates if d is not None]
    min_limit = min(valid_limit_dates) if valid_limit_dates else None

    # Calculate delays
    seller_delay_days = 0.0
    if dt_carrier and min_limit:
        diff_sec = (dt_carrier - min_limit).total_seconds()
        seller_delay_days = round(max(0.0, diff_sec / 86400.0), 2)

    logistics_delay_days = 0.0
    if dt_cust and dt_est:
        diff_sec = (dt_cust - dt_est).total_seconds()
        logistics_delay_days = round(max(0.0, diff_sec / 86400.0), 2)

    # Check confirmed audit events
    seller_event_confirmed = any(
        e.get("event_type") == "delivered_late"
        and e.get("actor") == "seller"
        and e.get("status") == "confirmed"
        for e in events
    )
    logistics_event_confirmed = any(
        e.get("event_type") == "delivered_late"
        and e.get("actor") == "logistics_provider"
        and e.get("status") == "confirmed"
        for e in events
    )

    # Signal evaluation (B5)
    # Check impossible timeline conflict (e.g. delivered to customer before handed to carrier)
    if dt_cust and dt_carrier and dt_cust < dt_carrier:
        signals.append("SHIP_TIMELINE_CONFLICT")
    elif dt_cust is None:
        # Not delivered to customer yet
        signals.append("SHIP_NOT_DELIVERED")
        if dt_carrier is None and not valid_limit_dates:
            signals.append("SHIP_TIMELINE_INCOMPLETE")
    elif dt_est is None or (not dt_carrier and not valid_limit_dates):
        # Missing essential milestones
        signals.append("SHIP_TIMELINE_INCOMPLETE")
    else:
        # Order was delivered to customer; evaluate delays
        seller_late = (seller_delay_days > 0.0) or seller_event_confirmed
        logistics_late = (logistics_delay_days > 0.0) or logistics_event_confirmed

        if seller_late and logistics_late:
            signals.append("SHIP_LATE_SELLER")
            signals.append("SHIP_LATE_LOGISTICS")
        elif seller_late:
            signals.append("SHIP_LATE_SELLER")
        elif logistics_late:
            signals.append("SHIP_LATE_LOGISTICS")
        else:
            signals.append("SHIP_ON_TIME")

    if dropped_limits:
        conflicts.append(
            {
                "field": "shipping_limit_at",
                "sources": ["shipment", "item"],
                "selected_source": "shipment",
                "resolution_code": "LIMIT_ROW_OUTSIDE_CASE_WINDOW",
            }
        )

    # Determine ranked causes and responsible parties (B6)
    ranked_causes: list[dict[str, Any]] = []
    responsible_parties: list[dict[str, Any]] = []

    if "SHIP_LATE_SELLER" in signals and "SHIP_LATE_LOGISTICS" in signals:
        if seller_delay_days >= logistics_delay_days:
            ranked_causes = [
                {"cause_code": "SELLER_HANDOVER_DELAY", "rank": 1},
                {"cause_code": "CARRIER_TRANSIT_DELAY", "rank": 2},
            ]
            responsible_parties = [
                {"party_type": "seller", "party_id": primary_seller_id},
                {"party_type": "logistics_provider", "party_id": None},
            ]
        else:
            ranked_causes = [
                {"cause_code": "CARRIER_TRANSIT_DELAY", "rank": 1},
                {"cause_code": "SELLER_HANDOVER_DELAY", "rank": 2},
            ]
            responsible_parties = [
                {"party_type": "logistics_provider", "party_id": None},
                {"party_type": "seller", "party_id": primary_seller_id},
            ]
    elif "SHIP_LATE_SELLER" in signals:
        ranked_causes = [{"cause_code": "SELLER_HANDOVER_DELAY", "rank": 1}]
        responsible_parties = [{"party_type": "seller", "party_id": primary_seller_id}]
    elif "SHIP_LATE_LOGISTICS" in signals:
        ranked_causes = [{"cause_code": "CARRIER_TRANSIT_DELAY", "rank": 1}]
        responsible_parties = [{"party_type": "logistics_provider", "party_id": None}]
    elif "SHIP_NOT_DELIVERED" in signals:
        ranked_causes = [{"cause_code": "SHIPMENT_NOT_DELIVERED_PENDING", "rank": 1}]
        responsible_parties = [{"party_type": "logistics_provider", "party_id": None}]

    facts["delivered_carrier_at"] = delivered_carrier_at
    facts["delivered_customer_at"] = delivered_customer_at
    facts["estimated_delivery_at"] = estimated_delivery_at
    facts["shipping_limits"] = shipping_limits
    facts["seller_delay_days"] = seller_delay_days
    facts["logistics_delay_days"] = logistics_delay_days
    facts["events"] = events
    facts["ranked_causes"] = ranked_causes
    facts["responsible_parties"] = responsible_parties

    confidence = 1.0 if (seller_event_confirmed or logistics_event_confirmed) else 0.95
    if "SHIP_TIMELINE_INCOMPLETE" in signals or "SHIP_TIMELINE_CONFLICT" in signals:
        confidence = 0.7

    return Finding(
        actor="shipment-agent",
        signals=signals,
        entities={
            "order_ids": [claimed_order_id],
            "item_ids": item_ids,
            "seller_ids": seller_ids,
            "payment_references": [],
            "shipment_ids": [],
        },
        facts=facts,
        evidence=evidence_items,
        conflicts=conflicts,
        confidence=confidence,
    )
