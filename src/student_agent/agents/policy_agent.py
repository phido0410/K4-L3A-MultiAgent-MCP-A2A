"""Policy agent — CHỦ SỞ HỮU: Phạm Cường Quốc.

Tool được cấp: get_policy.
Tín hiệu được phép phát: nhóm POLICY_SIGNALS trong domain/findings.py.
"""

from __future__ import annotations

from typing import Any

from ..a2a import AgentContext
from ..domain.findings import Finding

ACTOR = "policy-agent"


async def analyze(case: dict[str, Any], context: AgentContext) -> Finding:
    """TODO(Quốc): tra policy và xác định quyền lợi hoàn tiền.

        data, item = await context.call("get_policy", policy_version=policy_version)

    `policy_version` lấy từ case["policy_version"] (hiện tất cả là EC_POLICY_V1).
    Tool trả "public machine-readable policy" nên nhiều khả năng có sẵn bảng
    điều khoản — đọc kỹ trước khi hard-code luật.

    Phát POLICY_REFUND_FULL / POLICY_REFUND_PARTIAL / POLICY_NO_REFUND và ghi
    facts["policy_clause"] để trích dẫn evidence chính xác.
    """
    finding = Finding(actor=ACTOR)
    del case, context  # TODO(Quốc): xoá dòng này khi bắt đầu implement
    return finding
