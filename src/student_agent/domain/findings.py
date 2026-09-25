"""Hợp đồng dữ liệu giữa coordinator và các specialist agent.

Specialist agent KHÔNG tự quyết `primary_issue`. Mỗi agent chỉ phát ra:

- `signals`  — mã tín hiệu chuẩn hoá (xem hằng số bên dưới);
- `facts`    — số liệu thô để `rules.py` và `money.py` dùng lại;
- `evidence` — chỉ những `evidence_ref` thực sự dẫn tới kết luận.

`rules.py` ghép tín hiệu của cả bốn agent rồi mới ra kết luận cuối cùng.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

ENTITY_KEYS = (
    "order_ids",
    "item_ids",
    "seller_ids",
    "payment_references",
    "shipment_ids",
)

# --- Từ vựng tín hiệu -------------------------------------------------------
# Chỉ dùng mã trong các nhóm dưới đây. Cần mã mới thì bổ sung tại đây trước,
# nếu không `rules.py` sẽ bỏ qua tín hiệu lạ.

ORDER_SIGNALS = frozenset({
    "ORDER_NOT_FOUND",
    "ORDER_STATUS_CANCELED",
    "ORDER_STATUS_UNAVAILABLE",
    "ORDER_STATUS_DELIVERED",
    "ORDER_STATUS_SHIPPED",
    "ORDER_STATUS_OTHER",
})

SHIPMENT_SIGNALS = frozenset({
    "SHIP_ON_TIME",
    "SHIP_LATE_SELLER",
    "SHIP_LATE_LOGISTICS",
    "SHIP_NOT_DELIVERED",
    "SHIP_TIMELINE_INCOMPLETE",
    "SHIP_TIMELINE_CONFLICT",
})

PAYMENT_SIGNALS = frozenset({
    "PAY_NONE",
    "PAY_CAPTURED",
    "PAY_SPLIT_VALID",
    "PAY_DUPLICATE",
    "PAY_MISMATCH",
    "PAY_AMOUNT_UNKNOWN",
    "REFUND_NONE",
    "REFUND_PENDING",
    "REFUND_FAILED",
    "REFUND_COMPLETED",
})

POLICY_SIGNALS = frozenset({
    "POLICY_REFUND_FULL",
    "POLICY_REFUND_PARTIAL",
    "POLICY_NO_REFUND",
    "POLICY_UNAVAILABLE",
})

KNOWN_SIGNALS = ORDER_SIGNALS | SHIPMENT_SIGNALS | PAYMENT_SIGNALS | POLICY_SIGNALS


@dataclass(frozen=True)
class EvidenceItem:
    """Một `evidence_ref` lấy nguyên văn từ MCP. Không bao giờ sửa giá trị này."""

    evidence_ref: str
    domain: str
    tool_name: str


@dataclass
class Finding:
    """Kết quả quan sát được của một specialist agent."""

    actor: str
    signals: list[str] = field(default_factory=list)
    entities: dict[str, list[str]] = field(default_factory=dict)
    facts: dict[str, Any] = field(default_factory=dict)
    evidence: list[EvidenceItem] = field(default_factory=list)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    confidence: float = 0.0

    def add_signal(self, signal: str) -> None:
        if signal not in KNOWN_SIGNALS:
            raise ValueError(
                f"{self.actor}: tín hiệu lạ {signal!r}; khai báo trong findings.py trước"
            )
        if signal not in self.signals:
            self.signals.append(signal)

    def add_entities(self, key: str, values: list[str] | tuple[str, ...]) -> None:
        if key not in ENTITY_KEYS:
            raise ValueError(f"khoá entity không hợp lệ: {key!r}")
        bucket = self.entities.setdefault(key, [])
        for value in values:
            if value and value not in bucket:
                bucket.append(str(value))

    def refs(self) -> list[str]:
        return [item.evidence_ref for item in self.evidence]


def merge_entities(findings: list[Finding]) -> dict[str, list[str]]:
    """Gộp entity của mọi agent, giữ thứ tự, bỏ trùng, cắt còn 20 theo schema."""
    merged: dict[str, list[str]] = {key: [] for key in ENTITY_KEYS}
    for finding in findings:
        for key, values in finding.entities.items():
            for value in values:
                if value not in merged[key]:
                    merged[key].append(value)
    return {key: values[:20] for key, values in merged.items()}


def collect_signals(findings: list[Finding]) -> set[str]:
    return {signal for finding in findings for signal in finding.signals}


def collect_facts(findings: list[Finding]) -> dict[str, Any]:
    facts: dict[str, Any] = {}
    for finding in findings:
        facts.update(finding.facts)
    return facts


def collect_conflicts(findings: list[Finding]) -> list[dict[str, Any]]:
    """Gộp data_conflicts, bỏ trùng theo `field`, cắt còn 5 theo schema."""
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for finding in findings:
        for conflict in finding.conflicts:
            key = conflict.get("field", "")
            if key and key not in seen:
                seen.add(key)
                result.append(conflict)
    return result[:5]
