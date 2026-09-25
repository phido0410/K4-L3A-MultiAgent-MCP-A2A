"""Verifier — CHỦ SỞ HỮU: Đỗ Ngọc Phi.

Chạy trước khi finalize. Verifier KHÔNG sửa kết luận nghiệp vụ; nó chỉ chặn
output vi phạm bất biến. Bất biến tài chính uỷ quyền cho
`domain/money.py::check_money_invariants` (chủ sở hữu: Quốc), từ vựng
`resolution_actions` lấy từ `agents/policy_agent.py` — chính là các giá trị
`recommended_action` mà policy trả về.
"""

from __future__ import annotations

from typing import Any

from ..domain.money import check_money_invariants
from .policy_agent import RESOLUTION_ACTIONS

#: Hành động mang tính "không làm gì" — không hợp lệ khi case cần xử lý.
PASSIVE_ACTIONS = {"document_no_action"}


def verify(
    output: dict[str, Any],
    case: dict[str, Any],
    allowed_refs: set[str],
    facts: dict[str, Any],
) -> list[str]:
    """Trả về danh sách vi phạm; rỗng nghĩa là output đạt."""
    problems: list[str] = []

    # V1 — case scope.
    if output.get("case_id") != case["case_id"]:
        problems.append("V1: case_id không khớp input")

    # V2 — evidence ownership: mọi ref phải đến từ call MCP của chính case này.
    for ref in output.get("evidence_refs") or []:
        if ref not in allowed_refs:
            problems.append(f"V2: evidence_ref không thuộc case này: {ref}")

    # V3 — claim linkage: claim_id phải tồn tại trong input.
    known_claims = {c["claim_id"] for c in case["customer_request"].get("claims", [])}
    for assessment in output.get("claim_assessments") or []:
        if assessment.get("claim_id") not in known_claims:
            problems.append(f"V3: claim_id lạ {assessment.get('claim_id')!r}")
        for ref in assessment.get("evidence_refs") or []:
            if ref not in allowed_refs:
                problems.append(f"V3: claim trích dẫn ref ngoài case: {ref}")

    # V4 — entity scope.
    for key, values in (output.get("affected_entities") or {}).items():
        if len(values) != len(set(values)):
            problems.append(f"V4: {key} có phần tử trùng")
        if len(values) > 20:
            problems.append(f"V4: {key} vượt 20 phần tử")

    # V5 — bất biến tài chính (module của Quốc).
    problems.extend(
        check_money_invariants(output, captured_total_brl=facts.get("captured_total_brl"))
    )

    # V6 — nhất quán status / action.
    assessment = output.get("assessment") or {}
    actions = output.get("resolution_actions") or []
    unknown = [a for a in actions if a not in RESOLUTION_ACTIONS]
    if unknown:
        problems.append(f"V6: resolution_actions ngoài danh sách: {unknown}")
    if assessment.get("case_status") == "action_required" and set(actions) <= PASSIVE_ACTIONS:
        problems.append("V6: case_status=action_required nhưng không có hành động thực chất")
    if assessment.get("case_status") == "no_action" and not set(actions) <= PASSIVE_ACTIONS:
        problems.append("V6: case_status=no_action nhưng vẫn đề xuất hành động")

    # V7 — confidence bounds.
    confidence = assessment.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0.0 <= float(confidence) <= 1.0:
        problems.append("V7: confidence ngoài [0,1]")

    # V8 — data_conflicts phải có ít nhất 2 nguồn.
    for index, conflict in enumerate(output.get("data_conflicts") or []):
        if len(conflict.get("sources") or []) < 2:
            problems.append(f"V8: data_conflicts[{index}] có dưới 2 nguồn")

    return problems
