from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvidenceItem:
    evidence_ref: str  # nguyên văn từ MCP, không sửa
    domain: str  # "order" | "payment" | "shipment" | "item" | "seller" | ...
    tool_name: str  # tên tool đã gọi


@dataclass
class Finding:
    actor: str  # "order-agent", "shipment-agent", "payment-agent", ...
    signals: list[str]  # mã tín hiệu chuẩn hoá theo PHAN_CONG.md mục 4.4
    entities: dict[str, list[str]]  # order_ids, item_ids, seller_ids, ...
    facts: dict[str, Any]  # số liệu thô để rules.py và money.py dùng
    evidence: list[EvidenceItem]  # CHỈ ref thực sự dùng để kết luận
    conflicts: list[dict[str, Any]] = field(default_factory=list)  # xung đột dữ liệu nếu có
    confidence: float = 1.0  # 0.0 - 1.0 mức chắc chắn của agent này
