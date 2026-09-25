from __future__ import annotations

import asyncio
from typing import Any

from student_agent.agents.order_agent import analyze_order
from student_agent.agents.shipment_agent import analyze_shipment
from student_agent.domain.findings import Finding


class DummyGateway:
    def __init__(self, responses: dict[str, dict[str, Any]] | None = None) -> None:
        self.responses = responses or {}
        self.called_tools: list[str] = []

    async def call(self, tool_name: str, *, case_id: str, **arguments: str) -> dict[str, Any]:
        self.called_tools.append(tool_name)
        if tool_name in self.responses:
            return self.responses[tool_name]
        raise RuntimeError(f"Mock gateway: no response registered for tool {tool_name}")


class DummyTrace:
    def __init__(self) -> None:
        self.events: list[dict[str, Any]] = []

    def emit(self, **kwargs: Any) -> dict[str, Any]:
        self.events.append(kwargs)
        return kwargs


def test_order_agent_status_canceled() -> None:
    async def _test() -> None:
        case = {"case_id": "CASE_CANCELED", "customer_request": {"claimed_order_id": "ord_001"}}
        gateway = DummyGateway(
            {
                "get_order": {
                    "evidence_ref": "ev_order_test_1234567890123456",
                    "domain": "order",
                    "data": {
                        "order_id": "ord_001",
                        "order_status": "canceled",
                        "order_purchase_timestamp": "2018-01-01T09:00:00-03:00",
                    },
                },
                "get_order_items": {
                    "evidence_ref": "ev_items_test_1234567890123456",
                    "domain": "item",
                    "data": [
                        {
                            "order_item_id": "item_1",
                            "seller_id": "seller_1",
                            "price": "50.00",
                            "freight_value": "12.50",
                        }
                    ],
                },
                "get_sellers": {
                    "evidence_ref": "ev_seller_test_1234567890123456",
                    "domain": "seller",
                    "data": [{"seller_id": "seller_1"}],
                },
            }
        )
        trace = DummyTrace()
        finding = await analyze_order(case, gateway, trace)  # type: ignore[arg-type]

        assert finding.actor == "order-agent"
        assert "ORDER_STATUS_CANCELED" in finding.signals
        assert finding.facts["order_total_brl"] == 62.50
        assert finding.entities["order_ids"] == ["ord_001"]
        assert finding.entities["item_ids"] == ["item_1"]
        assert finding.entities["seller_ids"] == ["seller_1"]
        assert len(finding.evidence) == 3
        assert len(trace.events) == 3

    asyncio.run(_test())


def test_order_agent_status_unavailable() -> None:
    async def _test() -> None:
        case = {"case_id": "CASE_UNAVAILABLE", "customer_request": {"claimed_order_id": "ord_002"}}
        gateway = DummyGateway(
            {
                "get_order": {
                    "evidence_ref": "ev_order_unavail_123456789012",
                    "domain": "order",
                    "data": {"order_id": "ord_002", "order_status": "unavailable"},
                },
                "get_order_items": {
                    "evidence_ref": "ev_items_unavail_123456789012",
                    "domain": "item",
                    "data": [],
                },
            }
        )
        trace = DummyTrace()
        finding = await analyze_order(case, gateway, trace)  # type: ignore[arg-type]

        assert "ORDER_STATUS_UNAVAILABLE" in finding.signals
        assert finding.facts["order_total_brl"] == 0.0

    asyncio.run(_test())


def test_order_agent_not_found() -> None:
    async def _test() -> None:
        case = {"case_id": "CASE_EMPTY", "customer_request": {}}
        gateway = DummyGateway()
        trace = DummyTrace()
        finding = await analyze_order(case, gateway, trace)  # type: ignore[arg-type]

        assert "ORDER_NOT_FOUND" in finding.signals
        assert finding.confidence == 0.5

    asyncio.run(_test())


