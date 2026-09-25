"""Payment / refund agent — CHỦ SỞ HỮU: Phạm Cường Quốc.

Tool được cấp: get_order_payments, get_payment_timeline, get_refund_timeline.
Tín hiệu được phép phát: nhóm PAYMENT_SIGNALS trong domain/findings.py.
"""

from __future__ import annotations

from typing import Any

from ..a2a import AgentContext
from ..domain.findings import Finding

ACTOR = "payment-agent"


async def analyze(case: dict[str, Any], context: AgentContext) -> Finding:
    """TODO(Quốc): đối soát thanh toán và trạng thái hoàn tiền.

        pay, i1 = await context.call("get_order_payments", order_id=order_id)
        tl,  i2 = await context.call("get_payment_timeline", order_id=order_id)
        rf,  i3 = await context.call("get_refund_timeline", order_id=order_id)

    Phân biệt (điểm dễ sai nhất):

    - PAY_SPLIT_VALID : nhiều dòng payment, tổng KHỚP order_total_brl, thường khác loại
    - PAY_DUPLICATE   : tổng VƯỢT order_total_brl, thường cùng loại cùng số tiền
    - PAY_MISMATCH    : lệch ngoài dung sai, không khớp hai mẫu trên

    Dung sai đề xuất 0.01 BRL — chốt ở họp D4.

    Nhớ đọc warnings của response (get_refund_timeline rất có thể báo lý do
    thất bại ở đây) và ghi facts: captured_total_brl, refunded_total_brl,
    payment_references.
    """
    finding = Finding(actor=ACTOR)
    del case, context  # TODO(Quốc): xoá dòng này khi bắt đầu implement
    return finding
