"""Order / item / seller agent — CHỦ SỞ HỮU: Nguyễn Trường Bảo.

Tool được cấp: get_order, get_order_items, get_sellers, get_product_context.
Tín hiệu được phép phát: nhóm ORDER_SIGNALS trong domain/findings.py.
"""

from __future__ import annotations

from typing import Any

from ..a2a import AgentContext
from ..domain.findings import Finding

ACTOR = "order-agent"

#: order_status -> tín hiệu. Bổ sung khi biết tập giá trị thật từ gateway.
STATUS_SIGNALS = {
    "canceled": "ORDER_STATUS_CANCELED",
    "unavailable": "ORDER_STATUS_UNAVAILABLE",
    "delivered": "ORDER_STATUS_DELIVERED",
    "shipped": "ORDER_STATUS_SHIPPED",
}


async def analyze(case: dict[str, Any], context: AgentContext) -> Finding:
    """TODO(Bảo): đọc order + items + seller, phát tín hiệu trạng thái đơn.

    Khung gọi tool (tên tool đã xác nhận với gateway ngày 2026-09-25):

        order_data, item = await context.call("get_order", order_id=order_id)
        items_data, item2 = await context.call("get_order_items", order_id=order_id)

    `context.call` đã tự nhét case_id, kiểm tra evidence_ref và emit
    `tool_result_consumed`. Chỉ cần thêm `item` vào `finding.evidence` cho những
    evidence thực sự dùng để kết luận — cite thừa bị phạt (điểm evidence là F1).

    Cần điền vào facts: order_status, order_total_brl (tổng price + freight_value,
    Quốc cần số này để đối chiếu thanh toán), seller_ids.
    """
    finding = Finding(actor=ACTOR)
    del case, context  # TODO(Bảo): xoá dòng này khi bắt đầu implement
    return finding
