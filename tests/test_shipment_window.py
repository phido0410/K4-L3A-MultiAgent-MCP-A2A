"""Regression: shipment distractor rows outside [purchase, opened_at] must not drive delays.

Mirrors L3A_CASE_005: an on-time order whose response also carries a distractor
shipping limit dated before the purchase and a confirmed late event from another scenario.
"""

from __future__ import annotations

import asyncio
from typing import Any

from student_agent.agents.shipment_agent import analyze_shipment
from student_agent.domain.findings import Finding


class Gateway:
    def __init__(self, data: dict[str, Any]) -> None:
        self.data = data

    async def call(self, tool_name: str, *, case_id: str, **arguments: str) -> dict[str, Any]:
        return {
            "evidence_ref": "ev_shipmentWindowRef0001",
            "domain": "shipment",
            "data": self.data,
        }


class Trace:
    def emit(self, **kwargs: Any) -> dict[str, Any]:
        return kwargs


CASE = {
    "case_id": "L3A_CASE_005",
    "opened_at": "2018-05-05T09:00:00-03:00",
    "customer_request": {"claimed_order_id": "ord_005"},
}
ORDER = Finding(
    actor="order-agent",
    facts={"order_purchase_timestamp": "2018-04-23T09:00:00-03:00"},
)


def shipment(limits: list[str], events: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "order_id": "ord_005",
        "delivered_carrier_at": "2018-04-25T09:00:00-03:00",
        "delivered_customer_at": "2018-05-02T09:00:00-03:00",
        "estimated_delivery_at": "2018-05-03T09:00:00-03:00",
        "shipping_limits": [
            {"order_item_id": "item_1", "seller_id": "seller_1", "shipping_limit_at": at}
            for at in limits
        ],
        "events": events,
    }


def run(data: dict[str, Any]) -> Finding:
    return asyncio.run(analyze_shipment(CASE, Gateway(data), Trace(), order_finding=ORDER))  # type: ignore[arg-type]


def test_distractor_shipping_limit_before_purchase_is_ignored() -> None:
    finding = run(shipment(["2018-04-26T09:00:00-03:00", "2018-01-10T09:00:00-03:00"], []))
    assert finding.signals == ["SHIP_ON_TIME"]
    assert finding.facts["seller_delay_days"] == 0.0


def test_distractor_late_event_outside_window_is_ignored() -> None:
    late = {
        "order_id": "ord_005", "event_at": "2018-09-25T09:00:00-03:00",
        "event_type": "delivered_late", "actor": "logistics_provider", "status": "confirmed",
    }
    finding = run(shipment(["2018-04-26T09:00:00-03:00"], [late]))
    assert finding.signals == ["SHIP_ON_TIME"]


def test_in_window_seller_delay_still_detected() -> None:
    finding = run(shipment(["2018-04-24T09:00:00-03:00", "2018-01-10T09:00:00-03:00"], []))
    assert finding.signals == ["SHIP_LATE_SELLER"]
    assert finding.facts["seller_delay_days"] == 1.0
