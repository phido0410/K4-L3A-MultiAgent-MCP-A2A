"""Dump dữ liệu thô MCP của một case để soi khi kết luận sai.

    python scripts/dump_case.py L3A_CASE_010
    python scripts/dump_case.py L3A_CASE_010 --full   # in cả JSON đầy đủ

Dùng SDK (HTTP/2) nên chạy được ở nơi scripts/mcp_probe.py bị curl chặn.
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

TOOLS = ["get_order", "get_order_items", "get_shipment_summary", "get_payment_timeline",
         "get_refund_timeline"]


async def run(case_id: str, full: bool) -> None:
    settings = Settings.load(ROOT)
    contracts = Contracts(ROOT / "contracts" / "schemas")
    case = json.loads((ROOT / "inputs" / f"{case_id}.json").read_text(encoding="utf-8"))
    order_id = case["customer_request"]["claimed_order_id"]

    topic = case["customer_request"]["claims"][0]["topic"]
    print(f"{case_id}  opened_at={case['opened_at']}  claim={topic}")
    print(f"order_id={order_id}\n")

    async with connect_gateway(settings.mcp_endpoint, settings.team_api_key, contracts) as gateway:
        for tool in TOOLS:
            try:
                data = (await gateway.call(tool, case_id=case_id, order_id=order_id))["data"]
            except Exception as exc:  # noqa: BLE001 — dump cần thấy cả lỗi
                print(f"--- {tool}: LỖI {type(exc).__name__}\n")
                continue
            print(f"--- {tool}")
            if full:
                print(json.dumps(data, ensure_ascii=False, indent=2))
                print()
                continue
            if tool == "get_shipment_summary":
                print(f"    status={data.get('order_status')}")
                print(f"    carrier_at ={data.get('delivered_carrier_at')}")
                print(f"    customer_at={data.get('delivered_customer_at')}")
                print(f"    estimated  ={data.get('estimated_delivery_at')}")
                for lim in data.get("shipping_limits") or []:
                    print(f"    LIMIT {lim.get('shipping_limit_at')}"
                          f"  seller={lim.get('seller_id')}")
                for e in data.get("events") or []:
                    print(f"    EVENT {e.get('event_at')}  {e.get('event_type')}"
                          f"  actor={e.get('actor')}  status={e.get('status')}")
            elif tool == "get_order":
                for k in ("order_status", "order_purchase_timestamp", "order_approved_at",
                          "order_delivered_carrier_date", "order_delivered_customer_date",
                          "order_estimated_delivery_date"):
                    print(f"    {k:32}= {data.get(k)}")
            elif tool == "get_order_items":
                for row in data if isinstance(data, list) else [data]:
                    print(f"    ITEM {row.get('order_item_id')}"
                          f"  limit={row.get('shipping_limit_date')}"
                          f"  price={row.get('price')}  freight={row.get('freight_value')}")
            else:
                for e in data.get("events") or []:
                    print(f"    EVENT {e.get('event_at')}  {e.get('event_type')}"
                          f"  amount={e.get('amount_brl')}  status={e.get('status')}")
            print()


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump dữ liệu MCP thô của một case")
    parser.add_argument("case_id")
    parser.add_argument("--full", action="store_true", help="in JSON đầy đủ")
    args = parser.parse_args()
    asyncio.run(run(args.case_id, args.full))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