def test_shipment_on_time() -> None:
    async def _test() -> None:
        case = {"case_id": "CASE_ON_TIME", "customer_request": {"claimed_order_id": "ord_ontime"}}
        gateway = DummyGateway(
            {
                "get_shipment_summary": {
                    "evidence_ref": "ev_ship_ontime_1234567890123",
                    "domain": "shipment",
                    "data": {
                        "order_id": "ord_ontime",
                        "order_status": "delivered",
                        "delivered_carrier_at": "2018-02-10T10:00:00-03:00",
                        "delivered_customer_at": "2018-02-18T10:00:00-03:00",
                        "estimated_delivery_at": "2018-02-20T10:00:00-03:00",
                        "shipping_limits": [
                            {
                                "order_item_id": "it_1",
                                "shipping_limit_at": "2018-02-12T10:00:00-03:00",
                            }
                        ],
                        "events": [],
                    },
                }
            }
        )
        trace = DummyTrace()
        finding = await analyze_shipment(case, gateway, trace)  # type: ignore[arg-type]

        assert "SHIP_ON_TIME" in finding.signals
        assert finding.facts["seller_delay_days"] == 0.0
        assert finding.facts["logistics_delay_days"] == 0.0

    asyncio.run(_test())


def test_shipment_late_seller() -> None:
    async def _test() -> None:
        case = {
            "case_id": "CASE_SELLER_LATE",
            "customer_request": {"claimed_order_id": "ord_late_sel"},
        }
        gateway = DummyGateway(
            {
                "get_shipment_summary": {
                    "evidence_ref": "ev_ship_latesel_123456789012",
                    "domain": "shipment",
                    "data": {
                        "order_id": "ord_late_sel",
                        "order_status": "delivered",
                        "delivered_carrier_at": "2018-02-15T10:00:00-03:00",  # 3 days late
                        "delivered_customer_at": "2018-02-18T10:00:00-03:00",
                        "estimated_delivery_at": "2018-02-20T10:00:00-03:00",
                        "shipping_limits": [
                            {
                                "order_item_id": "it_1",
                                "seller_id": "seller_abc",
                                "shipping_limit_at": "2018-02-12T10:00:00-03:00",
                            }
                        ],
                        "events": [
                            {
                                "event_type": "delivered_late",
                                "actor": "seller",
                                "status": "confirmed",
                            }
                        ],
                    },
                }
            }
        )
        trace = DummyTrace()
        finding = await analyze_shipment(case, gateway, trace)  # type: ignore[arg-type]

        assert "SHIP_LATE_SELLER" in finding.signals
        assert "SHIP_LATE_LOGISTICS" not in finding.signals
        assert finding.facts["seller_delay_days"] == 3.0
        assert finding.facts["ranked_causes"][0]["cause_code"] == "SELLER_HANDOVER_DELAY"
        assert finding.facts["responsible_parties"][0]["party_type"] == "seller"

    asyncio.run(_test())


def test_shipment_late_logistics() -> None:
    async def _test() -> None:
        case = {
            "case_id": "CASE_LOG_LATE",
            "customer_request": {"claimed_order_id": "ord_late_log"},
        }
        gateway = DummyGateway(
            {
                "get_shipment_summary": {
                    "evidence_ref": "ev_ship_latelog_123456789012",
                    "domain": "shipment",
                    "data": {
                        "order_id": "ord_late_log",
                        "order_status": "delivered",
                        "delivered_carrier_at": "2018-02-10T10:00:00-03:00",
                        "delivered_customer_at": "2018-02-25T10:00:00-03:00",  # 5 days late
                        "estimated_delivery_at": "2018-02-20T10:00:00-03:00",
                        "shipping_limits": [
                            {
                                "order_item_id": "it_1",
                                "shipping_limit_at": "2018-02-12T10:00:00-03:00",
                            }
                        ],
                        "events": [
                            {
                                "event_type": "delivered_late",
                                "actor": "logistics_provider",
                                "status": "confirmed",
                            }
                        ],
                    },
                }
            }
        )
        trace = DummyTrace()
        finding = await analyze_shipment(case, gateway, trace)  # type: ignore[arg-type]

        assert "SHIP_LATE_LOGISTICS" in finding.signals
        assert "SHIP_LATE_SELLER" not in finding.signals
        assert finding.facts["logistics_delay_days"] == 5.0
        assert finding.facts["ranked_causes"][0]["cause_code"] == "CARRIER_TRANSIT_DELAY"
        assert finding.facts["responsible_parties"][0]["party_type"] == "logistics_provider"

    asyncio.run(_test())


