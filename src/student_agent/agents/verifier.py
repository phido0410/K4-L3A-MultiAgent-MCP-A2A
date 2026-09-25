"""Verifier — CHỦ SỞ HỮU: Đỗ Ngọc Phi.

Chạy trước khi finalize. Verifier KHÔNG sửa kết luận nghiệp vụ; nó chỉ chặn
output vi phạm bất biến và hạ confidence khi bằng chứng không đủ.
"""

from __future__ import annotations

from typing import Any

from ..domain.money import RESOLUTION_ACTIONS, check_money_invariants

#: Issue nào thì bắt buộc phải có hành động cụ thể (không được chỉ NO_ACTION).
ACTION_REQUIRED_STATUSES = {"action_required"}


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
    entities = output.get("affected_entities") or {}
    for key, values in entities.items():
        if len(values) != len(set(values)):
            problems.append(f"V4: {key} có phần tử trùng")
        if len(values) > 20:
            problems.append(f"V4: {key} vượt 20 phần tử")

    # V5 — bất biến tài chính.
    problems.extend(check_money_invariants(output, facts))

    # V6 — nhất quán status / action.
    assessment = output.get("assessment") or {}
    actions = output.get("resolution_actions") or []
    unknown = [a for a in actions if a not in RESOLUTION_ACTIONS]
    if unknown:
        problems.append(f"V6: resolution_actions ngoài danh sách: {unknown}")
    if assessment.get("case_status") in ACTION_REQUIRED_STATUSES and actions in ([], ["NO_ACTION"]):
        problems.append("V6: case_status=action_required nhưng không có hành động")
    if assessment.get("case_status") == "no_action" and [a for a in actions if a != "NO_ACTION"]:
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
