"""Shipment agent — CHỦ SỞ HỮU: Nguyễn Trường Bảo.

Tool được cấp: get_shipment_summary.
Tín hiệu được phép phát: nhóm SHIPMENT_SIGNALS trong domain/findings.py.
"""

from __future__ import annotations

from typing import Any

from ..a2a import AgentContext
from ..domain.findings import Finding

ACTOR = "shipment-agent"


async def analyze(case: dict[str, Any], context: AgentContext) -> Finding:
    """TODO(Bảo): phân tích timeline giao hàng, phân biệt trễ do seller hay logistics.

        data, item = await context.call("get_shipment_summary", order_id=order_id)

    Tool trả "delivery timestamps, seller handoff limits and shipment events".
    Luật đề xuất (xác nhận lại tên field thật trước khi code cứng):

    - bàn giao cho carrier muộn hơn hạn handoff  -> SHIP_LATE_SELLER
    - seller đúng hạn nhưng giao khách muộn hơn hạn cam kết -> SHIP_LATE_LOGISTICS
    - giao đúng hạn -> SHIP_ON_TIME
    - chưa giao -> SHIP_NOT_DELIVERED
    - thiếu mốc -> SHIP_TIMELINE_INCOMPLETE
    - mốc mâu thuẫn -> SHIP_TIMELINE_CONFLICT

    Cả hai chặng cùng trễ thì phát CẢ HAI tín hiệu và ghi
    facts["seller_delay_days"], facts["logistics_delay_days"] để rules.py xếp hạng.

    So sánh datetime phải cùng timezone (input dùng offset -03:00), không so chuỗi.
    """
    finding = Finding(actor=ACTOR)
    del case, context  # TODO(Bảo): xoá dòng này khi bắt đầu implement
    return finding