def test_shipment_both_late() -> None:
    async def _test() -> None:
        case = {"case_id": "CASE_BOTH_LATE", "customer_request": {"claimed_order_id": "ord_both"}}
        gateway = DummyGateway(
            {
                "get_shipment_summary": {
                    "evidence_ref": "ev_ship_both_123456789012345",
                    "domain": "shipment",
                    "data": {
                        "order_id": "ord_both",
                        "order_status": "delivered",
                        "delivered_carrier_at": "2018-02-16T10:00:00-03:00",  # 4d seller delay
                        "delivered_customer_at": "2018-02-25T10:00:00-03:00",  # 5d carrier delay
                        "estimated_delivery_at": "2018-02-20T10:00:00-03:00",
                        "shipping_limits": [
                            {
                                "order_item_id": "it_1",
                                "seller_id": "seller_xyz",
                                "shipping_limit_at": "2018-02-12T10:00:00-03:00",
                            }
                        ],
                        "events": [],
                    },
                }
            }
        )
        trace = DummyTrace()
        finding = await analyze_shipment(case, gateway, trace)  # type: ignore[arg-type]

        assert "SHIP_LATE_SELLER" in finding.signals
        assert "SHIP_LATE_LOGISTICS" in finding.signals
        # Logistics delay (5d) > seller delay (4d) -> Logistics ranked #1
        assert finding.facts["ranked_causes"][0]["cause_code"] == "CARRIER_TRANSIT_DELAY"
        assert finding.facts["ranked_causes"][1]["cause_code"] == "SELLER_HANDOVER_DELAY"

    asyncio.run(_test())


def test_shipment_not_delivered() -> None:
    async def _test() -> None:
        case = {
            "case_id": "CASE_NOT_DELIV",
            "customer_request": {"claimed_order_id": "ord_pending"},
        }
        gateway = DummyGateway(
            {
                "get_shipment_summary": {
                    "evidence_ref": "ev_ship_notdel_123456789012",
                    "domain": "shipment",
                    "data": {
                        "order_id": "ord_pending",
                        "order_status": "shipped",
                        "delivered_carrier_at": "2018-02-10T10:00:00-03:00",
                        "delivered_customer_at": None,
                        "estimated_delivery_at": "2018-02-25T10:00:00-03:00",
                        "shipping_limits": [
                            {
                                "order_item_id": "it_1",
                                "shipping_limit_at": "2018-02-12T10:00:00-03:00",
                            }
                        ],
                        "events": [],
                    },
                }
            }
        )
        trace = DummyTrace()
        finding = await analyze_shipment(case, gateway, trace)  # type: ignore[arg-type]

        assert "SHIP_NOT_DELIVERED" in finding.signals

    asyncio.run(_test())


def test_shipment_timeline_conflict() -> None:
    async def _test() -> None:
        case = {"case_id": "CASE_CONFLICT", "customer_request": {"claimed_order_id": "ord_conf"}}
        gateway = DummyGateway(
            {
                "get_shipment_summary": {
                    "evidence_ref": "ev_ship_conflict_1234567890",
                    "domain": "shipment",
                    "data": {
                        "order_id": "ord_conf",
                        "delivered_carrier_at": "2018-02-20T10:00:00-03:00",
                        # Customer received before carrier received:
                        "delivered_customer_at": "2018-02-10T10:00:00-03:00",
                        "estimated_delivery_at": "2018-02-25T10:00:00-03:00",
                        "shipping_limits": [],
                        "events": [],
                    },
                }
            }
        )
        trace = DummyTrace()
        finding = await analyze_shipment(case, gateway, trace)  # type: ignore[arg-type]

        assert "SHIP_TIMELINE_CONFLICT" in finding.signals

    asyncio.run(_test())


