"""Payment, refund, policy and money rules. Fixtures mirror real MCP response shapes
(including the out-of-window distractor rows); no network access."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from student_agent.agents import payment_agent, policy_agent
from student_agent.agents.payment_agent import assess_payments, assess_refunds, parse_time
from student_agent.contracts import Contracts
from student_agent.domain.money import check_money_invariants, compute_refund
from student_agent.trace import TraceWriter

ROOT = Path(__file__).resolve().parents[1]
ORDER_ID = "9a31fd9d697e9670777501f720773fd9"
PURCHASE = parse_time("2018-04-23T09:00:00-03:00")
OPENED = parse_time("2018-05-05T09:00:00-03:00")
IN_1 = "2018-04-23T10:00:00-03:00"
IN_2 = "2018-04-23T11:00:00-03:00"
IN_REFUND = "2018-05-01T09:00:00-03:00"
BEFORE = "2018-01-07T10:00:00-03:00"
AFTER = "2018-09-06T10:00:00-03:00"
ORDER_TOTAL = "89.00"

POLICY_RULES: dict[str, Any] = {
    "canceled_order_paid": {
        "case_status": "action_required", "recommended_action": "issue_refund",
        "refund_brl": 79.0, "responsible_parties": [{"party_id": None, "party_type": "platform"}],
    },
    "unavailable_order_paid": {
        "case_status": "action_required", "recommended_action": "issue_refund",
        "refund_brl": 89.0,
        "responsible_parties": [{"party_id": "seller-0c65eb5a1415", "party_type": "seller"}],
    },
    "duplicate_charge": {
        "case_status": "action_required", "recommended_action": "refund_duplicate_charge",
        "refund_brl": 64.0,
        "responsible_parties": [{"party_id": None, "party_type": "payment_provider"}],
    },
    "payment_mismatch": {
        "case_status": "action_required", "recommended_action": "reconcile_payment",
        "refund_brl": 35.0,
        "responsible_parties": [{"party_id": None, "party_type": "payment_provider"}],
    },
    "refund_failed": {
        "case_status": "action_required", "recommended_action": "retry_refund",
        "refund_brl": 52.0,
        "responsible_parties": [{"party_id": None, "party_type": "payment_provider"}],
    },
    "refund_pending": {
        "case_status": "needs_investigation", "recommended_action": "monitor_refund",
        "refund_brl": 0.0,
        "responsible_parties": [{"party_id": None, "party_type": "payment_provider"}],
    },
    "valid_split_payment": {
        "case_status": "no_action", "recommended_action": "document_no_action",
        "refund_brl": 0.0, "responsible_parties": [{"party_id": None, "party_type": "customer"}],
    },
}


def pay(seq: str, kind: str, value: str) -> dict[str, str]:
    return {
        "order_id": ORDER_ID, "payment_sequential": seq, "payment_type": kind,
        "payment_installments": "1", "payment_value": value,
    }


def event(at: str, kind: str, amount: str, status: str) -> dict[str, str]:
    return {
        "order_id": ORDER_ID, "event_at": at, "event_type": kind,
        "amount_brl": amount, "status": status,
    }


def timeline(payments: list[dict], events: list[dict]) -> dict[str, Any]:
    return {"order_id": ORDER_ID, "payments": payments, "events": events}


def assess(data: dict[str, Any], order_total: Any = ORDER_TOTAL) -> dict[str, Any]:
    return assess_payments(
        data, purchase_at=PURCHASE, opened_at=OPENED, order_total_brl=order_total
    )


def output(
    status: str, recommended: float, lines: list[dict], actions: list[str] | None = None
) -> dict[str, Any]:
    if actions is None:
        actions = ["refund_duplicate_charge"] if recommended > 0 else ["document_no_action"]
    return {
        "assessment": {"case_status": status},
        "resolution_actions": actions,
        "financial_resolution": {
            "currency": "BRL", "recommended_refund_brl": recommended, "refund_lines": lines,
        },
    }


def line(amount: float, reason: str = "DUPLICATE_CHARGE_EXCESS") -> dict[str, Any]:
    return {"reason_code": reason, "amount_brl": amount, "entity_id": ORDER_ID}


# --- payment signals -------------------------------------------------------------------


def test_split_payment_ignores_out_of_window_distractor() -> None:
    data = timeline(
        [pay("1", "credit_card", "44.50"), pay("2", "voucher", "44.50"),
         pay("1", "credit_card", "52.00")],
        [event(IN_1, "captured", "44.50", "confirmed"),
         event(IN_2, "captured", "44.50", "confirmed"),
         event(BEFORE, "captured", "52.00", "confirmed")],
    )
    result = assess(data)
    assert result["signals"] == ["PAY_SPLIT_VALID"]
    assert result["facts"]["captured_total_brl"] == 89.0
    assert result["facts"]["excluded_payment_rows"] == 1
    assert result["payment_references"] == [f"{ORDER_ID}:1", f"{ORDER_ID}:2"]


def test_duplicate_charge_with_mixed_payment_types() -> None:
    data = timeline(
        [pay("1", "credit_card", "64.00"), pay("2", "voucher", "64.00"),
         pay("1", "credit_card", "64.00"), pay("2", "voucher", "64.00")],
        [event(IN_1, "captured", "64.00", "confirmed"),
         event(IN_2, "captured", "64.00", "confirmed"),
         event(AFTER, "captured", "64.00", "confirmed"),
         event(AFTER, "captured", "64.00", "confirmed")],
    )
    result = assess(data)
    assert result["signals"] == ["PAY_DUPLICATE"]
    assert result["facts"]["duplicate_amount_brl"] == 64.0
    assert result["facts"]["captured_total_brl"] == 128.0


def test_duplicate_exactly_double_the_order_total() -> None:
    data = timeline(
        [pay("1", "credit_card", "89.00"), pay("2", "credit_card", "89.00")],
        [event(IN_1, "captured", "89.00", "confirmed"),
         event(IN_2, "captured", "89.00", "confirmed")],
    )
    result = assess(data)
    assert result["signals"] == ["PAY_DUPLICATE"]
    assert result["facts"]["duplicate_amount_brl"] == 89.0


def test_mismatch_comes_from_reconciliation_event_and_records_conflict() -> None:
    data = timeline(
        [pay("1", "credit_card", "35.00"), pay("1", "credit_card", "89.00")],
        [event(IN_1, "captured", "35.00", "confirmed"),
         event(IN_2, "reconciliation_mismatch", "35.00", "open"),
         event(AFTER, "captured", "89.00", "confirmed")],
    )
    result = assess(data)
    assert result["signals"] == ["PAY_MISMATCH"]
    assert result["facts"]["mismatch_amount_brl"] == 35.0
    assert len(result["conflicts"]) == 1
    assert len(result["conflicts"][0]["sources"]) >= 2


def test_total_below_order_without_mismatch_event_is_not_mismatch() -> None:
    # refund_failed scenario: 52.00 captured against an 89.00 order, no reconciliation event.
    data = timeline(
        [pay("1", "credit_card", "52.00"), pay("1", "credit_card", "44.50")],
        [event(IN_1, "captured", "52.00", "confirmed"),
         event(BEFORE, "captured", "44.50", "confirmed")],
    )
    result = assess(data)
    assert result["signals"] == ["PAY_CAPTURED"]
    assert result["conflicts"] == []


def test_mismatch_boundary_one_cent_counts_as_split() -> None:
    data = timeline(
        [pay("1", "credit_card", "44.50"), pay("2", "voucher", "44.49")],
        [event(IN_1, "captured", "44.50", "confirmed"),
         event(IN_2, "captured", "44.49", "confirmed")],
    )
    assert assess(data)["signals"] == ["PAY_SPLIT_VALID"]


def test_only_distractor_payments_means_pay_none() -> None:
    data = timeline(
        [pay("1", "credit_card", "89.00")], [event(AFTER, "captured", "89.00", "confirmed")]
    )
    assert assess(data)["signals"] == ["PAY_NONE"]


def test_unknown_order_total_does_not_guess_duplicate() -> None:
    data = timeline(
        [pay("1", "credit_card", "44.50"), pay("2", "voucher", "44.50")],
        [event(IN_1, "captured", "44.50", "confirmed"),
         event(IN_2, "captured", "44.50", "confirmed")],
    )
    assert assess(data, order_total=None)["signals"] == ["PAY_CAPTURED", "PAY_AMOUNT_UNKNOWN"]


# --- refund signals --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "signal"),
    [("pending", "REFUND_PENDING"), ("failed", "REFUND_FAILED"),
     ("completed", "REFUND_COMPLETED")],
)
def test_refund_status_from_latest_in_window_event(status: str, signal: str) -> None:
    data = {
        "order_id": ORDER_ID,
        "events": [event(IN_REFUND, "refund_requested", "52.00", status),
                   event(AFTER, "refund_requested", "89.00", "failed")],
    }
    result = assess_refunds(data, purchase_at=PURCHASE, opened_at=OPENED)
    assert result["signal"] == signal
    assert result["relevant"] is True
    assert result["facts"]["refunded_total_brl"] == (52.0 if status == "completed" else 0.0)


def test_distractor_only_refund_is_refund_none() -> None:
    data = {"order_id": ORDER_ID, "events": [event(BEFORE, "refund_requested", "52.00", "failed")]}
    result = assess_refunds(data, purchase_at=PURCHASE, opened_at=OPENED)
    assert result["signal"] == "REFUND_NONE"
    assert result["relevant"] is False


# --- money -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("issue", "captured", "expected", "reason"),
    [
        ("duplicate_charge", "128.00", 64.0, "DUPLICATE_CHARGE_EXCESS"),
        ("payment_mismatch", "35.00", 35.0, "PAYMENT_MISMATCH_ADJUSTMENT"),
        ("refund_failed", "52.00", 52.0, "FAILED_REFUND_RETRY"),
        ("canceled_order_paid", "89.00", 79.0, "CANCELED_ORDER_FULL_REFUND"),
    ],
)
def test_compute_refund_follows_policy_entitlement(
    issue: str, captured: str, expected: float, reason: str
) -> None:
    amount, lines = compute_refund(
        ORDER_TOTAL, captured, "0", [], POLICY_RULES[issue], primary_issue=issue,
        entity_id=ORDER_ID,
    )
    assert amount == expected
    assert lines == [{"reason_code": reason, "amount_brl": expected, "entity_id": ORDER_ID}]


@pytest.mark.parametrize(
    "issue", ["valid_split_payment", "refund_pending", "insufficient_evidence"]
)
def test_compute_refund_zero_for_no_refund_issues(issue: str) -> None:
    assert compute_refund(
        ORDER_TOTAL, ORDER_TOTAL, "0", [], POLICY_RULES.get(issue), primary_issue=issue
    ) == (0.0, [])


def test_compute_refund_already_refunded_is_zero() -> None:
    amount, lines = compute_refund(
        ORDER_TOTAL, "52.00", "52.00", ["REFUND_COMPLETED"], POLICY_RULES["refund_failed"],
        primary_issue="refund_failed",
    )
    assert (amount, lines) == (0.0, [])


def test_compute_refund_never_exceeds_captured_or_refunds_without_capture() -> None:
    amount, _ = compute_refund(
        ORDER_TOTAL, "40.00", "0", [], POLICY_RULES["unavailable_order_paid"],
        primary_issue="unavailable_order_paid",
    )
    assert amount == 40.0
    assert compute_refund(
        ORDER_TOTAL, None, "0", ["PAY_NONE"], POLICY_RULES["canceled_order_paid"],
        primary_issue="canceled_order_paid",
    ) == (0.0, [])


# --- money invariants ------------------------------------------------------------------


def test_invariants_accept_consistent_output() -> None:
    assert check_money_invariants(
        output("action_required", 64.0, [line(64.0)]), captured_total_brl="128.00"
    ) == []


def test_invariant_line_sum_matches_recommended_with_tolerance() -> None:
    assert check_money_invariants(output("action_required", 64.01, [line(64.0)])) == []
    errors = check_money_invariants(output("action_required", 64.02, [line(64.0)]))
    assert any("sum" in error for error in errors)


def test_invariant_no_action_requires_zero_refund() -> None:
    errors = check_money_invariants(output("no_action", 64.0, [line(64.0)]))
    assert any("no_action" in error for error in errors)


def test_invariant_rejects_negative_amounts() -> None:
    errors = check_money_invariants(output("action_required", -1.0, [line(-1.0)]))
    assert any(">= 0" in error for error in errors)


def test_invariant_refund_not_above_captured() -> None:
    errors = check_money_invariants(
        output("action_required", 89.0, [line(89.0)]), captured_total_brl="52.00"
    )
    assert any("exceeds captured" in error for error in errors)


def test_invariant_currency_and_reason_vocabulary() -> None:
    bad = output("action_required", 10.0, [line(10.0, reason="MADE_UP")])
    bad["financial_resolution"]["currency"] = "USD"
    errors = check_money_invariants(bad)
    assert any("BRL" in error for error in errors)
    assert any("vocabulary" in error for error in errors)


def test_invariant_action_consistency() -> None:
    duplicated = output("action_required", 64.0, [line(64.0)],
                        actions=["refund_duplicate_charge", "refund_duplicate_charge"])
    assert any("duplicates" in error for error in check_money_invariants(duplicated))
    no_refund_action = output("action_required", 64.0, [line(64.0)], actions=["monitor_refund"])
    assert any("refund action" in error for error in check_money_invariants(no_refund_action))
    no_action = output("no_action", 0.0, [], actions=["issue_refund"])
    assert any("no_action" in error for error in check_money_invariants(no_action))


# --- policy ----------------------------------------------------------------------------


def test_policy_binds_seller_party_to_case_seller() -> None:
    decision = policy_agent.apply_policy(
        POLICY_RULES, "unavailable_order_paid", seller_ids=["seller-9a31fd9d697e"]
    )
    assert decision["signal"] == "POLICY_REFUND_FULL"
    assert decision["responsible_parties"] == [
        {"party_type": "seller", "party_id": "seller-9a31fd9d697e"}
    ]
    assert decision["resolution_actions"] == ["issue_refund"]


def test_policy_signals_and_missing_rule() -> None:
    assert policy_agent.apply_policy(POLICY_RULES, "duplicate_charge")["signal"] == (
        "POLICY_REFUND_PARTIAL"
    )
    assert policy_agent.apply_policy(POLICY_RULES, "valid_split_payment")["signal"] == (
        "POLICY_NO_REFUND"
    )
    missing = policy_agent.apply_policy(POLICY_RULES, "insufficient_evidence")
    assert missing["rule_found"] is False
    assert missing["resolution_actions"] == ["request_more_evidence"]
    assert missing["case_status"] == "needs_investigation"


# --- agents end to end with a fake gateway ---------------------------------------------


class FakeGateway:
    def __init__(self, responses: dict[str, Any]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def call(self, tool_name: str, *, case_id: str, **arguments: str) -> dict[str, Any]:
        self.calls.append((tool_name, {"case_id": case_id, **arguments}))
        response = self.responses[tool_name]
        if isinstance(response, Exception):
            raise response
        return response


def envelope(ref: str, domain: str, data: Any) -> dict[str, Any]:
    return {
        "schema_version": "day09-mcp-evidence-v1", "evidence_ref": ref,
        "result_hash": "sha256:" + "0" * 64, "domain": domain, "data": data, "warnings": [],
    }


CASE = {
    "case_id": "L3A_CASE_005",
    "opened_at": "2018-05-05T09:00:00-03:00",
    "policy_version": "EC_POLICY_V1",
    "customer_request": {"claimed_order_id": ORDER_ID, "claims": []},
}
PAY_REF = "ev_paymentTimelineRef0001"
REFUND_REF = "ev_refundTimelineRef00001"
POLICY_REF = "ev_policyReferenceRef0001"


def read_trace(path: Path) -> list[dict[str, Any]]:
    return [json.loads(row) for row in path.read_text(encoding="utf-8").splitlines()]


def test_payment_agent_cites_only_evidence_it_used(tmp_path: Path) -> None:
    gateway = FakeGateway({
        "get_payment_timeline": envelope(PAY_REF, "payment", timeline(
            [pay("1", "credit_card", "44.50"), pay("2", "voucher", "44.50")],
            [event(IN_1, "captured", "44.50", "confirmed"),
             event(IN_2, "captured", "44.50", "confirmed")],
        )),
        # Only a distractor refund: fetched, but it does not support the conclusion.
        "get_refund_timeline": envelope(REFUND_REF, "refund", {
            "order_id": ORDER_ID, "events": [event(BEFORE, "refund_requested", "52.00", "failed")],
        }),
    })
    trace = TraceWriter(tmp_path / "trace.jsonl", Contracts(ROOT / "contracts" / "schemas"))
    finding = asyncio.run(payment_agent.analyze(
        CASE, gateway, trace,
        order_facts={"order_purchase_timestamp": "2018-04-23T09:00:00-03:00",
                     "order_total_brl": 89.0},
    ))
    assert finding.signals == ["PAY_SPLIT_VALID", "REFUND_NONE"]
    assert [item.evidence_ref for item in finding.evidence] == [PAY_REF]
    events = read_trace(tmp_path / "trace.jsonl")
    assert [(e["event_type"], e["evidence_refs"]) for e in events] == [
        ("tool_result_consumed", [PAY_REF])
    ]
    assert all("case_id" not in args or args["case_id"] == "L3A_CASE_005"
               for _, args in gateway.calls)


def test_payment_agent_treats_refund_tool_error_as_no_refund(tmp_path: Path) -> None:
    gateway = FakeGateway({
        "get_payment_timeline": envelope(PAY_REF, "payment", timeline(
            [pay("1", "credit_card", "89.00")], [event(IN_1, "captured", "89.00", "confirmed")],
        )),
        "get_refund_timeline": RuntimeError("MCP tool get_refund_timeline failed"),
    })
    trace = TraceWriter(tmp_path / "trace.jsonl", Contracts(ROOT / "contracts" / "schemas"))
    finding = asyncio.run(payment_agent.analyze(
        CASE, gateway, trace,
        order_facts={"order_purchase_timestamp": "2018-04-23T09:00:00-03:00",
                     "order_total_brl": "89.00"},
    ))
    assert finding.signals == ["PAY_CAPTURED", "REFUND_NONE"]
    assert "get_refund_timeline" in finding.facts["errors"]
    refund_calls = [name for name, _ in gateway.calls if name == "get_refund_timeline"]
    assert len(refund_calls) == payment_agent.MAX_ATTEMPTS


def test_policy_agent_emits_policy_decided_with_evidence(tmp_path: Path) -> None:
    gateway = FakeGateway({
        "get_policy": envelope(POLICY_REF, "policy", {
            "currency": "BRL", "policy_version": "EC_POLICY_V1", "rules": POLICY_RULES,
        }),
    })
    trace = TraceWriter(tmp_path / "trace.jsonl", Contracts(ROOT / "contracts" / "schemas"))
    finding = asyncio.run(policy_agent.analyze(
        CASE, gateway, trace, primary_issue="duplicate_charge"
    ))
    assert finding.signals == ["POLICY_REFUND_PARTIAL"]
    assert finding.facts["refund_brl"] == 64.0
    assert [item.evidence_ref for item in finding.evidence] == [POLICY_REF]
    events = read_trace(tmp_path / "trace.jsonl")
    assert [e["event_type"] for e in events] == ["tool_result_consumed", "policy_decided"]
    assert events[1]["decision_code"] == "refund_duplicate_charge"
