"""Chạy thử workflow trên vài case thật trước khi chạy batch 100.

Dùng để kiểm tra nhanh sau khi merge hoặc sửa luật, tốn ~5 lần gọi MCP mỗi case
thay vì 500 lần của cả batch.

    python scripts/smoke_cases.py                      # 5 case mặc định
    python scripts/smoke_cases.py L3A_CASE_007         # case chỉ định
    python scripts/smoke_cases.py --json L3A_CASE_007  # in output đầy đủ

Mỗi dòng kết quả cho biết claim của khách, kết luận của hệ thống, số tiền hoàn
và số evidence đã cite. Claim KHÁC issue là bình thường — customer message
không phải ground truth.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from student_agent.config import Settings  # noqa: E402
from student_agent.contracts import Contracts  # noqa: E402
from student_agent.mcp_gateway import connect_gateway  # noqa: E402
from student_agent.trace import TraceWriter  # noqa: E402
from student_agent.workflow import solve_case  # noqa: E402

#: Mỗi case đại diện một loại claim khác nhau.
DEFAULT_CASES = [
    "L3A_CASE_001",  # canceled_order_paid
    "L3A_CASE_007",  # duplicate_charge  <- phép thử cho bản vá order_total
    "L3A_CASE_005",  # valid_split_payment
    "L3A_CASE_003",  # late_delivery_seller
    "L3A_CASE_009",  # refund_failed
]


async def run(case_ids: list[str], as_json: bool) -> int:
    settings = Settings.load(ROOT)
    contracts = Contracts(ROOT / "contracts" / "schemas")
    trace_path = ROOT / "traces" / "smoke-trace.jsonl"
    trace_path.unlink(missing_ok=True)
    trace = TraceWriter(trace_path, contracts)

    failures = 0
    async with connect_gateway(settings.mcp_endpoint, settings.team_api_key, contracts) as gateway:
        for case_id in case_ids:
            case = json.loads((ROOT / "inputs" / f"{case_id}.json").read_text(encoding="utf-8"))
            claimed = case["customer_request"]["claims"][0]["topic"]
            trace.emit(case_id=case_id, event_type="case_received", actor="coordinator")
            try:
                output = await solve_case(case, gateway, trace)
                contracts.validate_output(output, case_id)
            except Exception as exc:  # noqa: BLE001 — smoke test cần báo mọi lỗi
                failures += 1
                print(f"✗ {case_id}  claim={claimed:<24} LỖI: {type(exc).__name__}: {exc}"[:240])
                continue

            if as_json:
                print(json.dumps(output, ensure_ascii=False, indent=2))
                continue

            a = output["assessment"]
            f = output["financial_resolution"]
            refs = len(output["evidence_refs"])

            # Không có evidence nghĩa là MCP hỏng, KHÔNG phải case khó.
            # Đây là lỗi, không được báo xanh.
            if refs == 0:
                failures += 1
                mark = "✗"
            else:
                mark = "✓"
            print(
                f"{mark} {case_id}  claim={claimed:<24} issue={a['primary_issue']:<24} "
                f"status={a['case_status']:<20} conf={a['confidence']:.2f} "
                f"refund={f['recommended_refund_brl']:>8.2f} "
                f"refs={refs}  {output['resolution_actions']}"
            )

    total = len(case_ids)
    print()
    if failures:
        print(f"KẾT QUẢ: ĐỎ — {failures}/{total} case không lấy được evidence hoặc lỗi.")
        print("Mọi case ra insufficient_evidence với refs=0 nghĩa là kết nối MCP hỏng,")
        print("không phải luật nghiệp vụ sai. Kiểm tra gói 'h2' đã cài chưa.")
    else:
        print(f"KẾT QUẢ: XANH — {total}/{total} case có evidence thật và output hợp lệ schema")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Chạy thử workflow trên vài case thật")
    parser.add_argument("cases", nargs="*", help="case id (mặc định: 5 case đại diện)")
    parser.add_argument("--json", action="store_true", help="in output JSON đầy đủ")
    args = parser.parse_args()
    return asyncio.run(run(args.cases or DEFAULT_CASES, args.json))


if __name__ == "__main__":
    raise SystemExit(main())