def test_shipment_boundary_exact_deadline() -> None:
    async def _test() -> None:
        case = {"case_id": "CASE_BOUNDARY", "customer_request": {"claimed_order_id": "ord_exact"}}
        exact_carrier = "2018-02-10T10:00:00-03:00"
        exact_delivery = "2018-02-20T10:00:00-03:00"
        gateway = DummyGateway(
            {
                "get_shipment_summary": {
                    "evidence_ref": "ev_ship_exact_1234567890123",
                    "domain": "shipment",
                    "data": {
                        "order_id": "ord_exact",
                        "delivered_carrier_at": exact_carrier,
                        "delivered_customer_at": exact_delivery,
                        "estimated_delivery_at": exact_delivery,
                        "shipping_limits": [
                            {
                                "order_item_id": "it_1",
                                "shipping_limit_at": exact_carrier,
                            }
                        ],
                        "events": [],
                    },
                }
            }
        )
        trace = DummyTrace()
        finding = await analyze_shipment(case, gateway, trace)  # type: ignore[arg-type]

        assert "SHIP_ON_TIME" in finding.signals
        assert finding.facts["seller_delay_days"] == 0.0
        assert finding.facts["logistics_delay_days"] == 0.0

    asyncio.run(_test())


def test_shipment_missing_milestones_incomplete() -> None:
    async def _test() -> None:
        case = {"case_id": "CASE_INCOMP", "customer_request": {"claimed_order_id": "ord_incomp"}}
        gateway = DummyGateway(
            {
                "get_shipment_summary": {
                    "evidence_ref": "ev_ship_incomp_123456789012",
                    "domain": "shipment",
                    "data": {
                        "order_id": "ord_incomp",
                        "delivered_carrier_at": None,
                        "delivered_customer_at": None,
                        "estimated_delivery_at": None,
                        "shipping_limits": [],
                        "events": [],
                    },
                }
            }
        )
        trace = DummyTrace()
        finding = await analyze_shipment(case, gateway, trace)  # type: ignore[arg-type]

        assert "SHIP_TIMELINE_INCOMPLETE" in finding.signals

    asyncio.run(_test())


def test_shipment_cross_domain_conflict_detection() -> None:
    async def _test() -> None:
        case = {"case_id": "CASE_CROSS", "customer_request": {"claimed_order_id": "ord_cross"}}
        gateway = DummyGateway(
            {
                "get_shipment_summary": {
                    "evidence_ref": "ev_ship_cross_1234567890123",
                    "domain": "shipment",
                    "data": {
                        "order_id": "ord_cross",
                        "delivered_carrier_at": "2018-02-10T10:00:00-03:00",
                        "delivered_customer_at": "2018-02-18T10:00:00-03:00",
                        "estimated_delivery_at": "2018-02-20T10:00:00-03:00",
                        "shipping_limits": [
                            {
                                "order_item_id": "it_1",
                                "shipping_limit_at": "2018-02-12T10:00:00-03:00",
                            }
                        ],
                        "events": [],
                    },
                }
            }
        )
        order_finding = Finding(
            actor="order-agent",
            signals=["ORDER_STATUS_DELIVERED"],
            entities={
                "order_ids": ["ord_cross"],
                "item_ids": [],
                "seller_ids": [],
                "payment_references": [],
                "shipment_ids": [],
            },
            facts={
                # Different customer delivery date from shipment's 2018-02-18:
                "order_delivered_customer_date": "2018-02-19T10:00:00-03:00",
                "order_delivered_carrier_date": "2018-02-10T10:00:00-03:00",
            },
            evidence=[],
        )
        trace = DummyTrace()
        finding = await analyze_shipment(
            case, gateway, trace, order_finding=order_finding
        )  # type: ignore[arg-type]

        assert len(finding.conflicts) == 1
        conflict = finding.conflicts[0]
        assert conflict["field"] == "order_delivered_customer_date"
        assert conflict["sources"] == ["order", "shipment"]
        assert conflict["selected_source"] == "shipment"
        assert conflict["resolution_code"] == "PREFER_SHIPMENT_TIMELINE"

    asyncio.run(_test())
